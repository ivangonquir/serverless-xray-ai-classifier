from aws_cdk import (
    Stack,
    Duration,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_lambda as lambda_,
    CfnOutput,
)
from constructs import Construct

from stacks.lambda_stack import LambdaStack
from stacks.storage_stack import StorageStack


class ApiStack(Stack):
    """
    REST API Gateway that exposes all LUNA backend endpoints.

    Every route except /auth/login and /auth/seed is protected by a custom
    Lambda Authorizer that validates session tokens (FR-1.1).

    Rate limiting is enforced via a Usage Plan (FR-1.3):
      • Burst: 100 requests/s
      • Steady-state: 50 requests/s

    CORS is enabled on every resource so the React frontend (served from a
    different CloudFront domain) can call the API.
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

        # ── Lambda Authorizer function ────────────────────────────────────
        # Defined here (not in LambdaStack) to avoid a circular cross-stack
        # reference: TokenAuthorizer adds a permission that references the
        # REST API ARN, which would point back from LambdaStack → ApiStack.
        authorizer_fn = lambda_.Function(
            self, "LunaAuthorizer",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/authorizer"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(5),
            memory_size=128,
            environment={
                "SESSIONS_TABLE": storage_stack.sessions_table.table_name,
                "AUDIT_LOG_TABLE": storage_stack.audit_log_table.table_name,
            },
        )
        storage_stack.sessions_table.grant_read_data(authorizer_fn)
        storage_stack.audit_log_table.grant_write_data(authorizer_fn)

        # ── REST API ─────────────────────────────────────────────────────
        api = apigw.RestApi(
            self, "LunaRestApi",
            rest_api_name="luna-api",
            description="LUNA Clinical Decision Support System — backend REST API",
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
                data_trace_enabled=False,  # Avoid logging PHI
            ),
        )

        # ── Token Authorizer ──────────────────────────────────────────────
        # Validates Bearer <sessionToken> on every protected route.
        # Results are NOT cached so every request is validated (no stale
        # sessions can slip through after logout).
        authorizer = apigw.TokenAuthorizer(
            self, "LunaTokenAuthorizer",
            handler=authorizer_fn,
            identity_source="method.request.header.Authorization",
            results_cache_ttl=Duration.seconds(0),
        )

        # Shorthand for a Lambda proxy integration
        def proxy(fn):
            return apigw.LambdaIntegration(fn, proxy=True)

        # Shorthand to add a method that requires the authorizer
        def add_auth_method(resource, http_method, fn):
            resource.add_method(
                http_method,
                proxy(fn),
                authorizer=authorizer,
                authorization_type=apigw.AuthorizationType.CUSTOM,
            )

        # ── /auth ─────────────────────────────────────────────────────────
        auth_resource = api.root.add_resource("auth")

        # POST /auth/login  — public (no auth required)
        auth_resource.add_resource("login").add_method(
            "POST", proxy(lambda_stack.auth_fn)
        )
        # POST /auth/logout — requires valid session
        add_auth_method(auth_resource.add_resource("logout"), "POST", lambda_stack.auth_fn)
        # POST /auth/seed   — creates initial test users (dev only, public)
        auth_resource.add_resource("seed").add_method(
            "POST", proxy(lambda_stack.auth_fn)
        )

        # ── /patients ─────────────────────────────────────────────────────
        patients_resource = api.root.add_resource("patients")

        # GET  /patients  — triage list (FR-UI 1.1)
        add_auth_method(patients_resource, "GET", lambda_stack.patient_fn)
        # POST /patients  — register patient
        add_auth_method(patients_resource, "POST", lambda_stack.patient_fn)

        patient_id_resource = patients_resource.add_resource("{patientId}")

        # GET /patients/{patientId}  — patient detail + latest result (FR-UI 2.1)
        add_auth_method(patient_id_resource, "GET", lambda_stack.patient_fn)

        # POST /patients/{patientId}/upload   — generate pre-signed DICOM URL
        upload_resource = patient_id_resource.add_resource("upload")
        add_auth_method(upload_resource, "POST", lambda_stack.upload_fn)

        # POST /patients/{patientId}/diagnose — trigger ML pipeline (FR-2.3)
        diagnose_resource = patient_id_resource.add_resource("diagnose")
        add_auth_method(diagnose_resource, "POST", lambda_stack.diagnostic_fn)

        # GET  /patients/{patientId}/results  — diagnostic history (FR-4.3)
        results_resource = patient_id_resource.add_resource("results")
        add_auth_method(results_resource, "GET", lambda_stack.diagnostic_fn)

        # GET  /patients/{patientId}/chat     — chat history (FR-5.x)
        chat_resource = patient_id_resource.add_resource("chat")
        add_auth_method(chat_resource, "GET", lambda_stack.assistant_fn)

        # ── /assistant ────────────────────────────────────────────────────
        assistant_resource = api.root.add_resource("assistant")

        # POST /assistant/query — NL query (patient-specific or population)
        query_resource = assistant_resource.add_resource("query")
        add_auth_method(query_resource, "POST", lambda_stack.assistant_fn)

        # ── Usage Plan (rate limiting — FR-1.3) ──────────────────────────
        plan = api.add_usage_plan(
            "LunaUsagePlan",
            name="luna-standard",
            throttle=apigw.ThrottleSettings(
                burst_limit=100,
                rate_limit=50,
            ),
        )
        plan.add_api_stage(stage=api.deployment_stage)

        # ── Outputs ───────────────────────────────────────────────────────
        CfnOutput(
            self, "ApiUrl",
            value=api.url,
            description="LUNA REST API base URL — set as NEXT_PUBLIC_API_URL in frontend .env",
        )
