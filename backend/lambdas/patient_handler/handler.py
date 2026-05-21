"""
Patient Handler — patient CRUD operations

GET  /patients             List all patients sorted by LUNA Risk Score DESC
                           (drives the Command Center triage list, FR-UI 1.1)
GET  /patients/{id}        Patient detail: demographics + clinical risk factors
                           + most recent diagnostic result (FR-UI 2.1)
POST /patients             Register a new patient record
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")
patients_table = dynamodb.Table(os.environ["PATIENTS_TABLE"])
results_table = dynamodb.Table(os.environ["DIAGNOSTIC_RESULTS_TABLE"])
audit_log_table = dynamodb.Table(os.environ["AUDIT_LOG_TABLE"])
DICOM_BUCKET = os.environ.get("DICOM_BUCKET", "")

AUDIT_RETENTION_SECONDS = int(os.environ.get("AUDIT_RETENTION_SECONDS", str(7 * 365 * 24 * 60 * 60)))


def lambda_handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}
    user_id = (event.get("requestContext", {}).get("authorizer") or {}).get("userId", "unknown")

    if method == "GET" and not path_params.get("patientId"):
        return _list_patients(user_id, event)
    if method == "GET" and path_params.get("patientId"):
        return _get_patient(path_params["patientId"], user_id, event)
    if method == "POST" and not path_params.get("patientId"):
        return _create_patient(event, user_id)

    _write_audit(user_id, "ROUTE_NOT_FOUND", "Patient", path or "unknown", 404)
    return _resp(404, {"error": "Not found"}, event)


# ── List patients ─────────────────────────────────────────────────────────

def _list_patients(user_id: str, event: dict):
    """
    Returns every patient ordered by lastLunaRiskScore descending so the
    highest-risk cases appear at the top of the triage list (FR-UI 1.1).
    """
    resp = patients_table.scan()
    patients = resp.get("Items", [])

    # Paginate if the table is large
    while "LastEvaluatedKey" in resp:
        resp = patients_table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        patients.extend(resp.get("Items", []))

    # Sort by risk score descending; unscored patients go to the bottom
    patients.sort(key=lambda p: float(p.get("lastLunaRiskScore", 0)), reverse=True)

    _write_audit(user_id, "LIST_PATIENTS", "Patient", "*", 200)
    return _resp(200, {"patients": [_serialize(p) for p in patients]}, event)


# ── Get patient ───────────────────────────────────────────────────────────

def _get_patient(patient_id: str, user_id: str, event: dict):
    resp = patients_table.get_item(Key={"patientId": patient_id})
    patient = resp.get("Item")
    if not patient:
        _write_audit(user_id, "VIEW_PATIENT", "Patient", patient_id, 404)
        return _resp(404, {"error": f"Patient {patient_id} not found"}, event)

    # Fetch the most recent diagnostic result for context (FR-UI 2.1)
    latest_result = _get_latest_result(patient_id)

    serialized_result = None
    if latest_result:
        serialized_result = _serialize(latest_result)
        s3_key = latest_result.get("s3Key")
        if s3_key and DICOM_BUCKET:
            try:
                serialized_result["imageUrl"] = s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": DICOM_BUCKET, "Key": s3_key},
                    ExpiresIn=3600,
                )
            except Exception:
                pass

    _write_audit(user_id, "VIEW_PATIENT", "Patient", patient_id, 200)
    return _resp(200, {
        "patient": _serialize(patient),
        "latestResult": serialized_result,
    }, event)


# ── Create patient ────────────────────────────────────────────────────────

def _create_patient(event: dict, user_id: str):
    body = _parse_body(event)

    required = ["name", "dateOfBirth"]
    for field in required:
        if not body.get(field):
            _write_audit(user_id, "CREATE_PATIENT", "Patient", "*", 400)
            return _resp(400, {"error": f"Missing required field: {field}"}, event)

    patient_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "patientId": patient_id,
        "name": body["name"],
        "dateOfBirth": body["dateOfBirth"],
        "age": int(body.get("age", 0)),
        # Clinical risk factors used in multimodal fusion (FR-4.2)
        "smokingHistory": body.get("smokingHistory", "never"),  # never / former / current
        "packYears": int(body.get("packYears", 0)),
        "familyHistory": bool(body.get("familyHistory", False)),
        "comorbidities": body.get("comorbidities", []),
        # Dashboard state (FR-UI 1.2)
        "status": "PENDING_ANALYSIS",
        "lastLunaRiskScore": None,
        "createdAt": now,
        "updatedAt": now,
    }
    patients_table.put_item(Item=item)

    _write_audit(user_id, "CREATE_PATIENT", "Patient", patient_id, 201)
    return _resp(201, {"patient": _serialize(item)}, event)


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_latest_result(patient_id: str) -> dict | None:
    """Queries the PatientIdIndex GSI for the most recent completed job."""
    resp = results_table.query(
        IndexName="PatientIdIndex",
        KeyConditionExpression="patientId = :pid",
        ExpressionAttributeValues={":pid": patient_id},
        ScanIndexForward=False,  # newest first
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def _serialize(obj):
    """Converts Decimal types from DynamoDB to plain Python types."""
    if obj is None:
        return None
    from decimal import Decimal
    result = {}
    for k, v in obj.items():
        if isinstance(v, Decimal):
            result[k] = float(v) if v % 1 else int(v)
        elif isinstance(v, list):
            result[k] = [
                float(i) if isinstance(i, Decimal) else i for i in v
            ]
        else:
            result[k] = v
    return result


def _write_audit(user_id: str, action: str, resource_type: str, resource_id: str, status_code: int = 200):
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
