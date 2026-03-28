"""
Pre-signed URL Generator Lambda.

Called via WebSocket action "getUploadUrl".
Returns a short-lived S3 pre-signed PUT URL so the browser can upload
the X-ray image directly to S3 without proxying through API Gateway.

Request body (JSON):
  { "action": "getUploadUrl", "jobId": "<uuid>", "contentType": "image/jpeg" }

Response (sent back via WebSocket):
  { "type": "uploadUrl", "url": "<presigned-url>", "jobId": "<uuid>" }
"""

import json
import os
import uuid

import boto3

s3 = boto3.client("s3")
apigw = boto3.client(
    "apigatewaymanagementapi",
    endpoint_url=os.environ.get("WEBSOCKET_ENDPOINT"),
)

BUCKET = os.environ["IMAGE_BUCKET"]
EXPIRY = 300  # seconds


def lambda_handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    body = json.loads(event.get("body") or "{}")

    job_id = body.get("jobId") or str(uuid.uuid4())
    content_type = body.get("contentType", "image/jpeg")
    key = f"uploads/{job_id}.jpg"

    presigned_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": BUCKET,
            "Key": key,
            "ContentType": content_type,
            "Metadata": {
                "job-id": job_id,
                "connection-id": connection_id,
            },
        },
        ExpiresIn=EXPIRY,
    )

    _send(connection_id, {"type": "uploadUrl", "url": presigned_url, "jobId": job_id, "key": key})
    return {"statusCode": 200, "body": "OK"}


def _send(connection_id, payload):
    apigw.post_to_connection(
        ConnectionId=connection_id,
        Data=json.dumps(payload).encode("utf-8"),
    )
