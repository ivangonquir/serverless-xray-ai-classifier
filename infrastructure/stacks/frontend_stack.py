from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    CfnOutput,
    Fn
)

from constructs import Construct


class FrontendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── Import API Gateway URL from ApiStack ────────────────────
        api_full_url = Fn.import_value("LunaApiUrl")
        api_domain = Fn.select(2, Fn.split("/", api_full_url))
        api_stage = Fn.select(3, Fn.split("/", api_full_url))
        api_origin = origins.HttpOrigin(api_domain, origin_path=f"/{api_stage}")
        # S3 bucket for static Next.js export
        frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # OAC — allows CloudFront to read from the private bucket
        oac = cloudfront.S3OriginAccessControl(self, "OAC")


        # ── Cache policy: do not cache API responses ───────────────
        api_no_cache = cloudfront.CachePolicy(
            self,
            "ApiNoCachePolicy",
            default_ttl=Duration.seconds(0),
            min_ttl=Duration.seconds(0),
            max_ttl=Duration.seconds(0),
            comment="No caching for API responses",
        )

        # ── Origin request policy: forward the Origin header ───────
        # Without this, CloudFront drops the browser's Origin header and
        # the Lambda function never sees it, causing CORS failures.
        cors_forward_policy = cloudfront.OriginRequestPolicy(
            self,
            "CorsForwardPolicy",
            header_behavior=cloudfront.OriginRequestHeaderBehavior.allow_list(
                "Origin"
            ),
            comment="Forward Origin header to Lambda for CORS matching",
        )

        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    frontend_bucket,
                    origin_access_control=oac,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            additional_behaviors={
                # Route /auth/* requests to API Gateway with CORS headers
                "/auth/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=api_no_cache,
                    origin_request_policy=cors_forward_policy,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,  # POST, OPTIONS, etc.
                ),
            },
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                )
            ],
        )

        # Deploy the built Next.js static export to S3
        s3deploy.BucketDeployment(
            self,
            "DeployFrontend",
            sources=[s3deploy.Source.asset("../frontend/out")],
            destination_bucket=frontend_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        CfnOutput(self, "FrontendURL",
                  value=f"https://{distribution.distribution_domain_name}",
                  export_name="LunaFrontendURL"
                  )
        CfnOutput(self, "FrontendBucketName", value=frontend_bucket.bucket_name)
