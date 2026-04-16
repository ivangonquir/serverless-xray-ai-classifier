"""
WebSocket Connection Manager

Handles the $connect and $disconnect routes of the LUNA WebSocket API.

$connect    → Stores the connectionId in ConnectionsTable with a 2-hour TTL.
              Optionally associates the connection with a userId extracted
              from query string parameters (set by the frontend on connect).
$disconnect → Removes the record so stale IDs are never used for result push.

The InferenceWorker Lambda reads ConnectionsTable to know which active
WebSocket connections to push diagnostic results to (FR-6.2).
"""

import os
import time
from datetime import datetime, timezone

import boto3

dynamodb = boto3.resource("dynamodb")
connections_table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])

TTL_SECONDS = 2 * 60 * 60  # 2 hours


def lambda_handler(event, context):
    route = event["requestContext"]["routeKey"]
    connection_id = event["requestContext"]["connectionId"]

    if route == "$connect":
        return _on_connect(event, connection_id)
    if route == "$disconnect":
        return _on_disconnect(connection_id)

    return {"statusCode": 400, "body": "Unhandled route"}


def _on_connect(event: dict, connection_id: str):
    # The frontend may pass userId and patientId as query string params
    # so the InferenceWorker can route results without a separate lookup
    query_params = event.get("queryStringParameters") or {}
    user_id = query_params.get("userId", "")
    patient_id = query_params.get("patientId", "")

    connections_table.put_item(Item={
        "connectionId": connection_id,
        "userId": user_id,
        "patientId": patient_id,
        "connectedAt": datetime.now(timezone.utc).isoformat(),
        "TTL": int(time.time()) + TTL_SECONDS,
    })
    return {"statusCode": 200, "body": "Connected"}


def _on_disconnect(connection_id: str):
    connections_table.delete_item(Key={"connectionId": connection_id})
    return {"statusCode": 200, "body": "Disconnected"}
