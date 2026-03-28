"""
WebSocket Connection Manager Lambda.

Handles $connect and $disconnect routes.
- $connect  → writes connectionId to DynamoDB with a TTL of 2 hours
- $disconnect → deletes the connectionId from DynamoDB
"""

import os
import time
import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])

TTL_SECONDS = 2 * 60 * 60  # 2 hours


def lambda_handler(event, context):
    route = event["requestContext"]["routeKey"]
    connection_id = event["requestContext"]["connectionId"]

    if route == "$connect":
        table.put_item(
            Item={
                "connectionId": connection_id,
                "ttl": int(time.time()) + TTL_SECONDS,
                "connectedAt": int(time.time()),
            }
        )
        return {"statusCode": 200, "body": "Connected"}

    if route == "$disconnect":
        table.delete_item(Key={"connectionId": connection_id})
        return {"statusCode": 200, "body": "Disconnected"}

    return {"statusCode": 400, "body": "Unhandled route"}
