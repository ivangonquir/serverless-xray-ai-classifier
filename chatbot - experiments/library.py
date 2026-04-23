import boto3
import os
import time
from dotenv import load_dotenv
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
TABLE_NAME = os.getenv("TABLE_NAME")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

def get_or_create_table():
    try:
        table = dynamodb.Table(TABLE_NAME)
        table.load()
        return table

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print("Creating DynamoDB table...")

            table = dynamodb.create_table(
                TableName=TABLE_NAME,
                KeySchema=[
                    {"AttributeName": "patient_id", "KeyType": "HASH"},
                    {"AttributeName": "timestamp", "KeyType": "RANGE"}
                ],
                AttributeDefinitions=[
                    {"AttributeName": "patient_id", "AttributeType": "S"},
                    {"AttributeName": "timestamp", "AttributeType": "N"}
                ],
                BillingMode="PAY_PER_REQUEST"
            )

            table.wait_until_exists()
            return table
        else:
            raise


table = get_or_create_table()

MAX_MESSAGES = 200


def save_message(patient_id, role, content):
    timestamp = int(time.time() * 1000)

    table.put_item(
        Item={
            "patient_id": patient_id,
            "timestamp": timestamp,
            "role": role,
            "content": content
        }
    )

    enforce_limit(patient_id)


def enforce_limit(patient_id):
    response = table.query(
        KeyConditionExpression=Key("patient_id").eq(patient_id),
        ScanIndexForward=True
    )

    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=Key("patient_id").eq(patient_id),
            ExclusiveStartKey=response["LastEvaluatedKey"],
            ScanIndexForward=True
        )
        items.extend(response.get("Items", []))

    if len(items) > MAX_MESSAGES:
        excess = len(items) - MAX_MESSAGES
        to_delete = items[:excess]

        with table.batch_writer() as batch:
            for item in to_delete:
                batch.delete_item(
                    Key={
                        "patient_id": item["patient_id"],
                        "timestamp": item["timestamp"]
                    }
                )


def load_history(patient_id, limit=6):
    response = table.query(
        KeyConditionExpression=Key("patient_id").eq(patient_id),
        ScanIndexForward=True
    )

    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=Key("patient_id").eq(patient_id),
            ExclusiveStartKey=response["LastEvaluatedKey"],
            ScanIndexForward=True
        )
        items.extend(response.get("Items", []))

    items = items[-limit:]

    return [
        {"role": i["role"], "content": i["content"]}
        for i in items
    ]