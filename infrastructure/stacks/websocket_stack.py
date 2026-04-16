from aws_cdk import (
    Stack,
    aws_apigatewayv2 as apigwv2,
    CfnOutput,
)
from constructs import Construct


class WebSocketStack(Stack):
    """
    Provisions the API Gateway WebSocket API used to push async ML results
    back to the clinician's browser in real time (FR-6.2).

    Routes ($connect / $disconnect) are wired to the connection_manager
    Lambda in LambdaStack so that active connection IDs can be tracked.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # WebSocket API — route selection based on the "action" field in the
        # JSON payload (compatible with the existing frontend hook pattern)
        self.api = apigwv2.CfnApi(
            self, "LunaWebSocketApi",
            name="luna-websocket-api",
            protocol_type="WEBSOCKET",
            route_selection_expression="$request.body.action",
        )

        # Auto-deploy stage so CDK changes are immediately live
        apigwv2.CfnStage(
            self, "ProdStage",
            api_id=self.api.ref,
            stage_name="prod",
            auto_deploy=True,
        )

        # Expose the full WSS URL so LambdaStack can build the management
        # endpoint and the frontend can read it from CDK outputs
        self.websocket_url = (
            f"wss://{self.api.ref}.execute-api.{self.region}.amazonaws.com/prod"
        )
        self.websocket_management_endpoint = (
            f"https://{self.api.ref}.execute-api.{self.region}.amazonaws.com/prod"
        )

        CfnOutput(
            self, "WebSocketURL",
            value=self.websocket_url,
            description="WebSocket endpoint — set as NEXT_PUBLIC_WS_URL in frontend .env",
        )
