"""
Diagnostic Handler

POST /patients/{patientId}/diagnose
  Validates that the patient exists and that an image S3 key is provided,
  creates a QUEUED job record in DiagnosticResultsTable, then sends a
  message to the SQS DiagnosticQueue to trigger the InferenceWorker.
  Satisfies FR-2.1 (input validation), FR-2.2 (routing), FR-2.3 (triggering).

GET  /patients/{patientId}/results
  Returns the full diagnostic history for a patient, newest first (FR-4.3).
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
sqs_client = boto3.client("sqs")

patients_table = dynamodb.Table(os.environ["PATIENTS_TABLE"])
results_table = dynamodb.Table(os.environ["DIAGNOSTIC_RESULTS_TABLE"])
audit_log_table = dynamodb.Table(os.environ["AUDIT_LOG_TABLE"])

DIAGNOSTIC_QUEUE_URL = os.environ["DIAGNOSTIC_QUEUE_URL"]

AUDIT_RETENTION_SECONDS = int(os.environ.get("AUDIT_RETENTION_SECONDS", str(7 * 365 * 24 * 60 * 60)))


def lambda_handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}
    patient_id = path_params.get("patientId")
    user_id = (event.get("requestContext", {}).get("authorizer") or {}).get("userId", "unknown")

    if not patient_id:
        _write_audit(user_id, "DIAGNOSIS_REQUEST", "DiagnosticJob", "missing-patient-id", 400)
        return _resp(400, {"error": "patientId is required"}, event)

    if method == "POST" and path.endswith("/diagnose"):
        return _trigger_diagnosis(event, patient_id, user_id)
    if method == "GET" and path.endswith("/results"):
        return _get_results(patient_id, user_id, event)

    _write_audit(user_id, "ROUTE_NOT_FOUND", "DiagnosticJob", patient_id, 404, patient_id)
    return _resp(404, {"error": "Not found"}, event)


# ── Trigger diagnosis ─────────────────────────────────────────────────────

def _trigger_diagnosis(event: dict, patient_id: str, user_id: str):
    # FR-2.1: Input validation
    patient_resp = patients_table.get_item(Key={"patientId": patient_id})
    if not patient_resp.get("Item"):
        _write_audit(user_id, "TRIGGER_DIAGNOSIS", "DiagnosticJob", patient_id, 404, patient_id)
        return _resp(404, {"error": f"Patient {patient_id} not found"}, event)

    body = _parse_body(event)
    s3_key = body.get("s3Key")
    connection_id = body.get("connectionId", "")

    if not s3_key:
        _write_audit(user_id, "TRIGGER_DIAGNOSIS", "DiagnosticJob", patient_id, 400, patient_id)
        return _resp(400, {"error": "s3Key is required (path of the uploaded DICOM in S3)"}, event)

    # Validate key belongs to this patient
    if not s3_key.startswith(f"uploads/{patient_id}/"):
        _write_audit(user_id, "TRIGGER_DIAGNOSIS", "DiagnosticJob", s3_key, 400, patient_id)
        return _resp(400, {"error": "s3Key does not belong to this patient"}, event)

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Create job record in QUEUED state
    results_table.put_item(Item={
        "jobId": job_id,
        "patientId": patient_id,
        "status": "QUEUED",
        "s3Key": s3_key,
        "connectionId": connection_id,
        "requestedBy": user_id,
        "createdAt": now,
        "completedAt": None,
        "lunaRiskScore": None,
        "nodulesDetected": [],
        "imagePrediction": None,
        "clinicalSummary": None,
    })

    # Update patient status to show work is in progress (FR-UI 1.2)
    patients_table.update_item(
        Key={"patientId": patient_id},
        UpdateExpression="SET #s = :s, updatedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "PENDING_ANALYSIS",
            ":ts": now,
        },
    )

    # FR-2.3: Trigger ML pipeline asynchronously via SQS
    sqs_client.send_message(
        QueueUrl=DIAGNOSTIC_QUEUE_URL,
        MessageBody=json.dumps({
            "jobId": job_id,
            "patientId": patient_id,
            "s3Key": s3_key,
            "connectionId": connection_id,
        }),
    )

    _write_audit(user_id, "TRIGGER_DIAGNOSIS", "DiagnosticJob", job_id, 202, patient_id)

    return _resp(202, {
        "jobId": job_id,
        "status": "QUEUED",
        "message": "Diagnostic job queued. Results will be pushed via WebSocket when complete.",
    }, event)


# ── Get results ───────────────────────────────────────────────────────────

def _get_results(patient_id: str, user_id: str, event: dict):
    """Returns all diagnostic jobs for a patient, sorted newest first."""
    resp = results_table.query(
        IndexName="PatientIdIndex",
        KeyConditionExpression=Key("patientId").eq(patient_id),
        ScanIndexForward=False,  # newest first
    )
    results = resp.get("Items", [])

    # Paginate for patients with many historical scans
    while "LastEvaluatedKey" in resp:
        resp = results_table.query(
            IndexName="PatientIdIndex",
            KeyConditionExpression=Key("patientId").eq(patient_id),
            ScanIndexForward=False,
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        results.extend(resp.get("Items", []))

    _write_audit(user_id, "VIEW_RESULTS", "DiagnosticJob", patient_id, 200, patient_id)

    return _resp(200, {
        "patientId": patient_id,
        "results": [_serialize(r) for r in results],
        "count": len(results),
    }, event)


# ── Helpers ───────────────────────────────────────────────────────────────

def _serialize(obj: dict) -> dict:
    from decimal import Decimal
    result = {}
    for k, v in obj.items():
        if isinstance(v, Decimal):
            result[k] = float(v) if v % 1 else int(v)
        else:
            result[k] = v
    return result


def _write_audit(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    status_code: int = 200,
    patient_id: str = "",
):
    try:
        now_epoch = int(time.time())
        now = datetime.fromtimestamp(now_epoch, timezone.utc).isoformat()
        audit_log_table.put_item(Item={
            "logId": str(uuid.uuid4()),
            "timestamp": now,
            "userId": user_id,
            "action": action,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "patientId": patient_id,
            "statusCode": status_code,
            "expiresAt": now_epoch + AUDIT_RETENTION_SECONDS,
        })
    except Exception:
        pass


def _parse_body(event: dict) -> dict:
    try:
        return json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _cors_headers(event: dict | None) -> dict:
    if not event:
        return {"Content-Type": "application/json", "Vary": "Origin"}
    headers = event.get("headers") or {}
    origin = headers.get("origin") or headers.get("Origin") or ""
    if _is_allowed_origin(origin):
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,GET,POST",
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
            "Content-Type": "application/json",
        }
    return {"Content-Type": "application/json", "Vary": "Origin"}


def _is_allowed_origin(origin: str) -> bool:
    normalized = (origin or "").rstrip("/")
    normalized_lower = normalized.lower()
    if normalized_lower.startswith("https://") and normalized_lower.endswith(".cloudfront.net"):
        return True

    allowed_origins = {
        value.strip().rstrip("/")
        for value in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if value.strip()
    }
    return normalized in allowed_origins


def _resp(status: int, body: dict, event: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": _cors_headers(event),
        "body": json.dumps(body, default=str),
    }
