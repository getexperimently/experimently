"""Two environments in one account neither collide nor leave billed residue.

#139 and #142, on a real ``app.synth()`` of every environment ``app.py``
accepts. Four properties, each asserted as exact values:

* **Names.** No account-scoped physical name is the same in two environments.
  Before this, dev and staging collided on 25 names plus the three Glue jobs
  and crawler -- the ECS cluster (``experimentation-dev`` in every
  environment, #142), the CodeDeploy application, the migration task family,
  fourteen alarms and dashboards, seven SSM parameters -- so the second
  environment deployed into an account failed on the first of them. A
  completeness guard classifies every CloudFormation resource type the app
  synthesises, so a new type cannot slip past the name scan unexamined.
* **Retention.** The exact DeletionPolicy of every resource that carries one,
  per environment: RETAIN/SNAPSHOT in prod, Delete everywhere else. A staging
  teardown left sixteen resources behind, eight of them named, so the next
  staging deploy failed on the names.
* **Sizing.** The exact Aurora instance and NAT gateway count per environment
  (T24, DECISIONS D7).
* **Teardown.** The stacks that must be destroyed before the cluster rename can
  reach an existing environment are *derived from the synthesised import
  graph*, and docs/self-hosting/cdk.md must name exactly those.
"""

from __future__ import annotations

import re

import pytest

from .test_app_profiles import REPO_ROOT
from .test_dashboard_service import _synth

ENVIRONMENTS = ("dev", "staging", "prod", "demo")
MODULES_PRESENT = (REPO_ROOT / "modules" / "infrastructure" / "cdk" / "stacks").is_dir()
CDK_DOC = REPO_ROOT / "docs" / "self-hosting" / "cdk.md"

#: Where each resource type keeps a physical name that must be unique in an
#: account (and region). Stricter than AWS in places -- a Cognito pool name or
#: an ECS service name need not be unique -- because an environment-scoped name
#: costs nothing and a shared one has to be reasoned about.
NAME_PROPERTIES: dict[str, tuple[str, ...]] = {
    "AWS::CloudWatch::Alarm": ("AlarmName",),
    "AWS::CloudWatch::Dashboard": ("DashboardName",),
    "AWS::CodeDeploy::Application": ("ApplicationName",),
    "AWS::CodeDeploy::DeploymentGroup": ("DeploymentGroupName",),
    "AWS::Cognito::UserPool": ("UserPoolName",),
    "AWS::DynamoDB::Table": ("TableName",),
    "AWS::EC2::SecurityGroup": ("GroupName",),
    "AWS::ECS::Cluster": ("ClusterName",),
    "AWS::ECS::Service": ("ServiceName",),
    "AWS::ECS::TaskDefinition": ("Family",),
    "AWS::ElastiCache::ReplicationGroup": ("ReplicationGroupId",),
    "AWS::ElastiCache::SubnetGroup": ("CacheSubnetGroupName",),
    "AWS::ElasticLoadBalancingV2::LoadBalancer": ("Name",),
    "AWS::ElasticLoadBalancingV2::TargetGroup": ("Name",),
    "AWS::Events::Rule": ("Name",),
    "AWS::Glue::Crawler": ("Name",),
    "AWS::Glue::Database": ("DatabaseInput.Name",),
    "AWS::Glue::Job": ("Name",),
    "AWS::IAM::ManagedPolicy": ("ManagedPolicyName",),
    "AWS::IAM::Role": ("RoleName",),
    "AWS::KMS::Alias": ("AliasName",),
    "AWS::KMS::Key": (),  # addressed by generated id; its alias is the name
    "AWS::Kinesis::Stream": ("Name",),
    "AWS::KinesisFirehose::DeliveryStream": ("DeliveryStreamName",),
    "AWS::Lambda::Function": ("FunctionName",),
    "AWS::Logs::LogGroup": ("LogGroupName",),
    "AWS::OpenSearchService::Domain": ("DomainName",),
    "AWS::RDS::DBCluster": ("DBClusterIdentifier",),
    "AWS::RDS::DBClusterParameterGroup": ("DBClusterParameterGroupName",),
    "AWS::RDS::DBInstance": ("DBInstanceIdentifier",),
    "AWS::RDS::DBParameterGroup": ("DBParameterGroupName",),
    "AWS::RDS::DBSubnetGroup": ("DBSubnetGroupName",),
    "AWS::S3::Bucket": ("BucketName",),
    "AWS::SNS::Topic": ("TopicName",),
    "AWS::SSM::Parameter": ("Name",),
    "AWS::SecretsManager::Secret": ("Name",),
}

