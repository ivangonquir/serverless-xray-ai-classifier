#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.storage_stack import StorageStack
from stacks.websocket_stack import WebSocketStack
from stacks.lambda_stack import LambdaStack
from stacks.frontend_stack import FrontendStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-east-1",
)

storage = StorageStack(app, "XRayStorageStack", env=env)
websocket = WebSocketStack(app, "XRayWebSocketStack", env=env)
lambdas = LambdaStack(
    app,
    "XRayLambdaStack",
    image_bucket=storage.image_bucket,
    connections_table=storage.connections_table,
    results_table=storage.results_table,
    queue=storage.queue,
    websocket_api=websocket.api,
    env=env,
)
frontend = FrontendStack(app, "XRayFrontendStack", env=env)

app.synth()
