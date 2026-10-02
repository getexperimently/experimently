from aws_cdk import (
    Duration,
    Stack,
    CfnOutput,
    Tags,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    aws_kms as kms,
    aws_ssm as ssm,
)
from constructs import Construct

from stacks.environments import (
    aurora_backup_retention_days,
    aurora_instance_count,
    data_removal_policy,
    database_removal_policy,
)
from stacks.names import aurora_cluster_identifier_parameter

# The one Aurora PostgreSQL engine version every environment's cluster and both
# parameter groups use. It must be a version RDS still offers for new clusters:
# 15.3 is deprecated and no longer orderable, so no environment could
# be created. 15.17 is the highest 15.x constant in the pinned aws-cdk-lib and,
# when checked in us-west-2, was orderable for db.t3.medium and db.r5.large; the
# parameter group family is unchanged (aurora-postgresql15). Pinned by
# infrastructure/tests/test_aurora_engine.py.
AURORA_POSTGRES_VERSION = rds.AuroraPostgresEngineVersion.VER_15_17


class EnhancedDatabaseStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, vpc, environment="dev", **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Use existing security group from VPC stack if available, otherwise create one
        if hasattr(vpc, "db_security_group"):
            rds_security_group = vpc.db_security_group
        else:
            rds_security_group = ec2.SecurityGroup(
                self,
                "RDSSecurityGroup",
                vpc=vpc,
                description="Security group for Aurora PostgreSQL",
                allow_all_outbound=False,
            )

            # Add explicit ingress rule for PostgreSQL port from application security group
            if hasattr(vpc, "app_security_group"):
                rds_security_group.add_ingress_rule(
                    peer=vpc.app_security_group,
                    connection=ec2.Port.tcp(5432),
                    description="Allow PostgreSQL access from application tier",
                )

            # Add bastion access if available
            if hasattr(vpc, "bastion_security_group"):
                rds_security_group.add_ingress_rule(
                    peer=vpc.bastion_security_group,
                    connection=ec2.Port.tcp(5432),
                    description="Allow PostgreSQL access from bastion hosts",
                )

        # 1. CREATE KMS KEY FOR ENCRYPTION
        db_encryption_key = kms.Key(
            self,
            "DatabaseEncryptionKey",
            alias=f"alias/{construct_id}-postgres-key",
            description=f"KMS key for {construct_id} PostgreSQL encryption",
            enable_key_rotation=True,
            # Kept in prod, where the retained cluster snapshot is encrypted
            # with it and unreadable without it. Elsewhere the cluster is
            # destroyed without a snapshot, so the key has nothing to protect
            # and is scheduled for deletion (stacks/environments.py).
            removal_policy=data_removal_policy(environment),
        )

        # Tag the key for easier identification
        Tags.of(db_encryption_key).add("Name", f"{construct_id}-postgres-key")
        Tags.of(db_encryption_key).add("Environment", environment)

        # 2. CREATE CUSTOM PARAMETER GROUPS
        # 2.1 DB Cluster Parameter Group
        db_cluster_parameter_group = rds.ParameterGroup(
            self,
            "ClusterParameterGroup",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=AURORA_POSTGRES_VERSION
            ),
            description=f"Parameter group for {construct_id} Aurora PostgreSQL cluster",
            parameters={
                "shared_preload_libraries": "pg_stat_statements",
                "timezone": "UTC",
                "rds.force_ssl": "1",  # Force SSL connections
            },
        )

        # 2.2 DB Instance Parameter Group
        db_instance_parameter_group = rds.ParameterGroup(
            self,
            "InstanceParameterGroup",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=AURORA_POSTGRES_VERSION
            ),
            description=f"Parameter group for {construct_id} Aurora PostgreSQL instances",
            parameters={
                # Performance tuning. shared_buffers and effective_cache_size
                # are deliberately left at Aurora's defaults, which scale with
                # the instance class. Both are in 8 kB pages, and the values
                # that used to be here were written as kB: shared_buffers came
                # to more than the instance's whole memory (16 GiB on a 4 GiB
                # staging instance, 32 GiB on a 16 GiB prod one).
                "work_mem": self._get_work_mem_for_env(environment),
                "maintenance_work_mem": "65536",
                "random_page_cost": "1.1",  # Optimized for SSD storage
                # Logging settings
                "log_statement": "ddl",  # Log DDL statements
                "log_min_duration_statement": "1000",  # Log slow queries (> 1sec)
                "log_connections": "1",
                "log_disconnections": "1",
                "log_lock_waits": "1",
                "log_temp_files": "0",
                # Query optimization
                # "autovacuum": "1",
                # "autovacuum_vacuum_scale_factor": "0.1",
                # "autovacuum_analyze_scale_factor": "0.05",# Not supported in this ver
            },
        )

        # 3. CREATE SUBNET GROUP
        db_subnet_group = rds.SubnetGroup(
            self,
            "DBSubnetGroup",
            description=f"Subnet group for {construct_id} Aurora PostgreSQL",
            vpc=vpc,
            # For production, use isolated subnets for better security
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=(
                    ec2.SubnetType.PRIVATE_ISOLATED
                    if environment == "prod"
                    else ec2.SubnetType.PRIVATE_WITH_EGRESS
                )
            ),
        )

        # 4. CREATE DATABASE CREDENTIALS IN SECRETS MANAGER
        # Generate a descriptive name for the secret
        secret_name = f"{construct_id}-aurora-credentials"

        db_credentials = secretsmanager.Secret(
            self,
            "DBCredentials",
            secret_name=secret_name,
            description=f"Credentials for {construct_id} Aurora PostgreSQL",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "postgres"}',
                generate_string_key="password",
                exclude_characters='"@/\\',  # Exclude problematic characters
                exclude_punctuation=False,  # Include some punctuation for stronger passwords
                password_length=32,
            ),
        )

        # Store the secret ARN in SSM for easy retrieval
        ssm.StringParameter(
            self,
            "DBSecretArnParam",
            parameter_name=f"/experimentation/{environment}/database/aurora-secret-arn",
            string_value=db_credentials.secret_arn,
            description=f"Secret ARN for {construct_id} Aurora PostgreSQL credentials",
        )

        # 5. DETERMINE ENVIRONMENT-SPECIFIC CONFIGURATIONS
        # A writer and a reader in prod; one instance elsewhere (T24). Staging
        # used to get the pair.
        instance_count = aurora_instance_count(environment)

        instance_type = (
            ec2.InstanceType.of(ec2.InstanceClass.MEMORY5, ec2.InstanceSize.LARGE)
            if environment == "prod"
            else ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE3, ec2.InstanceSize.MEDIUM
            )
        )

        # 6. CREATE AURORA POSTGRESQL CLUSTER WITH MINIMAL SETTINGS
        # Only using the most basic, universally supported parameters
        self.aurora_cluster = rds.DatabaseCluster(
            self,
            "AuroraCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=AURORA_POSTGRES_VERSION
            ),
            credentials=rds.Credentials.from_secret(db_credentials),
            default_database_name="experimentation",
            instances=instance_count,
            instance_props=rds.InstanceProps(
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=(
                        ec2.SubnetType.PRIVATE_ISOLATED
                        if environment == "prod"
                        else ec2.SubnetType.PRIVATE_WITH_EGRESS
                    )
                ),
                instance_type=instance_type,
                security_groups=[rds_security_group],
                parameter_group=db_instance_parameter_group,
            ),
            parameter_group=db_cluster_parameter_group,
            subnet_group=db_subnet_group,
            storage_encrypted=True,
            storage_encryption_key=db_encryption_key,
            # A final snapshot in prod; nothing elsewhere. A snapshot is a
            # billed resource `cdk destroy` leaves behind, which staging
            # should not (stacks/environments.py).
            removal_policy=database_removal_policy(environment),
            # 35 days of automated backups and point-in-time restore in prod
            # and staging, 1 elsewhere (#391). No preferred window is set, so
            # Aurora keeps choosing it.
            backup=rds.BackupProps(
                retention=Duration.days(aurora_backup_retention_days(environment))
            ),
        )

        # What the application tasks need from this stack (#78): the WRITER
        # endpoint -- never the read endpoint, which refuses every write the
        # API and the migrations make -- the credentials Aurora was actually
        # created with, and the security group that has to admit them.
        # fargate_service_stack.py and migration_task_stack.py take these from
        # app.py, so each environment's tasks import this environment's values.
        self.writer_host = self.aurora_cluster.cluster_endpoint.hostname
        self.db_credentials = db_credentials
        self.rds_security_group = rds_security_group

        # Add tags to the database cluster for easier identification and management
        Tags.of(self.aurora_cluster).add("Name", f"{construct_id}-aurora-cluster")
        Tags.of(self.aurora_cluster).add("Environment", environment)
        Tags.of(self.aurora_cluster).add("Service", "experimently")

        # 7. STORE CONNECTION INFORMATION IN SSM FOR EASY ACCESS
        ssm.StringParameter(
            self,
            "DBHostParam",
            parameter_name=f"/experimentation/{environment}/database/aurora-host",
            string_value=self.aurora_cluster.cluster_endpoint.hostname,
            description=f"Host for {construct_id} Aurora PostgreSQL",
        )

        ssm.StringParameter(
            self,
            "DBPortParam",
            parameter_name=f"/experimentation/{environment}/database/aurora-port",
            string_value=str(self.aurora_cluster.cluster_endpoint.port),
            description=f"Port for {construct_id} Aurora PostgreSQL",
        )

        # The cluster's identifier, for the monitoring stack's AuroraHighCPU
        # alarm (#390): CloudWatch publishes Aurora's metrics under it, and the
        # alarm named the literal "AuroraCluster", which no cluster is called.
        # A parameter, not an export, so this stack is not pinned by an
        # import; the name is shared through stacks/names.py. The cluster
        # itself is deliberately not renamed (see the ClusterIdentifier
        # output below).
        ssm.StringParameter(
            self,
            "DBClusterIdentifierParam",
            parameter_name=aurora_cluster_identifier_parameter(environment),
            string_value=self.aurora_cluster.cluster_identifier,
            description=f"Cluster identifier for {construct_id} Aurora PostgreSQL",
        )

        ssm.StringParameter(
            self,
            "DBNameParam",
            parameter_name=f"/experimentation/{environment}/database/aurora-name",
            string_value="experimentation",
            description=f"Database name for {construct_id} Aurora PostgreSQL",
        )

        # 8. CREATE CLOUDFORMATION OUTPUTS
        CfnOutput(
            self,
            "ClusterEndpoint",
            value=self.aurora_cluster.cluster_endpoint.socket_address,
            description="Aurora PostgreSQL cluster endpoint",
            export_name=f"{self.stack_name}-ClusterEndpoint",
        )

        CfnOutput(
            self,
            "ClusterReadEndpoint",
            value=self.aurora_cluster.cluster_read_endpoint.socket_address,
            description="Aurora PostgreSQL read endpoint",
            export_name=f"{self.stack_name}-ReadEndpoint",
        )

        # The cluster's identifier, which the deploy workflows pass to
        # `rds create-db-cluster-snapshot`. CloudFormation generates it (the
        # cluster is deliberately not renamed: a DBClusterIdentifier change
        # REPLACES the cluster), so the only way to learn it is to ask the
        # stack. Not exported: `describe-stacks` reads an output, and an export
        # would be one more thing pinning this stack in place.
        CfnOutput(
            self,
            "ClusterIdentifier",
            value=self.aurora_cluster.cluster_identifier,
            description="Aurora PostgreSQL cluster identifier",
        )

        CfnOutput(
            self,
            "SecretArn",
            value=db_credentials.secret_arn,
            description="Secret ARN for database credentials",
            export_name=f"{self.stack_name}-SecretArn",
        )

    # HELPER METHODS
    def _get_work_mem_for_env(self, environment):
        if environment == "prod":
            return "16384"  # 16MB in KB
        elif environment == "staging":
            return "8192"  # 8MB in KB
        else:
            return "4096"  # 4MB in KB
