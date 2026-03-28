"""
Inference Worker Lambda.

Triggered by SQS (which is triggered by S3 PUT events).

Flow:
  1. Parse SQS message → extract S3 bucket/key
  2. Read job metadata (jobId, connectionId) from S3 object metadata
  3. Download image from S3
  4. Invoke SageMaker Serverless Endpoint → get prediction
  5. Write result to DynamoDB (results table)
  6. Push result to frontend via WebSocket (API Gateway Management API)
"""

import json
import os
import uuid

import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
sagemaker_runtime = boto3.client("sagemaker-runtime")
dynamodb = boto3.resource("dynamodb")
apigw = boto3.client(
    "apigatewaymanagementapi",
    endpoint_url=os.environ["WEBSOCKET_ENDPOINT"],
)

RESULTS_TABLE = dynamodb.Table(os.environ["RESULTS_TABLE"])
CONNECTIONS_TABLE = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])
ENDPOINT_NAME = os.environ["SAGEMAKER_ENDPOINT"]


def lambda_handler(event, context):
    for record in event["Records"]:
        _process_record(record)


def _process_record(record):
    s3_event = json.loads(record["body"])

    for s3_record in s3_event.get("Records", []):
        bucket = s3_record["s3"]["bucket"]["name"]
        key = s3_record["s3"]["object"]["key"]

        head = s3.head_object(Bucket=bucket, Key=key)
        metadata = head.get("Metadata", {})
        job_id = metadata.get("job-id", str(uuid.uuid4()))
        connection_id = metadata.get("connection-id")

        _try_send(connection_id, {"type": "status", "jobId": job_id, "status": "processing"})

        try:
            prediction = _run_inference(bucket, key)
        except Exception as exc:
            print(f"Inference failed for job {job_id}: {exc}")
            _try_send(connection_id, {"type": "error", "jobId": job_id, "message": str(exc)})
            return

        RESULTS_TABLE.put_item(
            Item={
                "jobId": job_id,
                "connectionId": connection_id,
                "s3Key": key,
                "prediction": prediction,
            }
        )

        _try_send(
            connection_id,
            {
                "type": "result",
                "jobId": job_id,
                "status": "completed",
                "prediction": prediction,
            },
        )


def _run_inference(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    image_bytes = response["Body"].read()
    content_type = response.get("ContentType", "image/jpeg")

    sm_response = sagemaker_runtime.invoke_endpoint(
        EndpointName=ENDPOINT_NAME,
        ContentType=content_type,
        Body=image_bytes,
    )
    return json.loads(sm_response["Body"].read())


def _try_send(connection_id, payload):
    if not connection_id:
        return
    try:
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(payload).encode("utf-8"),
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "GoneException":
            CONNECTIONS_TABLE.delete_item(Key={"connectionId": connection_id})
        else:
            raise
