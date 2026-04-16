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
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb")
patients_table = dynamodb.Table(os.environ["PATIENTS_TABLE"])
results_table = dynamodb.Table(os.environ["DIAGNOSTIC_RESULTS_TABLE"])
audit_log_table = dynamodb.Table(os.environ["AUDIT_LOG_TABLE"])

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Content-Type": "application/json",
}


def lambda_handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}
    user_id = (event.get("requestContext", {}).get("authorizer") or {}).get("userId", "unknown")

    if method == "GET" and not path_params.get("patientId"):
        return _list_patients(user_id)
    if method == "GET" and path_params.get("patientId"):
        return _get_patient(path_params["patientId"], user_id)
    if method == "POST" and not path_params.get("patientId"):
        return _create_patient(event, user_id)

    return _resp(404, {"error": "Not found"})


# ── List patients ─────────────────────────────────────────────────────────

def _list_patients(user_id: str):
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

    _write_audit(user_id, "LIST_PATIENTS", "Patient", "*")
    return _resp(200, {"patients": [_serialize(p) for p in patients]})


# ── Get patient ───────────────────────────────────────────────────────────

def _get_patient(patient_id: str, user_id: str):
    resp = patients_table.get_item(Key={"patientId": patient_id})
    patient = resp.get("Item")
    if not patient:
        return _resp(404, {"error": f"Patient {patient_id} not found"})

    # Fetch the most recent diagnostic result for context (FR-UI 2.1)
    latest_result = _get_latest_result(patient_id)

    _write_audit(user_id, "VIEW_PATIENT", "Patient", patient_id)
    return _resp(200, {
        "patient": _serialize(patient),
        "latestResult": _serialize(latest_result) if latest_result else None,
    })


# ── Create patient ────────────────────────────────────────────────────────

def _create_patient(event: dict, user_id: str):
    body = _parse_body(event)

    required = ["name", "dateOfBirth"]
    for field in required:
        if not body.get(field):
            return _resp(400, {"error": f"Missing required field: {field}"})

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

    _write_audit(user_id, "CREATE_PATIENT", "Patient", patient_id)
    return _resp(201, {"patient": _serialize(item)})


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


def _write_audit(user_id: str, action: str, resource_type: str, resource_id: str):
    try:
        now = datetime.now(timezone.utc).isoformat()
        audit_log_table.put_item(Item={
            "logId": str(uuid.uuid4()),
            "timestamp": now,
            "userId": user_id,
            "action": action,
            "resourceType": resource_type,
            "resourceId": resource_id,
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
        "body": json.dumps(body, default=str),
    }
