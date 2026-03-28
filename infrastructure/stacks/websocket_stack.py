from aws_cdk import (
    Stack,
    aws_apigatewayv2 as apigwv2,
    CfnOutput,
)
from constructs import Construct


class WebSocketStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # WebSocket API — routes are wired to Lambdas in LambdaStack
        self.api = apigwv2.CfnApi(
            self,
            "XRayWebSocketApi",
            name="xray-websocket-api",
            protocol_type="WEBSOCKET",
            route_selection_expression="$request.body.action",
        )

        # Stage (auto-deploy)
        stage = apigwv2.CfnStage(
            self,
            "ProdStage",
            api_id=self.api.ref,
            stage_name="prod",
            auto_deploy=True,
        )

        # Output the WebSocket URL for the frontend .env
        CfnOutput(
            self,
            "WebSocketURL",
            value=f"wss://{self.api.ref}.execute-api.{self.region}.amazonaws.com/prod",
            description="WebSocket endpoint URL",
        )