#: Types with no physical name an account could hold twice, and why.
NO_ACCOUNT_SCOPED_NAME: dict[str, str] = {
    "AWS::ApplicationAutoScaling::ScalableTarget": "identified by the resource it scales",
    "AWS::ApplicationAutoScaling::ScalingPolicy": "PolicyName is scoped to its scalable target",
    "AWS::Cognito::UserPoolClient": "ClientName is scoped to its user pool",
    "AWS::EC2::EIP": "no name",
    "AWS::EC2::InternetGateway": "no name (a Name tag is not unique)",
    "AWS::EC2::NatGateway": "no name (a Name tag is not unique)",
    "AWS::EC2::NetworkAcl": "no name",
    "AWS::EC2::NetworkAclEntry": "no name",
    "AWS::EC2::Route": "no name",
    "AWS::EC2::RouteTable": "no name",
    "AWS::EC2::SecurityGroupEgress": "no name",
    "AWS::EC2::SecurityGroupIngress": "no name",
    "AWS::EC2::Subnet": "no name",
    "AWS::EC2::SubnetNetworkAclAssociation": "no name",
    "AWS::EC2::SubnetRouteTableAssociation": "no name",
    "AWS::EC2::VPC": "no name",
    "AWS::EC2::VPCEndpoint": "no name",
    "AWS::EC2::VPCGatewayAttachment": "no name",
    "AWS::ElasticLoadBalancingV2::Listener": "no name",
    "AWS::ElasticLoadBalancingV2::ListenerRule": "no name",
    "AWS::IAM::Policy": "an inline policy: PolicyName is scoped to its role",
    "AWS::Lambda::EventSourceMapping": "no name",
    "AWS::Lambda::Permission": "no name",
    "AWS::Logs::MetricFilter": "FilterName is scoped to its log group",
    "AWS::S3::BucketPolicy": "no name",
    "AWS::SNS::Subscription": "no name",
    "AWS::SecretsManager::SecretTargetAttachment": "no name",
    "AWS::CDK::Metadata": "no name",
    "Custom::OpenSearchAccessPolicy": "a custom resource: no name",
    "Custom::S3AutoDeleteObjects": "a custom resource: no name",
}

#: Pairs of environments allowed to share a physical name. Empty, and meant
#: to stay that way.
SHARED_NAME_ALLOW_LIST: frozenset[tuple[str, str]] = frozenset()

#: CloudFormation pseudo parameters: the SAME value in every environment of
#: one account, so a name built only from literals and these is a literal.
PSEUDO_PARAMETERS = {
    "AWS::AccountId",
    "AWS::Region",
    "AWS::Partition",
    "AWS::URLSuffix",
}


class Synth:
    """One environment's assembly, reduced to what these tests read."""

    def __init__(self, env: str):
        assembly = _synth(env)
        self.env = env
        self.templates = {s.stack_name: s.template for s in assembly.stacks}
        self.dependencies = {
            s.stack_name: {
                d.stack_name for d in s.dependencies if hasattr(d, "stack_name")
            }
            for s in assembly.stacks
        }

    def short(self, stack_name: str) -> str:
        """``experimentation-fargate-staging`` -> ``experimentation-fargate``."""
        suffix = f"-{self.env}"
        assert stack_name.endswith(suffix), stack_name
        return stack_name[: -len(suffix)]

    def resources(self):
        for stack_name, template in sorted(self.templates.items()):
            for logical_id, resource in sorted(template.get("Resources", {}).items()):
                yield stack_name, logical_id, resource


@pytest.fixture(scope="module")
def synths() -> dict[str, Synth]:
    return {env: Synth(env) for env in ENVIRONMENTS}


