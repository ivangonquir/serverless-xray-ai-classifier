from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_es,
    aws_iam as iam,
    aws_apigatewayv2 as apigwv2,
    aws_ssm as ssm,
    CfnOutput,
)
from constructs import Construct

from stacks.storage_stack import StorageStack
from stacks.websocket_stack import WebSocketStack
from stacks.sagemaker_stack import SageMakerStack


class LambdaStack(Stack):
    """
    Creates every Lambda function in the LUNA backend and wires up their
    permissions, environment variables, event sources, and WebSocket routes.

    Public properties (consumed by ApiStack to build REST routes):
        authorizer_fn, auth_fn, patient_fn, upload_fn,
        diagnostic_fn, assistant_fn
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        storage_stack: StorageStack,
        websocket_stack: WebSocketStack,
        sagemaker_stack: SageMakerStack,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        ws_api = websocket_stack.api
        ws_mgmt = websocket_stack.websocket_management_endpoint

        # ── 1. Auth Handler ──────────────────────────────────────────────
        # POST /auth/login  — validates credentials, issues session token
        # POST /auth/logout — invalidates session
        # POST /auth/seed   — creates initial test users (dev only)
        self.auth_fn = lambda_.Function(
            self, "LunaAuthHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/auth_handler"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={
                "USERS_TABLE": storage_stack.users_table.table_name,
                "SESSIONS_TABLE": storage_stack.sessions_table.table_name,
                "AUDIT_LOG_TABLE": storage_stack.audit_log_table.table_name,
                # HMAC key for password hashing — override in SSM/Secrets Manager
                # for production deployments
                "PASSWORD_SECRET": "luna-dev-secret-change-in-production",
            },
        )
        storage_stack.users_table.grant_read_write_data(self.auth_fn)
        storage_stack.sessions_table.grant_read_write_data(self.auth_fn)
        storage_stack.audit_log_table.grant_write_data(self.auth_fn)

        # ── 3. Patient Handler ───────────────────────────────────────────
        # GET  /patients        — triage list sorted by LUNA Risk Score
        # GET  /patients/{id}   — patient detail + latest diagnostic result
        # POST /patients        — register a new patient
        self.patient_fn = lambda_.Function(
            self, "LunaPatientHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/patient_handler"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={
                "PATIENTS_TABLE": storage_stack.patients_table.table_name,
                "DIAGNOSTIC_RESULTS_TABLE": storage_stack.diagnostic_results_table.table_name,
                "AUDIT_LOG_TABLE": storage_stack.audit_log_table.table_name,
            },
        )
        storage_stack.patients_table.grant_read_write_data(self.patient_fn)
        storage_stack.diagnostic_results_table.grant_read_data(self.patient_fn)
        storage_stack.audit_log_table.grant_write_data(self.patient_fn)

        # ── 4. Upload Handler ────────────────────────────────────────────
        # POST /patients/{id}/upload
        # Generates a short-lived pre-signed S3 PUT URL so the browser
        # uploads directly to S3 without going through API Gateway (FR-3.1)
        self.upload_fn = lambda_.Function(
            self, "LunaUploadHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/upload_handler"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(10),
            memory_size=128,
            environment={
                "DICOM_BUCKET": storage_stack.dicom_bucket.bucket_name,
                "PATIENTS_TABLE": storage_stack.patients_table.table_name,
                "AUDIT_LOG_TABLE": storage_stack.audit_log_table.table_name,
            },
        )
        storage_stack.dicom_bucket.grant_put(self.upload_fn)
        storage_stack.patients_table.grant_read_data(self.upload_fn)
        storage_stack.audit_log_table.grant_write_data(self.upload_fn)

        # ── 5. Diagnostic Handler ────────────────────────────────────────
        # POST /patients/{id}/diagnose   — validates input, enqueues job (FR-2.1-2.3)
        # GET  /patients/{id}/results    — retrieves all results for a patient
        self.diagnostic_fn = lambda_.Function(
            self, "LunaDiagnosticHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/diagnostic_handler"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(15),
            memory_size=256,
            environment={
                "PATIENTS_TABLE": storage_stack.patients_table.table_name,
                "DIAGNOSTIC_RESULTS_TABLE": storage_stack.diagnostic_results_table.table_name,
                "DIAGNOSTIC_QUEUE_URL": storage_stack.diagnostic_queue.queue_url,
                "CONNECTIONS_TABLE": storage_stack.connections_table.table_name,
                "AUDIT_LOG_TABLE": storage_stack.audit_log_table.table_name,
            },
        )
        storage_stack.patients_table.grant_read_write_data(self.diagnostic_fn)
        storage_stack.diagnostic_results_table.grant_read_write_data(self.diagnostic_fn)
        storage_stack.diagnostic_queue.grant_send_messages(self.diagnostic_fn)
        storage_stack.audit_log_table.grant_write_data(self.diagnostic_fn)

        # ── 6. Inference Worker ──────────────────────────────────────────
        # SQS trigger → download DICOM → invoke SageMaker → multimodal fusion
        # → write result → push to WebSocket (FR-4.1, FR-4.2, FR-6.2)
        inference_fn = lambda_.Function(
            self, "LunaInferenceWorker",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/inference_worker"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(360),  # 300s poll window + 60s headroom
            memory_size=1024,
            environment={
                "PATIENTS_TABLE": storage_stack.patients_table.table_name,
                "DIAGNOSTIC_RESULTS_TABLE": storage_stack.diagnostic_results_table.table_name,
                "DICOM_BUCKET": storage_stack.dicom_bucket.bucket_name,
                "SAGEMAKER_ENDPOINT": "chexone-async",  # ML team deploys this endpoint independently
                "WEBSOCKET_ENDPOINT": ws_mgmt,
            },
        )
        storage_stack.patients_table.grant_read_data(inference_fn)
        storage_stack.diagnostic_results_table.grant_read_write_data(inference_fn)
        storage_stack.dicom_bucket.grant_read(inference_fn)
        storage_stack.connections_table.grant_read_data(inference_fn)
        storage_stack.diagnostic_queue.grant_consume_messages(inference_fn)
        # Call the CheXOne async classifier endpoint
        inference_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sagemaker:InvokeEndpointAsync"],
                resources=["*"],
            )
        )
        # Push results back to connected browsers via WebSocket
        inference_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["execute-api:ManageConnections"],
                resources=[
                    f"arn:aws:execute-api:{self.region}:{self.account}:{ws_api.ref}/prod/POST/@connections/*"
                ],
            )
        )
        # SQS event source — process one job at a time
        inference_fn.add_event_source(
            lambda_es.SqsEventSource(
                storage_stack.diagnostic_queue,
                batch_size=1,
            )
        )

        # ── 7. Assistant Handler ─────────────────────────────────────────
        # POST /assistant/query       — RAG retrieval + LLM answer + citations
        # GET  /patients/{id}/chat    — chat history for a patient
        self.assistant_fn = lambda_.Function(
            self, "LunaAssistantHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/assistant_handler"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(30),
            memory_size=1024,
            environment={
                "PATIENTS_TABLE": storage_stack.patients_table.table_name,
                "DIAGNOSTIC_RESULTS_TABLE": storage_stack.diagnostic_results_table.table_name,
                "CHAT_HISTORY_TABLE": storage_stack.chat_history_table.table_name,
                "AUDIT_LOG_TABLE": storage_stack.audit_log_table.table_name,
                "OPENSEARCH_ENDPOINT": storage_stack.opensearch_domain.domain_endpoint,
                "OPENSEARCH_INDEX": "luna-docs",
                # Set to a SageMaker endpoint name to use the ML team's LLM;
                # leave empty to fall back to Amazon Bedrock Claude
                "LLM_SAGEMAKER_ENDPOINT": "",
                "BEDROCK_MODEL_ID": "anthropic.claude-haiku-4-5",
            },
        )
        storage_stack.patients_table.grant_read_data(self.assistant_fn)
        storage_stack.diagnostic_results_table.grant_read_data(self.assistant_fn)
        storage_stack.chat_history_table.grant_read_write_data(self.assistant_fn)
        storage_stack.audit_log_table.grant_write_data(self.assistant_fn)
        storage_stack.opensearch_domain.grant_read_write(self.assistant_fn)
        # Bedrock access for the LLM fallback
        self.assistant_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=["*"],
            )
        )
        # Optional: invoke the ML team's LLM SageMaker endpoint
        self.assistant_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sagemaker:InvokeEndpoint"],
                resources=["*"],
            )
        )

        # ── 8. Connection Manager ────────────────────────────────────────
        # WebSocket $connect / $disconnect — maintains the connections table
        # so the inference_worker knows where to push results (FR-6.2)
        connection_fn = lambda_.Function(
            self, "LunaConnectionManager",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/connection_manager"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(10),
            memory_size=128,
            environment={
                "CONNECTIONS_TABLE": storage_stack.connections_table.table_name,
            },
        )
        storage_stack.connections_table.grant_read_write_data(connection_fn)

        # ── WebSocket Routes ─────────────────────────────────────────────
        self._add_websocket_route(ws_api, "$connect", connection_fn, "ConnectIntegration")
        self._add_websocket_route(ws_api, "$disconnect", connection_fn, "DisconnectIntegration")

        # ── Outputs ──────────────────────────────────────────────────────
        CfnOutput(self, "InferenceWorkerName", value=inference_fn.function_name)
        CfnOutput(self, "AssistantFunctionName", value=self.assistant_fn.function_name)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _add_websocket_route(
        self,
        api: apigwv2.CfnApi,
        route_key: str,
        fn: lambda_.Function,
        integration_id: str,
    ):
        """Registers a Lambda integration for a WebSocket route and grants
        API Gateway permission to invoke the function."""
        integration = apigwv2.CfnIntegration(
            self, integration_id,
            api_id=api.ref,
            integration_type="AWS_PROXY",
            integration_uri=(
                f"arn:aws:apigateway:{self.region}:lambda:path"
                f"/2015-03-31/functions/{fn.function_arn}/invocations"
            ),
        )
        apigwv2.CfnRoute(
            self, f"Route{integration_id}",
            api_id=api.ref,
            route_key=route_key,
            target=f"integrations/{integration.ref}",
        )
        fn.add_permission(
            f"InvokeBy{integration_id}",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:{api.ref}/*/*",
        )
