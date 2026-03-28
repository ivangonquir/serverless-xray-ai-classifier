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
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct


class LambdaStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        image_bucket: s3.Bucket,
        connections_table: dynamodb.Table,
        results_table: dynamodb.Table,
        queue: sqs.Queue,
        websocket_api: apigwv2.CfnApi,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        sagemaker_endpoint_name = ssm.StringParameter.value_for_string_parameter(
            self, "/xray/sagemaker/endpoint-name"
        )

        # --- Shared Lambda role base ---
        base_role = iam.Role(
            self,
            "LambdaBaseRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # ── 1. Connection Manager Lambda ──────────────────────────────────────
        connection_fn = lambda_.Function(
            self,
            "ConnectionManager",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/connection_manager"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(10),
            environment={
                "CONNECTIONS_TABLE": connections_table.table_name,
            },
        )
        connections_table.grant_read_write_data(connection_fn)

        # ── 2. URL Generator Lambda ───────────────────────────────────────────
        url_generator_fn = lambda_.Function(
            self,
            "UrlGenerator",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/url_generator"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(10),
            environment={
                "IMAGE_BUCKET": image_bucket.bucket_name,
            },
        )
        image_bucket.grant_put(url_generator_fn)

        # ── 3. Inference Worker Lambda ────────────────────────────────────────
        inference_fn = lambda_.Function(
            self,
            "InferenceWorker",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_asset("../backend/lambdas/inference_worker"),
            handler="handler.lambda_handler",
            timeout=Duration.seconds(300),
            environment={
                "CONNECTIONS_TABLE": connections_table.table_name,
                "RESULTS_TABLE": results_table.table_name,
                "SAGEMAKER_ENDPOINT": sagemaker_endpoint_name,
                "WEBSOCKET_ENDPOINT": f"https://{websocket_api.ref}.execute-api.{self.region}.amazonaws.com/prod",
            },
        )
        connections_table.grant_read_data(inference_fn)
        results_table.grant_write_data(inference_fn)
        image_bucket.grant_read(inference_fn)
        queue.grant_consume_messages(inference_fn)

        # Trigger inference Lambda from SQS
        inference_fn.add_event_source(
            lambda_es.SqsEventSource(queue, batch_size=1)
        )

        # Allow inference Lambda to call SageMaker and send WebSocket messages
        inference_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sagemaker:InvokeEndpoint"],
                resources=["*"],
            )
        )
        inference_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["execute-api:ManageConnections"],
                resources=[
                    f"arn:aws:execute-api:{self.region}:{self.account}:{websocket_api.ref}/prod/POST/@connections/*"
                ],
            )
        )

        # ── WebSocket Routes ──────────────────────────────────────────────────
        self._add_websocket_route(
            websocket_api, "$connect", connection_fn, "ConnectIntegration"
        )
        self._add_websocket_route(
            websocket_api, "$disconnect", connection_fn, "DisconnectIntegration"
        )
        self._add_websocket_route(
            websocket_api, "getUploadUrl", url_generator_fn, "UrlGenIntegration"
        )

        CfnOutput(self, "InferenceFunctionName", value=inference_fn.function_name)

    def _add_websocket_route(self, api, route_key, fn, integration_id):
        integration = apigwv2.CfnIntegration(
            self,
            integration_id,
            api_id=api.ref,
            integration_type="AWS_PROXY",
            integration_uri=f"arn:aws:apigateway:{self.region}:lambda:path/2015-03-31/functions/{fn.function_arn}/invocations",
        )
        apigwv2.CfnRoute(
            self,
            f"Route{integration_id}",
            api_id=api.ref,
            route_key=route_key,
            target=f"integrations/{integration.ref}",
        )
        fn.add_permission(
            f"InvokeBy{integration_id}",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:{api.ref}/*/*",
        )