def _get(properties: dict, path: str):
    value = properties
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _literal(value) -> str | None:
    """The value as the same string in every environment, or ``None``.

    A plain string is literal. So is an ``Fn::Join`` / ``Fn::Sub`` built only
    from strings and pseudo parameters -- ``foo-${AWS::Region}`` is ``foo-`` in
    every environment of a region. Anything referring to a resource (``Ref``,
    ``Fn::GetAtt``, ``Fn::ImportValue``) takes that resource's unique value.
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, dict) or len(value) != 1:
        return None
    ((function, argument),) = value.items()
    if function == "Ref":
        return f"${{{argument}}}" if argument in PSEUDO_PARAMETERS else None
    if function == "Fn::Join":
        separator, parts = argument
        rendered = [_literal(part) for part in parts]
        return None if None in rendered else separator.join(rendered)
    if function == "Fn::Sub" and isinstance(argument, str):
        references = set(re.findall(r"\$\{([^}]+)\}", argument))
        return argument if references <= PSEUDO_PARAMETERS else None
    return None


def literal_names(synth: Synth) -> dict[tuple[str, str], list[str]]:
    """``(type, literal name) -> [stack/logical id]`` for every named resource."""
    found: dict[tuple[str, str], list[str]] = {}
    for stack_name, logical_id, resource in synth.resources():
        for path in NAME_PROPERTIES.get(resource["Type"], ()):
            name = _literal(_get(resource.get("Properties") or {}, path))
            if name is not None:
                found.setdefault((resource["Type"], name), []).append(
                    f"{stack_name}/{logical_id}"
                )
    return found


# --- names ------------------------------------------------------------------


def test_every_resource_type_is_classified(synths):
    """A type the scan does not know is a type whose name nobody checked."""
    seen = {
        resource["Type"]
        for synth in synths.values()
        for _, _, resource in synth.resources()
    }
    unclassified = sorted(seen - NAME_PROPERTIES.keys() - NO_ACCOUNT_SCOPED_NAME.keys())
    assert not unclassified, (
        f"{unclassified} is not classified: add it to NAME_PROPERTIES with the "
        "property holding its physical name, or to NO_ACCOUNT_SCOPED_NAME with "
        "the reason it has none"
    )
    both = sorted(NAME_PROPERTIES.keys() & NO_ACCOUNT_SCOPED_NAME.keys())
    assert not both, f"{both} is classified both ways"


def test_the_name_scan_reads_the_names_that_matter(synths):
    """Not vacuous: the scan finds the names the deploy workflows address."""
    names = literal_names(synths["staging"])
    expected = {
        ("AWS::ECS::Cluster", "experimentation-staging"),
        ("AWS::CodeDeploy::Application", "experimentation-platform-staging"),
        ("AWS::ECS::TaskDefinition", "experimentation-migrate-staging"),
        ("AWS::ECS::TaskDefinition", "experimentation-backend-staging"),
        ("AWS::Logs::LogGroup", "/ecs/experimentation-backend-staging"),
        ("AWS::SSM::Parameter", "/experimentation/staging/vpc/id"),
        ("AWS::SNS::Topic", "experimentation-alerts-staging"),
    }
    if MODULES_PRESENT:
        expected |= {
            ("AWS::Glue::Job", "experimentation-events-etl-staging"),
            ("AWS::Glue::Database", "experimentation_staging"),
        }
    assert expected <= names.keys(), sorted(expected - names.keys())
    assert len(names) >= 50, len(names)


@pytest.mark.regression
@pytest.mark.parametrize(
    "first, second",
    [(a, b) for i, a in enumerate(ENVIRONMENTS) for b in ENVIRONMENTS[i + 1 :]],
)
def test_two_environments_share_no_physical_name(synths, first, second):
    """#139: dev and staging collided on 25 names and three Glue names."""
    if (first, second) in SHARED_NAME_ALLOW_LIST:
        pytest.skip("allow-listed")
    a, b = literal_names(synths[first]), literal_names(synths[second])
    shared = sorted(a.keys() & b.keys())
    assert not shared, "\n".join(
        f"{rtype} {name!r} is identical in {first} ({a[(rtype, name)]}) and "
        f"{second}; an account can hold only one"
        for rtype, name in shared
    )


@pytest.mark.regression
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_the_cluster_is_named_for_its_environment(synths, env):
    """#142: the cluster was `experimentation-dev` in every environment."""
    clusters = [
        r["Properties"].get("ClusterName")
        for _, _, r in synths[env].resources()
        if r["Type"] == "AWS::ECS::Cluster"
    ]
    assert clusters == [f"experimentation-{env}"], (
        f"{env} cluster is {clusters}, expected experimentation-{env}"
    )


