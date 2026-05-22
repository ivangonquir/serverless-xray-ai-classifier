"""
seed_dynamodb.py — Create demo user accounts directly in DynamoDB.

This script bypasses the /auth/seed API endpoint and writes user records
straight to the UsersTable using your local AWS credentials.  It is safe
to run multiple times: existing usernames are skipped.

Default demo user created (credentials also documented in .env):
    username : doctorluna
    password : DoctorLuna#2026!
    role     : doctor

To add more users set SEED_USERS_JSON in .env:
    SEED_USERS_JSON='[{"username":"alice","password":"Secure#1","role":"doctor"}]'

Required env vars (loaded from .env):
    USERS_TABLE   — DynamoDB table name for user accounts
    AWS_REGION    — AWS region (default: eu-west-1)
"""

import json
import os
import uuid
from datetime import datetime, timezone

import bcrypt
import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
USERS_TABLE_NAME = os.getenv("USERS_TABLE", "").strip()

# ── Default demo users (always seeded unless already present) ─────────────
# Credentials are documented in .env under DOCTORLUNA_PASSWORD.
DEFAULT_USERS = [
    {
        "username": "doctorluna",
        "password": "DoctorLuna#2026!",
        "role": "doctor",
    }
]


def main():
    if not USERS_TABLE_NAME:
        raise RuntimeError("USERS_TABLE is not set in .env")

    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(USERS_TABLE_NAME)

    # Merge default users with any extra users from the environment
    extra_raw = os.getenv("SEED_USERS_JSON", "[]")
    try:
        extra_users = json.loads(extra_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"SEED_USERS_JSON is not valid JSON: {exc}") from exc

    all_users = DEFAULT_USERS + (extra_users if isinstance(extra_users, list) else [])

    created, skipped = [], []

    for u in all_users:
        username = (u.get("username") or "").strip()
        password = u.get("password") or ""
        role = (u.get("role") or "doctor").strip()

        if not username or not password:
            print(f"  SKIP  (missing username or password): {u}")
            continue

        # Check whether the username already exists (via UsernameIndex GSI)
        resp = table.query(
            IndexName="UsernameIndex",
            KeyConditionExpression=Key("username").eq(username),
            Limit=1,
        )
        if resp.get("Items"):
            skipped.append(username)
            print(f"  SKIP  '{username}' — already exists")
            continue

        # Hash the password with bcrypt (cost factor 12)
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()

        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        table.put_item(Item={
            "userId": user_id,
            "username": username,
            "passwordHash": password_hash,
            "role": role,
            "createdAt": now,
        })
        created.append(username)
        print(f"  OK    '{username}' created (role: {role})")

    print(f"\n✅  Users seeding complete.  created={created}  skipped={skipped}")


if __name__ == "__main__":
    main()
