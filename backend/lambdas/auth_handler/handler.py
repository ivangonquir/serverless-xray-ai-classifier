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

import hashlib
import hmac
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

PASSWORD_SECRET = os.environ.get("PASSWORD_SECRET", "luna-dev-secret-change-in-production")

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Content-Type": "application/json",
}


def lambda_handler(event, context):
    path = event.get("path", "")
    method = event.get("httpMethod", "")

    if method == "POST" and path.endswith("/login"):
        return _login(event)
    if method == "POST" and path.endswith("/logout"):
        return _logout(event)
    if method == "POST" and path.endswith("/seed"):
        return _seed()

    return _resp(404, {"error": "Not found"})


# ── Login ─────────────────────────────────────────────────────────────────

def _login(event):
    body = _parse_body(event)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return _resp(400, {"error": "username and password are required"})

    user = _find_user_by_username(username)
    if not user:
        return _resp(401, {"error": "Invalid credentials"})

    if not _verify_password(password, user["passwordHash"]):
        _write_audit(user["userId"], "LOGIN_FAILED", "User", user["userId"])
        return _resp(401, {"error": "Invalid credentials"})

    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    sessions_table.put_item(Item={
        "sessionToken": token,
        "userId": user["userId"],
        "createdAt": now,
        "TTL": int(time.time()) + 86400,  # 24-hour expiry
    })

    _write_audit(user["userId"], "LOGIN", "User", user["userId"])

    return _resp(200, {
        "sessionToken": token,
        "userId": user["userId"],
        "username": user["username"],
        "role": user.get("role", "doctor"),
    })


# ── Logout ────────────────────────────────────────────────────────────────

def _logout(event):
    token = _extract_token(event)
    if not token:
        return _resp(400, {"error": "Missing Authorization header"})

    resp = sessions_table.get_item(Key={"sessionToken": token})
    session = resp.get("Item")
    if session:
        sessions_table.delete_item(Key={"sessionToken": token})
        _write_audit(session["userId"], "LOGOUT", "Session", token)

    return _resp(200, {"message": "Logged out"})


# ── Seed ──────────────────────────────────────────────────────────────────

def _seed():
    """Creates a default doctor account if it does not already exist."""
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
    return hmac.new(
        PASSWORD_SECRET.encode(),
        password.encode(),
        hashlib.sha256,
    ).hexdigest()


def _verify_password(password: str, stored_hash: str) -> bool:
    expected = _hash_password(password)
    return hmac.compare_digest(expected, stored_hash)


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