@pytest.mark.regression
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_no_lambda_is_told_it_runs_in_another_environment(synths, env):
    """The same context key made the analytics Lambda say ENVIRONMENT=dev."""
    told = {
        f"{stack}/{lid}": r["Properties"]["Environment"]["Variables"]["ENVIRONMENT"]
        for stack, lid, r in synths[env].resources()
        if r["Type"] == "AWS::Lambda::Function"
        and "ENVIRONMENT"
        in ((r["Properties"].get("Environment") or {}).get("Variables") or {})
    }
    expected_stacks = {f"experimentation-compute-{env}"}
    if MODULES_PRESENT:
        expected_stacks.add(f"experimentation-analytics-{env}")
    assert {key.split("/")[0] for key in told} == expected_stacks, told
    assert set(told.values()) == {env}, told


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_the_api_is_given_the_glue_names_the_glue_stack_creates(synths, env):
    """Renaming the Glue jobs must not strand the API on the old names."""
    if not MODULES_PRESENT:
        pytest.skip("core checkout: no etl module")
    created = {
        name
        for (rtype, name) in literal_names(synths[env])
        if rtype in ("AWS::Glue::Job", "AWS::Glue::Crawler", "AWS::Glue::Database")
    }
    fargate = synths[env].templates[f"experimentation-fargate-{env}"]["Resources"]
    (backend,) = [
        c
        for r in fargate.values()
        if r["Type"] == "AWS::ECS::TaskDefinition"
        and r["Properties"]["Family"] == f"experimentation-backend-{env}"
        for c in r["Properties"]["ContainerDefinitions"]
    ]
    told = {
        e["Name"]: e["Value"]
        for e in backend["Environment"]
        if e["Name"].startswith("GLUE_")
    }
    assert set(told) == {
        "GLUE_ETL_JOB_NAME",
        "GLUE_METRICS_JOB_NAME",
        "GLUE_DATABASE",
        "GLUE_CRAWLER_NAME",
    }, told
    assert set(told.values()) == created, (told, created)


# --- retention ----------------------------------------------------------------

#: Every resource that carries a DeletionPolicy, by (stack, type, logical id),
#: and what prod does with it. Outside prod every one of them is "Delete".
_CORE_POLICIES = {
    ("experimentation-auth", "AWS::Cognito::UserPool", "ExperimentationUserPool8B5B85D6"): "Retain",
    ("experimentation-compute", "AWS::Logs::LogGroup", "DatabaseLambdaLogs0B6EB9BE"): "Delete",
    ("experimentation-database", "AWS::RDS::DBCluster", "AuroraCluster23D869C0"): "Snapshot",
    ("experimentation-database", "AWS::RDS::DBInstance", "AuroraClusterInstance19E8278EB"): "Delete",
    ("experimentation-database", "AWS::SecretsManager::Secret", "DBCredentialsCBF39AE9"): "Delete",
    ("experimentation-database", "AWS::KMS::Key", "DatabaseEncryptionKey10487C37"): "Retain",
    ("experimentation-dynamodb", "AWS::DynamoDB::Table", "AssignmentsTableBD53780E"): "Retain",
    ("experimentation-dynamodb", "AWS::DynamoDB::Table", "EventsTableD24865E5"): "Retain",
    ("experimentation-dynamodb", "AWS::DynamoDB::Table", "ExperimentsTable057193CB"): "Retain",
    ("experimentation-dynamodb", "AWS::DynamoDB::Table", "FeatureFlagsTable00AD5587"): "Retain",
    ("experimentation-dynamodb", "AWS::DynamoDB::Table", "OverridesTable7BDFBA35"): "Retain",
    ("experimentation-fargate", "AWS::Logs::LogGroup", "BackendLogGroupDA10F1B2"): "Retain",
    ("experimentation-fargate", "AWS::Logs::LogGroup", "DashboardLogGroupE8E0E1A2"): "Retain",
    ("experimentation-migrations", "AWS::Logs::LogGroup", "MigrationLogs670D4322"): "Retain",
    ("experimentation-monitoring", "AWS::Logs::LogGroup", "ApplicationLogsAF17AEF2"): "Delete",
}
_MODULE_POLICIES = {
    ("experimentation-analytics", "AWS::S3::Bucket", "DataLakeBucket0256EA8E"): "Retain",
    ("experimentation-analytics", "AWS::Kinesis::Stream", "EventsStream287662BE"): "Retain",
    ("experimentation-analytics", "AWS::OpenSearchService::Domain", "ExperimentationDomain3B6A1339"): "Retain",
    ("experimentation-analytics", "Custom::OpenSearchAccessPolicy", "ExperimentationDomainAccessPolicyCF0D0276"): "Delete",
    ("experimentation-dynamodb-counters", "AWS::DynamoDB::Table", "ExperimentCountersTableE64AC51F"): "Retain",
    ("experimentation-glue-etl", "AWS::S3::Bucket", "AthenaResultsBucket879938FA"): "Retain",
    ("experimentation-glue-etl", "AWS::S3::Bucket", "GlueScriptsBucketCD60B14C"): "Retain",
}
#: Present only where the buckets are destroyed: the custom resources that
#: empty them first. Their provider -- the CDK's
#: Custom::S3AutoDeleteObjectsCustomResourceProvider Lambda and its role -- is
#: what `auto_delete_objects=True` adds to the stack.
_AUTO_DELETE = {
    ("experimentation-analytics", "Custom::S3AutoDeleteObjects", "DataLakeBucketAutoDeleteObjectsCustomResourceBA68F53A"),
    ("experimentation-glue-etl", "Custom::S3AutoDeleteObjects", "AthenaResultsBucketAutoDeleteObjectsCustomResourceD2206C34"),
    ("experimentation-glue-etl", "Custom::S3AutoDeleteObjects", "GlueScriptsBucketAutoDeleteObjectsCustomResource5EF6A9DF"),
}


