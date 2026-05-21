from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_apigateway as apigw,
    aws_lambda as lambda_,
)
from constructs import Construct

from stacks.lambda_stack import LambdaStack
from stacks.storage_stack import StorageStack


class ApiStack(Stack):
    """
    REST API Gateway that exposes all LUNA backend endpoints.

    Every route except /auth/login is protected by a custom Lambda Authorizer
    that validates session tokens (FR-1.1). Lambda responses dynamically echo
    localhost and any https://*.cloudfront.net origin. API Gateway OPTIONS uses
    a broad preflight because REST API mock CORS cannot match dynamic subdomains.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        lambda_stack: LambdaStack,
        storage_stack: StorageStack,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        authorizer_fn = lambda_.Function(
            self,
            "LunaAuthorizer",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/authorizer"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(5),
            memory_size=128,
            environment={
                "SESSIONS_TABLE": storage_stack.sessions_table.table_name,
                "AUDIT_LOG_TABLE": storage_stack.audit_log_table.table_name,
                "SESSION_EXTEND_THRESHOLD": "3600",
                "AUDIT_RETENTION_SECONDS": "220752000",
            },
        )
        storage_stack.sessions_table.grant_read_write_data(authorizer_fn)
        storage_stack.audit_log_table.grant_write_data(authorizer_fn)

        api = apigw.RestApi(
            self,
            "LunaRestApi",
            rest_api_name="luna-api",
            description="LUNA Clinical Decision Support System - backend REST API",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "X-Amz-Date",
                    "X-Api-Key",
                ],
            ),
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_burst_limit=100,
                throttling_rate_limit=50,
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=False,
            ),
        )

        authorizer = apigw.TokenAuthorizer(
            self,
            "LunaTokenAuthorizer",
            handler=authorizer_fn,
            identity_source="method.request.header.Authorization",
            results_cache_ttl=Duration.seconds(0),
        )

        def proxy(fn):
            return apigw.LambdaIntegration(fn, proxy=True)

        def add_auth_method(resource, http_method, fn):
            resource.add_method(
                http_method,
                proxy(fn),
                authorizer=authorizer,
                authorization_type=apigw.AuthorizationType.CUSTOM,
            )

        auth_resource = api.root.add_resource("auth")
        auth_resource.add_resource("login").add_method("POST", proxy(lambda_stack.auth_fn))
        add_auth_method(auth_resource.add_resource("logout"), "POST", lambda_stack.auth_fn)
        add_auth_method(auth_resource.add_resource("seed"), "POST", lambda_stack.auth_fn)

        patients_resource = api.root.add_resource("patients")
        add_auth_method(patients_resource, "GET", lambda_stack.patient_fn)
        add_auth_method(patients_resource, "POST", lambda_stack.patient_fn)

        patient_id_resource = patients_resource.add_resource("{patientId}")
        add_auth_method(patient_id_resource, "GET", lambda_stack.patient_fn)
        add_auth_method(patient_id_resource.add_resource("upload"), "POST", lambda_stack.upload_fn)
        add_auth_method(patient_id_resource.add_resource("diagnose"), "POST", lambda_stack.diagnostic_fn)
        add_auth_method(patient_id_resource.add_resource("results"), "GET", lambda_stack.diagnostic_fn)
        add_auth_method(patient_id_resource.add_resource("chat"), "GET", lambda_stack.assistant_fn)

        assistant_resource = api.root.add_resource("assistant")
        add_auth_method(assistant_resource.add_resource("query"), "POST", lambda_stack.assistant_fn)

        plan = api.add_usage_plan(
            "LunaUsagePlan",
            name="luna-standard",
            throttle=apigw.ThrottleSettings(
                burst_limit=100,
                rate_limit=50,
            ),
        )
        plan.add_api_stage(stage=api.deployment_stage)

        CfnOutput(
            self,
            "ApiUrl",
            value=api.url,
            export_name="LunaApiUrl",
            description="LUNA REST API base URL - set as NEXT_PUBLIC_API_URL in frontend .env",
        )
