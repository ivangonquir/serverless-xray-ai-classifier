"""
Upload Handler — POST /patients/{patientId}/upload

Generates a short-lived (5-minute) pre-signed S3 PUT URL so the browser
can upload a DICOM file directly to S3 without routing large payloads
through API Gateway (FR-3.1).

The S3 key follows the pattern:
    uploads/{patientId}/{jobId}.dcm

Once the file lands in S3 the bucket notification fires automatically,
placing a message on the SQS DiagnosticQueue which triggers the
InferenceWorker Lambda.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
patients_table = dynamodb.Table(os.environ["PATIENTS_TABLE"])
audit_log_table = dynamodb.Table(os.environ["AUDIT_LOG_TABLE"])

DICOM_BUCKET = os.environ["DICOM_BUCKET"]
PRESIGN_EXPIRY_SECONDS = 300  # 5 minutes

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Content-Type": "application/json",
}


def lambda_handler(event, context):
    path_params = event.get("pathParameters") or {}
    patient_id = path_params.get("patientId")
    user_id = (event.get("requestContext", {}).get("authorizer") or {}).get("userId", "unknown")

    if not patient_id:
        return _resp(400, {"error": "patientId is required"})

    # Verify patient exists
    resp = patients_table.get_item(Key={"patientId": patient_id})
    if not resp.get("Item"):
        return _resp(404, {"error": f"Patient {patient_id} not found"})

    body = _parse_body(event)
    # Allow callers to specify the file extension; default to .dcm for CT scans
    file_extension = body.get("fileExtension", "dcm").lstrip(".").lower()
    connection_id = body.get("connectionId", "")  # WebSocket ID for result push

    job_id = str(uuid.uuid4())
    s3_key = f"uploads/{patient_id}/{job_id}.{file_extension}"

    # Embed jobId, patientId and connectionId as S3 object metadata so the
    # InferenceWorker Lambda can retrieve them without an extra DynamoDB lookup
    presigned_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": DICOM_BUCKET,
            "Key": s3_key,
            "ContentType": _content_type(file_extension),
            "Metadata": {
                "jobid": job_id,
                "patientid": patient_id,
                "connectionid": connection_id,
            },
        },
        ExpiresIn=PRESIGN_EXPIRY_SECONDS,
    )

    _write_audit(user_id, "UPLOAD_DICOM", "S3Object", s3_key, patient_id)

    return _resp(200, {
        "uploadUrl": presigned_url,
        "jobId": job_id,
        "s3Key": s3_key,
        "expiresInSeconds": PRESIGN_EXPIRY_SECONDS,
    })


# ── Helpers ───────────────────────────────────────────────────────────────

def _content_type(ext: str) -> str:
    mapping = {
        "dcm": "application/dicom",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }
    return mapping.get(ext, "application/octet-stream")


def _write_audit(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    patient_id: str = "",
):
    try:
        now = datetime.now(timezone.utc).isoformat()
        audit_log_table.put_item(Item={
            "logId": str(uuid.uuid4()),
            "timestamp": now,
            "userId": user_id,
            "action": action,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "patientId": patient_id,
            "statusCode": 200,
        })
    except Exception:
        pass


def _parse_body(event: dict) -> dict:
    try:
        return json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": CORS,
        "body": json.dumps(body),
    }