def _expected_policies(env: str) -> dict[tuple[str, str, str], str]:
    prod = dict(_CORE_POLICIES)
    if MODULES_PRESENT:
        prod.update(_MODULE_POLICIES)
    if env == "prod":
        # prod's second Aurora instance (T24): a reader, deleted with the cluster.
        prod[("experimentation-database", "AWS::RDS::DBInstance", "AuroraClusterInstance2FE2217C4")] = "Delete"
        return prod
    expected = {key: "Delete" for key in prod}
    if MODULES_PRESENT:
        expected.update({key: "Delete" for key in _AUTO_DELETE})
    return expected


@pytest.mark.regression
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_retention_is_chosen_per_environment(synths, env):
    """The exact DeletionPolicy table: prod keeps its data, nothing else does.

    A staging teardown left 16 resources behind (#139): Cognito, six named
    DynamoDB tables, Kinesis, three buckets, OpenSearch, the KMS key, an Aurora
    snapshot and two named log groups. The named ones then made the next
    staging deploy fail.
    """
    synth = synths[env]
    actual = {
        (synth.short(stack), r["Type"], lid): r["DeletionPolicy"]
        for stack, lid, r in synth.resources()
        if "DeletionPolicy" in r
    }
    expected = _expected_policies(env)
    wrong = {
        key: (actual.get(key), policy)
        for key, policy in expected.items()
        if actual.get(key) != policy
    }
    extra = sorted(actual.keys() - expected.keys())
    assert not wrong and not extra, (
        f"{env}: (actual, expected) {wrong}; unexpected {extra}"
    )
    # UpdateReplacePolicy follows: a replacement must not orphan what a
    # deletion would have destroyed, or keep what it would have kept.
    for stack, lid, r in synth.resources():
        if "DeletionPolicy" in r:
            assert r.get("UpdateReplacePolicy") == r["DeletionPolicy"], (stack, lid)


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_a_destroyed_bucket_is_emptied_first(synths, env):
    """CloudFormation deletes only an empty bucket; the data lake never is."""
    if not MODULES_PRESENT:
        pytest.skip("core checkout: no buckets")
    synth = synths[env]
    buckets = {
        (stack, lid): r
        for stack, lid, r in synth.resources()
        if r["Type"] == "AWS::S3::Bucket"
    }
    emptied = {
        (stack, r["Properties"]["BucketName"]["Ref"])
        for stack, lid, r in synth.resources()
        if r["Type"] == "Custom::S3AutoDeleteObjects"
    }
    tagged = {
        key
        for key, r in buckets.items()
        if {"Key": "aws-cdk:auto-delete-objects", "Value": "true"}
        in ((r.get("Properties") or {}).get("Tags") or [])
    }
    assert len(buckets) == 3, sorted(buckets)
    if env == "prod":
        assert not emptied and not tagged, (emptied, tagged)
    else:
        assert emptied == set(buckets) == tagged, (sorted(buckets), emptied, tagged)


