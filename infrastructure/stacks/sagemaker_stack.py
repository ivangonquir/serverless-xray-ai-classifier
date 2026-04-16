from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_sagemaker as sagemaker,
    aws_ssm as ssm,
    CfnOutput,
)
from constructs import Construct

from stacks.storage_stack import StorageStack


# PyTorch 2.2 / Python 3.11 Deep Learning Container for inference
# (same framework version used by the ML team in ml/inference/inference.py)
PYTORCH_INFERENCE_IMAGE = (
    "763104351884.dkr.ecr.{region}.amazonaws.com/"
    "pytorch-inference:2.2.0-cpu-py311-ubuntu20.04-sagemaker"
)


class SageMakerStack(Stack):
    """
    Deploys the LUNA classifier as a SageMaker real-time endpoint.

    The ML team trains the model using ml/training/train.py and uploads
    the artifact to S3.  This stack packages it and creates a persistent
    endpoint that the inference_worker Lambda can invoke.

    Deployment is conditional: pass the S3 URI of the model artifact via
    CDK context to activate endpoint creation:

        cdk deploy LunaSageMakerStack \\
            --context model_artifact_uri=s3://luna-dicom-<account>/models/model.tar.gz
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        storage_stack: StorageStack,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # ── IAM role for SageMaker ───────────────────────────────────────
        self.sagemaker_role = iam.Role(
            self, "LunaSageMakerRole",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSageMakerFullAccess"
                ),
            ],
        )
        # Allow SageMaker to read the trained model artifact from S3
        storage_stack.dicom_bucket.grant_read(self.sagemaker_role)

        # ── Conditional endpoint deployment ─────────────────────────────
        model_artifact_uri = self.node.try_get_context("model_artifact_uri")

        if model_artifact_uri:
            region = self.region
            image_uri = PYTORCH_INFERENCE_IMAGE.format(region=region)

            # SageMaker Model — points at the trained artifact produced by
            # ml/training/train.py (model_best.pth packed as model.tar.gz)
            cfn_model = sagemaker.CfnModel(
                self, "LunaClassifierModel",
                model_name="luna-classifier",
                execution_role_arn=self.sagemaker_role.role_arn,
                primary_container=sagemaker.CfnModel.ContainerDefinitionProperty(
                    image=image_uri,
                    model_data_url=model_artifact_uri,
                    environment={
                        # SageMaker will call inference.py as the entry point
                        "SAGEMAKER_PROGRAM": "inference.py",
                        "SAGEMAKER_SUBMIT_DIRECTORY": "/opt/ml/code",
                    },
                ),
            )

            # Endpoint configuration — serverless to minimise idle cost
            endpoint_config = sagemaker.CfnEndpointConfig(
                self, "LunaEndpointConfig",
                endpoint_config_name="luna-classifier-config",
                production_variants=[
                    sagemaker.CfnEndpointConfig.ProductionVariantProperty(
                        variant_name="AllTraffic",
                        model_name=cfn_model.model_name,
                        serverless_config=sagemaker.CfnEndpointConfig.ServerlessConfigProperty(
                            memory_size_in_mb=3072,
                            max_concurrency=5,
                        ),
                    )
                ],
            )
            endpoint_config.add_dependency(cfn_model)

            cfn_endpoint = sagemaker.CfnEndpoint(
                self, "LunaClassifierEndpoint",
                endpoint_name="luna-classifier",
                endpoint_config_name=endpoint_config.endpoint_config_name,
            )
            cfn_endpoint.add_dependency(endpoint_config)

            self.endpoint_name = cfn_endpoint.endpoint_name

            CfnOutput(
                self, "SageMakerEndpointName",
                value=self.endpoint_name,
                description="LUNA classifier SageMaker endpoint name",
            )
        else:
            # Model not yet available — endpoint name must be set manually
            # once the ML team provides the artifact.
            self.endpoint_name = "luna-classifier"
            CfnOutput(
                self, "SageMakerEndpointName",
                value=self.endpoint_name,
                description=(
                    "Placeholder — deploy with --context model_artifact_uri=<s3-uri> "
                    "once the ML team provides the trained model artifact"
                ),
            )

        # ── SSM: share endpoint name with Lambda ─────────────────────────
        # The inference_worker Lambda reads this parameter at deploy time
        ssm.StringParameter(
            self, "LunaEndpointNameParam",
            parameter_name="/luna/sagemaker/endpoint-name",
            string_value=self.endpoint_name,
            description="LUNA SageMaker classifier endpoint name",
        )
