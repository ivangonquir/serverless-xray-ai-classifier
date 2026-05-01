"""
Auth Handler — POST /auth/login, POST /auth/logout, POST /auth/seed

login:
  Validates username + password against UsersTable.
  Passwords are stored as HMAC-SHA256(password, PASSWORD_SECRET).
  On success, creates a 24-hour session token in SessionsTable and
  returns it to the client.

logout:
  Deletes the session record so the token is immediately invalidated.

seed (dev only):
  Creates a default doctor account for first-time setup so the system
  can be tested before a proper user-management UI is built.
"""

import bcrypt
import json
import os
import time
import uuid
from datetime import datetime, timezone
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
sessions_table = dynamodb.Table(os.environ["SESSIONS_TABLE"])
audit_log_table = dynamodb.Table(os.environ["AUDIT_LOG_TABLE"])
session = boto3.session.Session()

def _log(level, message, action=None, extra=None, trace_id=None):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        "traceId": trace_id or "no-trace",
    }
    if action:
        entry["action"] = action
    if extra:
        extra.pop("timestamp", None)
        extra.pop("level", None)
        extra.pop("message", None)
        extra.pop("traceId", None)
        entry.update(extra)
    print(json.dumps(entry, default=str))  # default=str 以防某些类型无法序列化

def _cors_headers(event):
    origin = event.get("headers", {}).get("origin", "")
    allowed = os.environ.get("ALLOWED_ORIGINS", "").split(",")
    print(f"CORS DEBUG origin={origin} allowed={allowed}")
    if origin in allowed:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Credentials": "true",
            "Content-Type": "application/json"
        }
    return {"Content-Type": "application/json"}

def get_secret():
    secret_name = os.environ.get("SECRET_NAME", "lunachat")
    region_name = "eu-west-1"
    client = session.client(service_name='secretsmanager', region_name=region_name)

    try:
        response = client.get_secret_value(SecretId=secret_name)
        _log("INFO", "Secret fetched successfully", action="SECRET_FETCH", extra={"secretName": secret_name})
        return response['SecretString']
    except Exception as e:
        _log("ERROR", "Failed to fetch password secret – cannot proceed",
             action="SECRET_FETCH_FAILED",
             extra={"secretName": secret_name, "errorType": type(e).__name__})
        raise RuntimeError("Secrets Manager unreachable") from None
PASSWORD_SECRET = get_secret()

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Content-Type": "application/json",
}


def lambda_handler(event, context):
    trace_id = event.get("requestContext", {}).get("requestId") or context.aws_request_id
    source_ip = event.get("requestContext", {}).get("http", {}).get("sourceIp", "unknown")
    path = event.get("path", "")
    method = event.get("httpMethod", "")
    _log("INFO", "Request started", action=f"{method}:{path}",
         extra={"sourceIp": source_ip}, trace_id=trace_id)
    if method == "OPTIONS":
        _log("INFO", "OPTIONS request received", action=f"OPTIONS:{path}", trace_id=trace_id)
        return _resp(204, {}, event)
    if method == "POST" and path.endswith("/login"):
        result = _login(event,trace_id)
    elif method == "POST" and path.endswith("/logout"):
        result = _logout(event,trace_id)
    elif method == "POST" and path.endswith("/seed"):
        result = _seed(trace_id)
    else:
        _log("WARNING", "No route matched", action=f"{method}:{path}",
             extra={"sourceIp": source_ip}, trace_id=trace_id)
        result = _resp(404, {"error": "Not found"},event)
    _log("INFO", "Request completed", action=f"{method}:{path}",
         extra={"statusCode": result.get("statusCode")}, trace_id=trace_id)
    return result


# ── Login ─────────────────────────────────────────────────────────────────

