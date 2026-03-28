"""
Deploy a SageMaker Serverless Endpoint from a trained model artifact.
Run this after launch_training.py completes.
"""

import boto3
import sagemaker
from sagemaker.pytorch import PyTorchModel
from sagemaker.serverless import ServerlessInferenceConfig

# ── Update this after training completes ──────────────────────────────────────
MODEL_ARTIFACT_S3 = "s3://xray-classifier-113627992593/models/xray-classifier/YOUR-JOB/output/model.tar.gz"
ENDPOINT_NAME = "xray-classifier-serverless"
REGION = "us-east-1"
SSM_PARAM = "/xray/sagemaker/endpoint-name"
# ─────────────────────────────────────────────────────────────────────────────

session = sagemaker.Session()
role = "arn:aws:iam::113627992593:role/SageMakerExecutionRole"

model = PyTorchModel(
    model_data=MODEL_ARTIFACT_S3,
    role=role,
    entry_point="inference.py",
    source_dir=".",
    framework_version="2.2",
    py_version="py311",
)

serverless_config = ServerlessInferenceConfig(
    memory_size_in_mb=3072,
    max_concurrency=5,
)

predictor = model.deploy(
    serverless_inference_config=serverless_config,
    endpoint_name=ENDPOINT_NAME,
)

print(f"Endpoint deployed: {ENDPOINT_NAME}")

ssm = boto3.client("ssm", region_name=REGION)
ssm.put_parameter(
    Name=SSM_PARAM,
    Value=ENDPOINT_NAME,
    Type="String",
    Overwrite=True,
)
print(f"Endpoint name saved to SSM: {SSM_PARAM}")
