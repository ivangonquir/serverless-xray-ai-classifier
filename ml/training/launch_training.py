"""
Run this script locally to launch a SageMaker Training Job.
"""

import sagemaker
from sagemaker.pytorch import PyTorch

session = sagemaker.Session()
role = "arn:aws:iam::113627992593:role/SageMakerExecutionRole"
bucket = "xray-classifier-113627992593"

s3_train = f"s3://{bucket}/datasets/chest_xray/train"
s3_val   = f"s3://{bucket}/datasets/chest_xray/val"

estimator = PyTorch(
    entry_point="train.py",
    source_dir=".",
    role=role,
    instance_type="ml.m5.xlarge",  # Switch to ml.g4dn.xlarge for GPU
    instance_count=1,
    framework_version="2.2",
    py_version="py311",
    hyperparameters={
        "epochs": 15,
        "batch-size": 32,
        "learning-rate": 1e-4,
        "num-classes": 2,
    },
    output_path=f"s3://{bucket}/models/xray-classifier/",
    base_job_name="xray-resnet-classifier",
    sagemaker_session=session,
)

estimator.fit({"train": s3_train, "val": s3_val})

print("Training job name:", estimator.latest_training_job.name)
print("Model artifact:", estimator.model_data)
