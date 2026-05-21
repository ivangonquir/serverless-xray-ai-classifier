"""
Auth Handler — POST /auth/login, POST /auth/logout, POST /auth/seed

login:
  Validates username + password against UsersTable.
  Passwords are stored as bcrypt hashes.
  On success, creates a 24-hour session token in SessionsTable and
  returns it to the client.

logout:
  Deletes the session record so the token is immediately invalidated.

seed (dev only):
  Protected and disabled by default. When explicitly enabled, creates only
  the users supplied in the request body.
"""

import bcrypt
import json
import os
import time
import uuid
from datetime import datetime, timezone
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


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
    print(json.dumps(entry, default=str))

def _cors_headers(event):
    headers = event.get("headers") or {}
    origin = headers.get("origin") or headers.get("Origin") or ""
    if _is_allowed_origin(origin):
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
            "Content-Type": "application/json"
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
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Content-Type": "application/json",
}

AUDIT_RETENTION_SECONDS = int(os.environ.get("AUDIT_RETENTION_SECONDS", str(7 * 365 * 24 * 60 * 60)))
SEED_ENABLED_VALUES = {"1", "true", "yes"}


def lambda_handler(event, context):
    trace_id = event.get("requestContext", {}).get("requestId") or context.aws_request_id
    source_ip = _source_ip(event)
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
        result = _seed(event, trace_id)
    else:
        _log("WARNING", "No route matched", action=f"{method}:{path}",
             extra={"sourceIp": source_ip}, trace_id=trace_id)
        result = _resp(404, {"error": "Not found"},event)
    _log("INFO", "Request completed", action=f"{method}:{path}",
         extra={"statusCode": result.get("statusCode")}, trace_id=trace_id)
    return result


# ── Login ─────────────────────────────────────────────────────────────────

LOGIN_ATTEMPTS_TABLE = dynamodb.Table(os.environ["LOGIN_ATTEMPTS_TABLE"])

def _get_login_attempts(ip):
    resp = LOGIN_ATTEMPTS_TABLE.get_item(Key={"ip": ip})
    return resp.get("Item")

def _increment_login_failure(ip, max_attempts, lockout_seconds):
    now_epoch = int(time.time())
    lockout_until = now_epoch + lockout_seconds
    try:
        LOGIN_ATTEMPTS_TABLE.update_item(
            Key={"ip": ip},
            UpdateExpression=(
                "ADD attempts :inc "
                "SET lockoutUntil = if_not_exists(lockoutUntil, :zero), "
                "#t = :ttl"
            ),
            ConditionExpression="attribute_not_exists(lockoutUntil) OR lockoutUntil < :now",
            ExpressionAttributeNames={"#t": "TTL"},
            ExpressionAttributeValues={
                ":inc": 1,
                ":zero": 0,
                ":ttl": lockout_until,
                ":now": now_epoch
            }
        )
        # Si el update tuvo éxito, verificar si alcanzamos el umbral
        attempts_after = _get_login_attempts(ip)
        if attempts_after and attempts_after.get("attempts", 0) >= max_attempts:
            LOGIN_ATTEMPTS_TABLE.update_item(
                Key={"ip": ip},
                UpdateExpression="SET lockoutUntil = :lock, attempts = :zero, #t = :lock",
                ExpressionAttributeNames={"#t": "TTL"},
                ExpressionAttributeValues={
                    ":lock": now_epoch + lockout_seconds,
                    ":zero": 0
                }
            )
    except ClientError:
        # Only ignore the condition check failure (lockout still active)
        pass


def _reset_login_attempts(ip):
    try:
        LOGIN_ATTEMPTS_TABLE.delete_item(Key={"ip": ip})
    except Exception:
        pass  # no queremos que falle el login por esto

def _login(event, trace_id):
    body = _parse_body(event)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    source_ip = _source_ip(event)

    if not username or not password:
        _log("WARNING", "Missing credentials in login request", action="LOGIN",
             extra={"usernameProvided": bool(username), "passwordProvided": bool(password)},
             trace_id=trace_id)
        _write_audit("unknown", "LOGIN_FAILED", "User", _mask(username) or "unknown", 400)
        return _resp(400, {"error": "username and password are required"}, event)

    # --- Rate limiting check ---
    MAX_ATTEMPTS = 5
    LOCKOUT_SECONDS = 900  # 15 minutos
    now_epoch = int(time.time())

    # Obtener estado de intentos
    attempts_item = _get_login_attempts(source_ip)
    if attempts_item:
        lockout = attempts_item.get("lockoutUntil", 0)
        if lockout > now_epoch:
            _log("WARNING", "Login blocked due to lockout", action="LOGIN_LOCKOUT",
                 extra={"sourceIp": source_ip, "lockoutUntil": lockout}, trace_id=trace_id)
            _write_audit("unknown", "LOGIN_LOCKOUT", "User", _mask(username), 429)
            # ── FIX: convert Decimal to int for JSON ──
            return _resp(429, {
                "error": "Too many attempts. Try again later.",
                "retryAfter": int(lockout - now_epoch)
            }, event)

    # --- Validación de credenciales ---
    user = _find_user_by_username(username)
    if not user:
        # ── FIX: user not found – no audit, but count failure ──
        _increment_login_failure(source_ip, MAX_ATTEMPTS, LOCKOUT_SECONDS)
        _log("WARNING", "Login failed: user not found", action="LOGIN_FAILED",
             extra={"username": username[:3] + "***"}, trace_id=trace_id)
        _write_audit("unknown", "LOGIN_FAILED", "User", _mask(username), 401)
        return _resp(401, {"error": "Invalid credentials"}, event)

    if not _verify_password(password, user["passwordHash"]):
        # ── FIX: password wrong – full audit with correct args ──
        _increment_login_failure(source_ip, MAX_ATTEMPTS, LOCKOUT_SECONDS)
        _log("WARNING", "Login failed: password mismatch", action="LOGIN_FAILED",
             extra={"userId": user["userId"], "username": username[:3] + "***"},
             trace_id=trace_id)
        _write_audit(user["userId"], "LOGIN_FAILED", "User", user["userId"], 401)
        return _resp(401, {"error": "Invalid credentials"}, event)

    # --- Autenticación exitosa: resetear intentos fallidos ---
    _reset_login_attempts(source_ip)

    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    sessions_table.put_item(Item={
        "sessionToken": token,
        "userId": user["userId"],
        "createdAt": now,
        "TTL": int(time.time()) + 86400,  # 24-hour expiry
    })

    _write_audit(user["userId"], "LOGIN", "User", user["userId"], 200)
    _log("INFO", "Login successful", action="LOGIN",
         extra={"userId": user["userId"], "role": user.get("role", "doctor")},
         trace_id=trace_id)
    return _resp(200, {
        "sessionToken": token,
        "userId": user["userId"],
        "username": user["username"],
        "role": user.get("role", "doctor"),
    }, event)