def _login(event,trace_id):
    body = _parse_body(event)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        _log("WARNING", "Missing credentials in login request", action="LOGIN",
             extra={"usernameProvided": bool(username), "passwordProvided": bool(password)},
             trace_id=trace_id)
        return _resp(400, {"error": "username and password are required"},event)

    user = _find_user_by_username(username)
    if not user:
        _log("WARNING", "Login failed: user not found or wrong password", action="LOGIN_FAILED",
             extra={"username": username[:3] + "***"},
             trace_id=trace_id)
        return _resp(401, {"error": "Invalid credentials"},event)

    if not _verify_password(password, user["passwordHash"]):
        _log("WARNING", "Login failed: password mismatch", action="LOGIN_FAILED",
             extra={"userId": user["userId"], "username": username[:3] + "***"},
             trace_id=trace_id)
        _write_audit(user["userId"], "LOGIN_FAILED", "User", user["userId"])
        return _resp(401, {"error": "Invalid credentials"},event)

    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    sessions_table.put_item(Item={
        "sessionToken": token,
        "userId": user["userId"],
        "createdAt": now,
        "TTL": int(time.time()) + 86400,  # 24-hour expiry
    })

    _write_audit(user["userId"], "LOGIN", "User", user["userId"])
    _log("INFO", "Login successful", action="LOGIN",
         extra={"userId": user["userId"], "role": user.get("role", "doctor")},
         trace_id=trace_id)
    return _resp(200, {
        "sessionToken": token,
        "userId": user["userId"],
        "username": user["username"],
        "role": user.get("role", "doctor"),
    },event)


# ── Logout ────────────────────────────────────────────────────────────────

def _logout(event,trace_id):
    token = _extract_token(event)
    if not token:
        _log("WARNING", "Logout request missing token", action="LOGOUT", trace_id=trace_id)
        return _resp(400, {"error": "Missing Authorization header"},event)

    resp = sessions_table.get_item(Key={"sessionToken": token})
    session_item = resp.get("Item")
    if session_item:
        sessions_table.delete_item(Key={"sessionToken": token})
        _write_audit(session_item["userId"], "LOGOUT", "Session", token)
        _log("INFO", "Logout successful", action="LOGOUT",
             extra={"userId": session_item["userId"]}, trace_id=trace_id)
    else:
        _log("WARNING", "Logout attempted with invalid/expired token", action="LOGOUT",
             extra={"tokenPrefix": token[:4] + "***"}, trace_id=trace_id)
    return _resp(200, {"message": "Logged out"},event)


# ── Seed ──────────────────────────────────────────────────────────────────

def _seed(trace_id):
    """Creates a default doctor account if it does not already exist."""
    _log("WARNING", "Seed endpoint called", action="SEED",
         extra={"note": "Should be disabled in production"}, trace_id=trace_id)
    default_users = [
        {"username": "doctor", "password": "Luna2024!", "role": "doctor"},
        {"username": "admin",  "password": "Luna2024!", "role": "admin"},
    ]
    created = []
    for u in default_users:
        if _find_user_by_username(u["username"]):
            continue
        user_id = str(uuid.uuid4())
        users_table.put_item(Item={
            "userId": user_id,
            "username": u["username"],
            "passwordHash": _hash_password(u["password"]),
            "role": u["role"],
            "createdAt": datetime.now(timezone.utc).isoformat(),
        })
        created.append(u["username"])
    _log("INFO", "Seed completed", action="SEED",
         extra={"created": created}, trace_id=trace_id)
    return _resp(200, {
        "message": "Seed complete",
        "created": created,
        "note": "Disable this endpoint before going to production",
    })


# ── Helpers ───────────────────────────────────────────────────────────────

def _find_user_by_username(username: str) -> dict | None:
    resp = users_table.query(
        IndexName="UsernameIndex",
        KeyConditionExpression=Key("username").eq(username),
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, stored_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), stored_hash.encode())


def _extract_token(event: dict) -> str:
    header = (event.get("headers") or {}).get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):]
    return header.strip()


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
    except Exception as e:
        _log("ERROR", "Failed to write audit log", action="AUDIT_ERROR",
             extra={
                 "userId": user_id,
                 "action": action,
                 "resourceType": resource_type,
                 "resourceId": resource_id,
                 "errorType": type(e).__name__,
                 "errorMessage": str(e)[:200]
             })


def _parse_body(event: dict) -> dict:
    try:
        return json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _resp(status: int, body: dict,event=None) -> dict:
    headers = _cors_headers(event) if event else CORS
    return {
        "statusCode": status,
        "headers": headers,
        "body": json.dumps(body)
    }