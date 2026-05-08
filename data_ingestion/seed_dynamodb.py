import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("NEXT_PUBLIC_API_URL")

endpoints = [
    "/auth/seed",
    #"/auth/another",
]

for endpoint in endpoints:
    url = f"{API_BASE_URL}{endpoint}"
    r = requests.post(url)
    print(endpoint, r.status_code)

print("✅ DynamoDB Tables Initialized")