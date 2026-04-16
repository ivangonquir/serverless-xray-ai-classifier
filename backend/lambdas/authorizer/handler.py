"""
Lambda Authorizer — validates session tokens for every protected REST route.

Flow:
  1. Extract "Bearer <token>" from the Authorization header.
  2. Look up the token in SessionsTable.
  3. If found and not expired (DynamoDB TTL handles expiry), return an ALLOW
     IAM policy and inject userId into the authorizer context so downstream
     Lambdas can read it from event['requestContext']['authorizer']['userId'].
  4. Write an audit record (FR-1.2) for every authorised request.
  5. Raise an explicit 'Unauthorized' exception on failure so API Gateway
     returns a 401 to the client.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
sessions_table = dynamodb.Table(os.environ["SESSIONS_TABLE"])
audit_log_table = dynamodb.Table(os.environ["AUDIT_LOG_TABLE"])


def lambda_handler(event, context):
    token = _extract_token(event.get("authorizationToken", ""))
    if not token:
        raise Exception("Unauthorized")

    session = _get_session(token)
    if not session:
        raise Exception("Unauthorized")

    user_id = session["userId"]
    method_arn = event.get("methodArn", "*")

    _write_audit(user_id, method_arn)

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
    """Returns the raw token from 'Bearer <token>' or an empty string."""
    if header_value.startswith("Bearer "):
        return header_value[len("Bearer "):]
    return header_value.strip()


def _get_session(token: str) -> dict | None:
    """Fetches the session item from DynamoDB (TTL expiry is automatic)."""
    try:
        resp = sessions_table.get_item(Key={"sessionToken": token})
        return resp.get("Item")
    except Exception:
        return None


def _write_audit(user_id: str, method_arn: str):
    """Records the authorised API access in the audit log (FR-1.2)."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        # Derive a human-readable action from the method ARN
        # e.g. "arn:aws:execute-api:...:prod/GET/patients" → "GET /patients"
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
        # Audit failures must never block the request
        pass
