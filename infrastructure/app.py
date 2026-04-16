#!/usr/bin/env python3
import os
import aws_cdk as cdk

from stacks.storage_stack import StorageStack
from stacks.websocket_stack import WebSocketStack
from stacks.sagemaker_stack import SageMakerStack
from stacks.lambda_stack import LambdaStack
from stacks.api_stack import ApiStack
from stacks.frontend_stack import FrontendStack

app = cdk.App()

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT") or app.node.try_get_context("account"),
    region=os.getenv("CDK_DEFAULT_REGION") or app.node.try_get_context("region") or "us-east-1",
)

# ── Layer 1: Storage ─────────────────────────────────────────────────────
# S3, SQS, all DynamoDB tables, OpenSearch RAG domain
storage = StorageStack(app, "LunaStorageStack", env=env)

# ── Layer 2: WebSocket API ───────────────────────────────────────────────
# Real-time channel for pushing async inference results to the browser
websocket = WebSocketStack(app, "LunaWebSocketStack", env=env)

# ── Layer 3: SageMaker Endpoint ──────────────────────────────────────────
# Deploy the LUNA classifier once the ML team provides a model artifact.
# Trigger with:
#   cdk deploy LunaSageMakerStack \
#       --context model_artifact_uri=s3://luna-dicom-<account>/models/model.tar.gz
sagemaker = SageMakerStack(app, "LunaSageMakerStack", storage_stack=storage, env=env)

# ── Layer 4: Lambda Functions ────────────────────────────────────────────
# All eight Lambda handlers + WebSocket route bindings
lambdas = LambdaStack(
    app, "LunaLambdaStack",
    storage_stack=storage,
    websocket_stack=websocket,
    sagemaker_stack=sagemaker,
    env=env,
)

# ── Layer 5: REST API ────────────────────────────────────────────────────
# API Gateway routes, Lambda authorizer, CORS, rate limiting
api = ApiStack(app, "LunaApiStack", lambda_stack=lambdas, env=env)

# ── Layer 6: Frontend Hosting ────────────────────────────────────────────
# S3 + CloudFront for the React SPA (owned by Team 3)
frontend = FrontendStack(app, "LunaFrontendStack", env=env)

app.synth()