# --- sizing -------------------------------------------------------------------

AURORA_INSTANCES = {"dev": 1, "staging": 1, "prod": 2, "demo": 1}
NAT_GATEWAYS = {"dev": 1, "staging": 1, "prod": 2, "demo": 1}


def _count(synth: Synth, rtype: str) -> int:
    return sum(1 for _, _, r in synth.resources() if r["Type"] == rtype)


@pytest.mark.regression
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_aurora_instance_count_per_environment(synths, env):
    """T24 (EM condition 7): staging runs one instance, prod two."""
    assert _count(synths[env], "AWS::RDS::DBInstance") == AURORA_INSTANCES[env]


@pytest.mark.regression
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_nat_gateway_count_per_environment(synths, env):
    """DECISIONS D7: one NAT gateway outside prod."""
    assert _count(synths[env], "AWS::EC2::NatGateway") == NAT_GATEWAYS[env]


# --- outputs B3 reads -----------------------------------------------------------


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_the_stacks_say_what_a_workflow_needs_to_address(synths, env):
    """The cluster identifier, and where a one-off task must run."""
    synth = synths[env]
    database = synth.templates[f"experimentation-database-{env}"]
    (cluster_id,) = [
        lid for lid, r in database["Resources"].items() if r["Type"] == "AWS::RDS::DBCluster"
    ]
    assert database["Outputs"]["ClusterIdentifier"]["Value"] == {"Ref": cluster_id}

    compute = synth.templates[f"experimentation-compute-{env}"]
    (ecs_sg,) = [
        lid
        for lid, r in compute["Resources"].items()
        if r["Type"] == "AWS::EC2::SecurityGroup"
    ]
    outputs = synth.templates[f"experimentation-fargate-{env}"]["Outputs"]
    sg = outputs["TaskSecurityGroup"]["Value"]["Fn::ImportValue"]
    assert sg.startswith(f"experimentation-compute-{env}:") and ecs_sg in sg, sg

    separator, parts = outputs["TaskSubnets"]["Value"]["Fn::Join"]
    imports = [p["Fn::ImportValue"] for p in parts if isinstance(p, dict)]
    assert len(imports) == 2 and all("PrivateSubnet" in i for i in imports), parts

    # The service runs in exactly those subnets and that group.
    (service,) = [
        r
        for r in synth.templates[f"experimentation-fargate-{env}"]["Resources"].values()
        if r["Type"] == "AWS::ECS::Service"
        and r["Properties"].get("ServiceName") == f"experimentation-backend-{env}"
    ]
    network = service["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]
    assert [s["Fn::ImportValue"] for s in network["Subnets"]] == imports
    assert [g["Fn::ImportValue"] for g in network["SecurityGroups"]] == [sg]


# --- teardown -----------------------------------------------------------------


def _exports(synth: Synth) -> dict[str, str]:
    return {
        output["Export"]["Name"]: stack
        for stack, template in synth.templates.items()
        for output in template.get("Outputs", {}).values()
        if "Export" in output and isinstance(output["Export"]["Name"], str)
    }


def _imports(value, found: set[str]) -> set[str]:
    if isinstance(value, dict):
        if "Fn::ImportValue" in value and isinstance(value["Fn::ImportValue"], str):
            found.add(value["Fn::ImportValue"])
        for item in value.values():
            _imports(item, found)
    elif isinstance(value, list):
        for item in value:
            _imports(item, found)
    return found


def import_graph(synth: Synth) -> dict[str, set[str]]:
    """``export name -> {importing stack}`` over the whole app."""
    graph: dict[str, set[str]] = {name: set() for name in _exports(synth)}
    for stack, template in synth.templates.items():
        for name in _imports(template.get("Resources", {}), set()) | _imports(
            template.get("Outputs", {}), set()
        ):
            graph.setdefault(name, set()).add(stack)
    return graph


def cluster_export_importers(synth: Synth) -> set[str]:
    """The stacks importing the compute stack's ECS cluster ``Ref``."""
    compute = f"experimentation-compute-{synth.env}"
    (cluster,) = [
        lid
        for lid, r in synth.templates[compute]["Resources"].items()
        if r["Type"] == "AWS::ECS::Cluster"
    ]
    exported = [
        output["Export"]["Name"]
        for output in synth.templates[compute].get("Outputs", {}).values()
        if output["Value"] == {"Ref": cluster} and "Export" in output
    ]
    assert len(exported) == 1, exported
    return {synth.short(s) for s in import_graph(synth)[exported[0]]}


def _doc_section(title: str) -> str:
    text = CDK_DOC.read_text()
    match = re.search(rf"^### {re.escape(title)}\n(.*?)(?=^##)", text, re.M | re.S)
    assert match, f"{CDK_DOC} has no section '### {title}'"
    return match.group(1)


def _commands(section: str, verb: str) -> list[str]:
    """The stacks named by ``cdk <verb>`` lines, in order, ``-<env>`` stripped."""
    return [
        m.group(1)
        for m in re.finditer(
            rf"^cdk {verb}(?: --\w+)* (experimentation-[a-z-]+?)-<env>\s*$",
            section,
            re.M,
        )
    ]


@pytest.mark.regression
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_the_rename_instruction_is_the_synthesised_import_graph(synths, env):
    """PE v2 condition 5: destroy fargate, deploy compute, redeploy fargate.

    The cluster's ``Ref`` is an export; CloudFormation refuses to change an
    export another stack imports, and renaming the cluster changes it. So the
    stacks to destroy first are exactly the importers of that export -- which
    the plan got wrong once (it named migrations and analytics, and analytics
    imports nothing from compute). Asserted from the synth, then against the
    documented commands.
    """
    importers = cluster_export_importers(synths[env])
    assert importers == {"experimentation-fargate"}, importers

    section = _doc_section("Moving an environment deployed before the rename")
    destroyed = _commands(section, "destroy")
    assert set(destroyed) == importers, (destroyed, importers)
    # --exclusively: without it the CLI also destroys the stacks that DEPEND
    # on fargate (the migrations stack), whose old template retains its log
    # group.
    assert re.search(
        r"^cdk destroy --exclusively experimentation-fargate-<env>$", section, re.M
    ), (
        "the fargate destroy must be --exclusively: the CDK CLI otherwise also "
        "destroys experimentation-migrations-<env>, which depends on it"
    )
    deployed = _commands(section, "deploy")
    assert deployed == ["experimentation-compute", "experimentation-fargate"], deployed

    # Nothing imports from fargate, so destroying it alone is allowed.
    fargate = f"experimentation-fargate-{env}"
    exports = _exports(synths[env])
    for name, importers_of in import_graph(synths[env]).items():
        if exports.get(name) == fargate:
            assert not importers_of, (name, importers_of)


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_the_full_teardown_order_respects_imports_and_dependencies(synths, env):
    """Importers and dependants go first: monitoring and glue-etl before analytics."""
    synth = synths[env]
    order = _commands(_doc_section("Tearing an environment down"), "destroy")
    present = {synth.short(s) for s in synth.templates}
    assert set(order) == present | (
        set()
        if MODULES_PRESENT
        else {
            "experimentation-analytics",
            "experimentation-glue-etl",
            "experimentation-dynamodb-counters",
        }
    ), order
    position = {stack: i for i, stack in enumerate(order)}
    exports = _exports(synth)
    for name, importers in import_graph(synth).items():
        exporter = synth.short(exports[name])
        for importer in importers:
            assert position[synth.short(importer)] < position[exporter], (
                f"{importer} imports {name} from {exporter} and must be "
                "destroyed first"
            )
    for stack, dependencies in synth.dependencies.items():
        for dependency in dependencies:
            assert position[synth.short(stack)] < position[synth.short(dependency)], (
                f"{stack} depends on {dependency} and must be destroyed first"
            )
    if MODULES_PRESENT:
        assert position["experimentation-monitoring"] < position["experimentation-analytics"]
        assert position["experimentation-glue-etl"] < position["experimentation-analytics"]
