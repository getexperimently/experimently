# Database Backup Schedules and Retention Policies

This document outlines the backup schedules and retention policies for all database resources in the experimentation platform infrastructure.

## Overview

The experimentation platform uses three primary database technologies:
- **Aurora PostgreSQL**: For relational data storage
- **DynamoDB**: For NoSQL data storage
- **ElastiCache Redis**: For caching and ephemeral data

Each database resource has its own backup mechanism and retention policy that is configured appropriately based on environment (development, staging, production).

## Aurora PostgreSQL

### Backup Mechanism

Aurora PostgreSQL protects the cluster with:
1. **Automated backups**: a daily snapshot and continuous backup of the transaction log, which
   together allow point-in-time recovery to any moment within the retention period
2. **Manual snapshots**: `deploy.yml` takes one before every deploy's migration
   (`pre-deploy-<env>-<tag>-<time>`); they are kept until you delete them
3. **A final snapshot** when the prod database stack is deleted

### Backup and Maintenance Windows

The stack sets no preferred backup window and no preferred maintenance window, so Aurora
chooses both for the cluster's region.

### Retention Policy

| Environment | Automated Backup Retention | Point-in-Time Recovery | Manual Snapshot Retention |
|-------------|----------------------------|------------------------|---------------------------|
| Production  | 35 days                    | Up to 35 days          | Until manually deleted    |
| Staging     | 35 days                    | Up to 35 days          | Until manually deleted    |
| Any other   | 1 day                      | Up to 1 day            | Until manually deleted    |

### Implementation

The retention is what the stack sets: `aurora_backup_retention_days()` in
`infrastructure/cdk/stacks/environments.py` returns it per environment, and
`infrastructure/cdk/stacks/enhanced_database_stack.py` passes it to the cluster as
`backup=rds.BackupProps(retention=Duration.days(...))`. 35 days is the most Aurora allows.

A cluster deployed from an earlier version of the CDK app, which set no retention, keeps
CloudFormation's default of 1 day until its database stack is redeployed. Check what a cluster
actually keeps with `aws rds describe-db-clusters --query 'DBClusters[].BackupRetentionPeriod'`.

### Disaster Recovery

In case of database failure:
1. In prod, Aurora fails over to the reader instance. Staging and other environments run a
   single instance, so Aurora replaces it instead, which takes longer
2. For complete cluster failure, restore to a new cluster from an automated backup or a manual
   snapshot
3. Point-in-time recovery can restore to any point within the retention period

The procedures are in the [Disaster Recovery Plan](../../deployment/disaster-recovery.md).

## DynamoDB Tables

### Backup Mechanism

DynamoDB uses two types of backups:
1. **Point-in-Time Recovery (PITR)**: Continuous backups allowing restoration to any point within the last 35 days
2. **On-Demand Backups**: Manual or scheduled backups retained until explicitly deleted

### Backup Configuration

| Environment | PITR Enabled | Backup Frequency  |
|-------------|--------------|-------------------|
| Development | Yes          | On-demand only    |
| Staging     | Yes          | On-demand only    |
| Production  | Yes          | Daily + On-demand |

### Retention Policy

| Environment | PITR Retention | On-Demand Backup Retention |
|-------------|----------------|----------------------------|
| Development | 35 days        | Until manually deleted     |
| Staging     | 35 days        | Until manually deleted     |
| Production  | 35 days        | 90 days (then archived)    |

### Implementation

Point-in-time recovery is enabled in the table configuration:

```python
table = dynamodb.Table(
    # ... other configuration ...
    point_in_time_recovery=True,
    # ... other configuration ...
)
```

### Disaster Recovery

In case of data loss:
1. For accidental writes/deletes: Use PITR to restore to a point before the incident
2. For table deletion: Restore from the most recent on-demand backup
3. For region-wide issues: Cross-region backups can be restored in another region

## ElastiCache Redis

### Backup Mechanism

ElastiCache Redis uses snapshot-based backups:
1. **Automatic Snapshots**: Taken daily during the configured backup window
2. **Manual Snapshots**: Can be taken at any time

### Backup Windows

| Environment | Backup Window (UTC) | Maintenance Window (UTC) |
|-------------|---------------------|--------------------------|
| Development | 02:00-03:00         | Sun 04:00-05:00          |
| Staging     | 02:00-03:00         | Sun 04:00-05:00          |
| Production  | 02:00-03:00         | Sun 04:00-05:00          |

### Retention Policy

| Environment | Snapshot Retention |
|-------------|-------------------|
| Development | 1 day             |
| Staging     | 3 days            |
| Production  | 7 days            |

### Implementation

The snapshot retention is configured based on environment:

```python
def _get_snapshot_retention_for_env(self, environment: str) -> int:
    """
    Get the appropriate Redis snapshot retention period based on environment.
    """
    if environment == "prod":
        return 7  # 7 days retention in production
    elif environment == "staging":
        return 3  # 3 days retention in staging
    else:  # dev, test, etc.
        return 1  # 1 day retention in dev/test
```

And applied in the Redis cluster configuration:

```python
self.redis_cluster = elasticache.CfnReplicationGroup(
    # ... other configuration ...
    snapshot_retention_limit=self._get_snapshot_retention_for_env(environment),
    snapshot_window="02:00-03:00",  # UTC
    # ... other configuration ...
)
```

### Disaster Recovery

In case of Redis failure:
1. For multi-node deployments (staging and production), automatic failover will occur
2. For complete cluster failure, restore from the most recent snapshot
3. Since Redis is primarily used for caching, some data loss may be acceptable as the data can be rebuilt from primary sources

## Additional Information

### Encryption

All backups are encrypted:
- **Aurora PostgreSQL**: Backups are encrypted using the same KMS key as the database
- **DynamoDB**: Backups are encrypted by default using AWS managed keys
- **ElastiCache Redis**: Snapshots are encrypted if the cluster has encryption at rest enabled

### Monitoring

Backup success/failure is monitored through:
- CloudWatch alarms for failed backup events
- SNS notifications for critical backup failures
- Automated weekly backup verification

### Backup Testing

Regular backup testing is performed following this schedule:
- **Development**: Quarterly
- **Staging**: Monthly
- **Production**: Monthly

### Compliance

The backup and retention policies are designed to meet:
- General data protection requirements
- Disaster recovery best practices
- Industry standard RPO (Recovery Point Objective) and RTO (Recovery Time Objective) guidelines

## Backup Management Responsibilities

| Task                         | Responsible Team    | Frequency         |
|------------------------------|---------------------|-------------------|
| Monitor backup jobs          | DevOps              | Daily             |
| Test recovery procedures     | DevOps, Engineering | Monthly           |
| Review retention policies    | Engineering, DevOps | Quarterly         |
| Update backup documentation  | Engineering         | As needed         |
