"""
Lambda Authorizer — validates session tokens for every protected REST route.

Improvements (security hardening):
  - Checks token TTL explicitly (not relying only on DynamoDB TTL sweep).
  - Optionally extends the session TTL if it's about to expire.

Flow:
  1. Extract "Bearer <token>" from the Authorization header.
  2. Look up the token in SessionsTable.
  3. If found and not expired (explicit TTL check), optionally extend TTL.
  4. Return an ALLOW IAM policy with userId in context.
  5. Write an audit record for every authorised request.
  6. Raise 'Unauthorized' on failure → API Gateway returns 401.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import boto3

dynamodb = boto3.resource("dynamodb")
sessions_table = dynamodb.Table(os.environ["SESSIONS_TABLE"])
audit_log_table = dynamodb.Table(os.environ["AUDIT_LOG_TABLE"])

# ── SECURITY HARDENING ──
SESSION_EXTEND_THRESHOLD = int(os.environ.get("SESSION_EXTEND_THRESHOLD", "3600"))
SESSION_TTL_SECONDS = 86400  # 24 h, must match the value set during login


def lambda_handler(event, context):
    token = _extract_token(event.get("authorizationToken", ""))
    if not token:
        print(json.dumps({"msg": "Missing token", "level": "WARN"}))
        raise Exception("Unauthorized")

    # Log token prefix only (avoid full token leakage)
    safe_token = token[:4] + "***" if len(token) > 4 else token
    print(json.dumps({"msg": "Authorizing", "tokenPrefix": safe_token}))

    session = _get_session(token)
    if not session:
        print(json.dumps({"msg": "Session not found", "tokenPrefix": safe_token, "level": "WARN"}))
        raise Exception("Unauthorized")

    user_id = session["userId"]
    current_epoch = int(time.time())
    ttl_value = int(session.get("TTL", 0))

    # ── Explicit TTL check ──
    if ttl_value <= current_epoch:
        print(json.dumps({
            "msg": "Token expired (TTL check)",
            "userId": user_id,
            "tokenPrefix": safe_token,
            "ttl": ttl_value,
            "now": current_epoch,
            "level": "WARN"
        }))
        raise Exception("Unauthorized")

    # ── Silent session extension if close to expiry ──
    remaining = ttl_value - current_epoch
    if remaining < SESSION_EXTEND_THRESHOLD:
        new_ttl = current_epoch + SESSION_TTL_SECONDS
        print(json.dumps({
            "msg": "Extending session",
            "userId": user_id,
            "tokenPrefix": safe_token,
            "oldTTL": ttl_value,
            "newTTL": new_ttl,
            "remainingSeconds": remaining,
            "threshold": SESSION_EXTEND_THRESHOLD
        }))
        try:
            sessions_table.update_item(
                Key={"sessionToken": token},
                UpdateExpression="SET TTL = :new_ttl",
                ExpressionAttributeValues={":new_ttl": new_ttl}
            )
            print(json.dumps({"msg": "Session extension succeeded", "tokenPrefix": safe_token}))
        except Exception as e:
            print(json.dumps({
                "msg": "Session extension failed",
                "tokenPrefix": safe_token,
                "error": str(e),
                "level": "ERROR"
            }))
            # fail silently, never block the request
    else:
        print(json.dumps({
            "msg": "Session not extended",
            "remainingSeconds": remaining,
            "threshold": SESSION_EXTEND_THRESHOLD
        }))

    method_arn = event.get("methodArn", "*")
    _write_audit(user_id, method_arn)

    # Final success log
    print(json.dumps({
        "msg": "Authorized",
        "userId": user_id,
        "methodArn": method_arn
    }))

    return {
        "principalId": user_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": "Allow",
                    "Resource": method_arn,
                }
            ],
        },
        "context": {
            "userId": user_id,
        },
    }


# ── Helpers ──────────────────────────────────────────────────────────────

def _extract_token(header_value: str) -> str:
    if header_value.startswith("Bearer "):
        return header_value[len("Bearer "):]
    return header_value.strip()


def _get_session(token: str) -> dict | None:
    try:
        resp = sessions_table.get_item(Key={"sessionToken": token})
        return resp.get("Item")
    except Exception:
        return None


def _write_audit(user_id: str, method_arn: str):
    try:
        now = datetime.now(timezone.utc).isoformat()
        parts = method_arn.split("/")
        action = f"{parts[-2]} /{parts[-1]}" if len(parts) >= 2 else method_arn
        audit_log_table.put_item(Item={
            "logId": str(uuid.uuid4()),
            "timestamp": now,
            "userId": user_id,
            "action": f"API_ACCESS: {action}",
            "resourceType": "REST_API",
            "resourceId": method_arn,
            "statusCode": 200,
        })
    except Exception:
        pass   # audit never blocks the request