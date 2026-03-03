"""
CDK Construct for the Split URL CloudFront Distribution — EP-036 Batch 2.

Creates a CloudFront distribution with a Lambda@Edge viewer-request handler
that performs deterministic A/B URL assignment at the CDN edge. Caching is
deliberately disabled so that every request is evaluated by the router function.
"""
from aws_cdk import (
    Duration,
    CfnOutput,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_lambda as lambda_,
)
from constructs import Construct


class SplitUrlDistribution(Construct):
    """
    CloudFront distribution wired to a Lambda@Edge viewer-request function
    for split URL A/B redirect routing.

    The distribution is deliberately configured with:
    - No caching (TTL = 0): every request must be evaluated by the router so
      that individual users consistently receive their assigned variant across
      their session via the cookie set by the Lambda@Edge function.
    - HTTPS-only viewer protocol policy: all HTTP requests are redirected to
      HTTPS to protect the assignment cookie.
    - ALLOW_ALL origin request policy so the router function receives all
      headers including cookies.

    Attributes:
        distribution: The created CloudFront Distribution.
        domain_name: The CloudFront domain name (e.g. ``d1234.cloudfront.net``).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        router_function: lambda_.IFunction,
        origin_domain: str,
        **kwargs,
    ) -> None:
        """
        Initialise a SplitUrlDistribution construct.

        Args:
            scope: CDK construct scope.
            construct_id: Logical identifier for this construct.
            router_function: Lambda@Edge function (``lambda_.IFunction``) that
                handles viewer-request events and redirects users to the
                correct URL variant.
            origin_domain: Fully qualified domain name for the CloudFront
                origin (e.g. ``myapp.example.com``).
            **kwargs: Additional keyword arguments forwarded to the parent
                ``Construct`` constructor.
        """
        super().__init__(scope, construct_id, **kwargs)

        # Cache policy: no caching — TTL = 0 so every request hits the
        # viewer-request Lambda.  This is intentional for A/B routing.
        no_cache_policy = cloudfront.CachePolicy(
            self,
            "NoCachePolicy",
            cache_policy_name=f"{construct_id}-no-cache",
            comment="Disable caching for split URL A/B routing",
            default_ttl=Duration.seconds(0),
            min_ttl=Duration.seconds(0),
            max_ttl=Duration.seconds(0),
        )

        # Lambda@Edge association on the viewer-request event phase so the
        # router function can inspect/modify the request before any cache
        # lookup (or origin request).
        edge_lambda = cloudfront.EdgeLambda(
            function_version=router_function.current_version,
            event_type=cloudfront.LambdaEdgeEventType.VIEWER_REQUEST,
            include_body=False,
        )

        # Origin — the real application behind CloudFront.
        http_origin = origins.HttpOrigin(origin_domain)

        # Default behaviour configuration.
        default_behavior = cloudfront.BehaviorOptions(
            origin=http_origin,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=no_cache_policy,
            edge_lambdas=[edge_lambda],
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
        )

        # Create the CloudFront distribution.
        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=default_behavior,
            comment=f"{construct_id} — Split URL A/B distribution",
        )

        # Convenience property.
        self.domain_name: str = self.distribution.distribution_domain_name

        # CloudFormation output so the domain can be referenced from other
        # stacks or consumed by CI/CD pipelines.
        CfnOutput(
            self,
            "DistributionDomainName",
            value=self.domain_name,
            description="CloudFront domain name for the split URL distribution",
            export_name=f"{construct_id}-domain-name",
        )
