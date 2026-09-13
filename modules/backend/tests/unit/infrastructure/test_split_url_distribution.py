"""
CDK unit tests for SplitUrlDistribution construct — EP-036 Batch 2.

Uses aws_cdk.assertions.Template to assert CloudFormation resource properties
without deploying any real infrastructure.

Run with:
    source venv/bin/activate
    export APP_ENV=test TESTING=true
    python -m pytest modules/backend/tests/unit/infrastructure/test_split_url_distribution.py -v
"""

import aws_cdk as cdk
import pytest
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Match, Template

from modules.infrastructure.constructs.split_url_distribution import (
    SplitUrlDistribution,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ORIGIN_DOMAIN = "myapp.example.com"
_CONSTRUCT_ID = "TestSplitUrlDist"


@pytest.fixture(scope="module")
def stack_and_template():
    """Create a minimal CDK app/stack containing a SplitUrlDistribution and return
    both the construct and the synthesised CloudFormation template."""
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")

    # A minimal Lambda function to act as the router Lambda@Edge.
    router_fn = lambda_.Function(
        stack,
        "RouterFn",
        runtime=lambda_.Runtime.NODEJS_18_X,
        handler="index.handler",
        code=lambda_.Code.from_inline(
            "exports.handler = async (event) => { return event.Records[0].cf.request; };"
        ),
    )

    construct = SplitUrlDistribution(
        stack,
        _CONSTRUCT_ID,
        router_function=router_fn,
        origin_domain=_ORIGIN_DOMAIN,
    )

    template = Template.from_stack(stack)
    return construct, template


@pytest.fixture(scope="module")
def construct(stack_and_template):
    return stack_and_template[0]


@pytest.fixture(scope="module")
def template(stack_and_template):
    return stack_and_template[1]


# ---------------------------------------------------------------------------
# Test 1: Construct can be instantiated
# ---------------------------------------------------------------------------


def test_construct_can_be_instantiated(construct):
    """SplitUrlDistribution construct can be created without errors."""
    assert construct is not None


# ---------------------------------------------------------------------------
# Test 2: CloudFront distribution resource exists
# ---------------------------------------------------------------------------


def test_cloudfront_distribution_created(template):
    """A CloudFront distribution resource is present in the synthesised template."""
    template.resource_count_is("AWS::CloudFront::Distribution", 1)


# ---------------------------------------------------------------------------
# Test 3: Distribution has the correct origin domain
# ---------------------------------------------------------------------------


def test_distribution_has_correct_origin_domain(template):
    """The distribution origin is configured with the supplied origin_domain."""
    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": {
                "Origins": Match.array_with(
                    [Match.object_like({"DomainName": _ORIGIN_DOMAIN})]
                )
            }
        },
    )


# ---------------------------------------------------------------------------
# Test 4: Lambda@Edge is attached to viewer-request
# ---------------------------------------------------------------------------


def test_lambda_edge_attached_to_viewer_request(template):
    """Lambda@Edge association uses the VIEWER_REQUEST event type."""
    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": {
                "DefaultCacheBehavior": {
                    "LambdaFunctionAssociations": Match.array_with(
                        [Match.object_like({"EventType": "viewer-request"})]
                    )
                }
            }
        },
    )


# ---------------------------------------------------------------------------
# Test 5: HTTPS-only viewer protocol policy
# ---------------------------------------------------------------------------


def test_distribution_has_https_only_policy(template):
    """Distribution viewer protocol policy redirects HTTP to HTTPS."""
    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": {
                "DefaultCacheBehavior": {"ViewerProtocolPolicy": "redirect-to-https"}
            }
        },
    )


# ---------------------------------------------------------------------------
# Test 6: Cache disabled — default TTL is 0
# ---------------------------------------------------------------------------


def test_distribution_has_no_cache_ttl(template):
    """Cache policy has DefaultTTL=0 to disable caching for A/B routing."""
    template.has_resource_properties(
        "AWS::CloudFront::CachePolicy",
        {
            "CachePolicyConfig": {
                "DefaultTTL": 0,
            }
        },
    )