# ── Logout ────────────────────────────────────────────────────────────────

def _logout(event,trace_id):
    token = _extract_token(event)
    if not token:
        _log("WARNING", "Logout request missing token", action="LOGOUT", trace_id=trace_id)
        _write_audit("unknown", "LOGOUT_FAILED", "Session", "missing-token", 400)
        return _resp(400, {"error": "Missing Authorization header"},event)

    resp = sessions_table.get_item(Key={"sessionToken": token})
    session_item = resp.get("Item")
    if session_item:
        sessions_table.delete_item(Key={"sessionToken": token})
        _write_audit(session_item["userId"], "LOGOUT", "Session", _token_ref(token), 200)
        _log("INFO", "Logout successful", action="LOGOUT",
             extra={"userId": session_item["userId"]}, trace_id=trace_id)
    else:
        _log("WARNING", "Logout attempted with invalid/expired token", action="LOGOUT",
             extra={"tokenPrefix": token[:4] + "***"}, trace_id=trace_id)
        _write_audit("unknown", "LOGOUT_FAILED", "Session", _token_ref(token), 401)
    return _resp(200, {"message": "Logged out"},event)


# ── Seed ──────────────────────────────────────────────────────────────────

def _seed(event, trace_id):
    """Creates explicitly supplied test users only when the endpoint is enabled."""
    actor_id = (event.get("requestContext", {}).get("authorizer") or {}).get("userId", "unknown")
    if os.environ.get("ENABLE_SEED_ENDPOINT", "false").lower() not in SEED_ENABLED_VALUES:
        _log("WARNING", "Seed endpoint blocked because it is disabled", action="SEED",
             trace_id=trace_id)
        _write_audit(actor_id, "SEED_BLOCKED", "User", "*", 403)
        return _resp(403, {"error": "Seed endpoint is disabled"}, event)

    _log("WARNING", "Seed endpoint called", action="SEED",
         extra={"note": "Should be disabled in production"}, trace_id=trace_id)
    body = _parse_body(event)
    seed_users = body.get("users")
    if not isinstance(seed_users, list) or not seed_users:
        _write_audit(actor_id, "SEED_FAILED", "User", "*", 400)
        return _resp(400, {"error": "users must be a non-empty list"}, event)

    created = []
    for u in seed_users:
        username = (u.get("username") or "").strip()
        password = u.get("password") or ""
        role = (u.get("role") or "doctor").strip()
        if not username or not password:
            _write_audit(actor_id, "SEED_FAILED", "User", username or "unknown", 400)
            return _resp(400, {"error": "Each seed user requires username and password"}, event)
        if role not in {"doctor", "admin"}:
            _write_audit(actor_id, "SEED_FAILED", "User", _mask(username), 400)
            return _resp(400, {"error": "role must be doctor or admin"}, event)

        if _find_user_by_username(username):
            continue
        user_id = str(uuid.uuid4())
        users_table.put_item(Item={
            "userId": user_id,
            "username": username,
            "passwordHash": _hash_password(password),
            "role": role,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        })
        created.append(username)
    _log("INFO", "Seed completed", action="SEED",
         extra={"created": created}, trace_id=trace_id)
    _write_audit(actor_id, "SEED_USERS", "User", ",".join(created) or "none", 200)
    return _resp(200, {
        "message": "Seed complete",
        "created": created,
    }, event)


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


def _source_ip(event: dict) -> str:
    request_context = event.get("requestContext") or {}
    return (
        (request_context.get("http") or {}).get("sourceIp")
        or (request_context.get("identity") or {}).get("sourceIp")
        or "unknown"
    )


def _mask(value: str) -> str:
    if not value:
        return ""
    return value[:3] + "***"


def _token_ref(token: str) -> str:
    return token[:4] + "***" if token else "missing-token"


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
