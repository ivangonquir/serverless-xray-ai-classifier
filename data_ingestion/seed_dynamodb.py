import json
import os

import requests
from dotenv import load_dotenv


load_dotenv()

API_BASE_URL = (os.getenv("NEXT_PUBLIC_API_URL") or "").rstrip("/")
SEED_AUTH_TOKEN = os.getenv("SEED_AUTH_TOKEN")
SEED_USERS_JSON = os.getenv("SEED_USERS_JSON", "[]")


def main():
    if not API_BASE_URL:
        raise RuntimeError("NEXT_PUBLIC_API_URL is required")
    if not SEED_AUTH_TOKEN:
        raise RuntimeError("SEED_AUTH_TOKEN is required because /auth/seed is protected")

    seed_users = json.loads(SEED_USERS_JSON)
    if not isinstance(seed_users, list) or not seed_users:
        raise RuntimeError("SEED_USERS_JSON must be a non-empty JSON array")

    response = requests.post(
        f"{API_BASE_URL}/auth/seed",
        headers={"Authorization": f"Bearer {SEED_AUTH_TOKEN}"},
        json={"users": seed_users},
        timeout=30,
    )
    print("/auth/seed", response.status_code, response.text)
    response.raise_for_status()


if __name__ == "__main__":
    main()