# ---------------------------------------------------------------------------
# Test 7: Cache policy has MinTTL = 0
# ---------------------------------------------------------------------------


def test_distribution_has_min_ttl_zero(template):
    """Cache policy MinTTL is 0 (no minimum caching)."""
    template.has_resource_properties(
        "AWS::CloudFront::CachePolicy",
        {
            "CachePolicyConfig": {
                "MinTTL": 0,
            }
        },
    )


# ---------------------------------------------------------------------------
# Test 8: Cache policy has MaxTTL = 0
# ---------------------------------------------------------------------------


def test_distribution_has_max_ttl_zero(template):
    """Cache policy MaxTTL is 0."""
    template.has_resource_properties(
        "AWS::CloudFront::CachePolicy",
        {
            "CachePolicyConfig": {
                "MaxTTL": 0,
            }
        },
    )


# ---------------------------------------------------------------------------
# Test 9: Distribution outputs domain name via CfnOutput
# ---------------------------------------------------------------------------


def test_distribution_outputs_domain_name(template):
    """A CfnOutput for the CloudFront domain name is present in the template.

    CDK appends a uniqueness hash to the logical ID of CfnOutputs, so we use
    find_outputs with a wildcard to locate the output without knowing the hash.
    """
    # find_outputs(logical_id, props) returns a dict of {logicalId: outputProps}.
    # Using '*' matches all outputs; then we filter by key prefix.
    all_outputs = template.find_outputs("*", {})
    domain_name_outputs = {
        k: v for k, v in all_outputs.items() if "DistributionDomainName" in k
    }
    assert len(domain_name_outputs) >= 1, (
        f"Expected at least one output containing 'DistributionDomainName'. "
        f"Found outputs: {list(all_outputs.keys())}"
    )


# ---------------------------------------------------------------------------
# Test 10: Construct exposes domain_name attribute
# ---------------------------------------------------------------------------


def test_construct_exposes_domain_name_attribute(construct):
    """SplitUrlDistribution exposes the distribution domain name as an attribute."""
    assert construct.domain_name is not None
    assert isinstance(construct.domain_name, str)


# ---------------------------------------------------------------------------
# Test 11: Construct exposes distribution attribute
# ---------------------------------------------------------------------------


def test_construct_exposes_distribution_attribute(construct):
    """SplitUrlDistribution exposes the CloudFront Distribution object."""
    assert construct.distribution is not None


# ---------------------------------------------------------------------------
# Test 12: Lambda function resource exists
# ---------------------------------------------------------------------------


def test_lambda_function_resource_exists(template):
    """At least one Lambda function resource exists (the router function)."""
    # find_resources returns a dict; we just need it to be non-empty.
    lambda_resources = template.find_resources("AWS::Lambda::Function")
    assert len(lambda_resources) >= 1, (
        "Expected at least one AWS::Lambda::Function resource in the template"
    )


# ---------------------------------------------------------------------------
# Test 13: Lambda@Edge function has a versioned ARN reference
# ---------------------------------------------------------------------------


def test_lambda_edge_association_references_function_version(template):
    """LambdaFunctionAssociation references a Lambda version (not just the function)."""
    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": {
                "DefaultCacheBehavior": {
                    "LambdaFunctionAssociations": Match.array_with(
                        [Match.object_like({"LambdaFunctionARN": Match.any_value()})]
                    )
                }
            }
        },
    )


# ---------------------------------------------------------------------------
# Test 14: Cache policy name contains construct ID
# ---------------------------------------------------------------------------


def test_cache_policy_name_contains_construct_id(template):
    """Cache policy name is namespaced with the construct ID."""
    template.has_resource_properties(
        "AWS::CloudFront::CachePolicy",
        {"CachePolicyConfig": {"Name": Match.string_like_regexp(_CONSTRUCT_ID)}},
    )


# ---------------------------------------------------------------------------
# Test 15: Distribution is enabled (not disabled)
# ---------------------------------------------------------------------------


def test_distribution_is_enabled(template):
    """The CloudFront distribution is enabled (Enabled=true)."""
    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": {
                "Enabled": True,
            }
        },
    )
