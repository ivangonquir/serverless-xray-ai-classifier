import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeCondition:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class FakeKey:
    def __init__(self, name):
        self.name = name

    def eq(self, value):
        return FakeCondition(self.name, value)


class FakeAttr(FakeKey):
    pass


class FakeTable:
    def __init__(self, name):
        self.name = name
        self.items = []

    def put_item(self, Item):
        self.items.append(dict(Item))
        return {}

    def get_item(self, Key):
        for item in self.items:
            if all(item.get(key) == value for key, value in Key.items()):
                return {"Item": item}
        return {}

    def delete_item(self, Key):
        self.items = [
            item for item in self.items
            if not all(item.get(key) == value for key, value in Key.items())
        ]
        return {}

    def update_item(self, Key, **kwargs):
        item = self.get_item(Key).get("Item")
        if item is None:
            item = dict(Key)
            self.items.append(item)
        values = kwargs.get("ExpressionAttributeValues", {})
        expression = kwargs.get("UpdateExpression", "")
        if "TTL = :new_ttl" in expression:
            item["TTL"] = values[":new_ttl"]
        if "#s = :s" in expression:
            item["status"] = values[":s"]
        if "updatedAt = :ts" in expression:
            item["updatedAt"] = values[":ts"]
        if "ADD attempts :inc" in expression:
            item["attempts"] = item.get("attempts", 0) + values.get(":inc", 1)
            item["TTL"] = values.get(":ttl", item.get("TTL"))
            item["lockoutUntil"] = item.get("lockoutUntil", values.get(":zero", 0))
        return {}

    def query(self, **kwargs):
        condition = kwargs.get("KeyConditionExpression")
        items = list(self.items)
        if isinstance(condition, FakeCondition):
            items = [item for item in items if item.get(condition.name) == condition.value]
        elif isinstance(condition, str) and "patientId" in condition:
            value = kwargs.get("ExpressionAttributeValues", {}).get(":pid")
            items = [item for item in items if item.get("patientId") == value]
        if kwargs.get("ScanIndexForward") is False:
            items = sorted(items, key=lambda item: item.get("createdAt") or item.get("timestamp") or "", reverse=True)
        limit = kwargs.get("Limit")
        if limit:
            items = items[:limit]
        return {"Items": items}

    def scan(self, **kwargs):
        return {"Items": list(self.items)}


class FakeDynamoResource:
    def __init__(self):
        self.tables = {}

    def Table(self, name):
        self.tables.setdefault(name, FakeTable(name))
        return self.tables[name]


class FakeSecretClient:
    def get_secret_value(self, SecretId):
        return {"SecretString": "test-secret"}


class FakeS3Client:
    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://signed.example/{operation}/{Params['Key']}?expires={ExpiresIn}"


class FakeSession:
    def __init__(self, fake_aws):
        self.fake_aws = fake_aws

    def client(self, service_name, region_name=None):
        return self.fake_aws.client(service_name, region_name=region_name)

    def get_credentials(self):
        return types.SimpleNamespace(get_frozen_credentials=lambda: object())


class FakeAws:
    def __init__(self):
        self.dynamodb = FakeDynamoResource()
        self.sqs_messages = []

    def resource(self, service_name, **kwargs):
        if service_name != "dynamodb":
            raise AssertionError(f"Unexpected resource: {service_name}")
        return self.dynamodb

    def client(self, service_name, **kwargs):
        if service_name == "secretsmanager":
            return FakeSecretClient()
        if service_name == "s3":
            return FakeS3Client()
        if service_name == "sqs":
            return types.SimpleNamespace(send_message=lambda **message: self.sqs_messages.append(message))
        return types.SimpleNamespace()

    def table(self, name):
        return self.dynamodb.Table(name)


def install_aws_stubs():
    fake_aws = FakeAws()

    boto3 = types.ModuleType("boto3")
    boto3.resource = fake_aws.resource
    boto3.client = fake_aws.client
    boto3.session = types.SimpleNamespace(Session=lambda: FakeSession(fake_aws))

    conditions = types.ModuleType("boto3.dynamodb.conditions")
    conditions.Key = FakeKey
    conditions.Attr = FakeAttr

    dynamodb = types.ModuleType("boto3.dynamodb")
    dynamodb.conditions = conditions

    botocore_exceptions = types.ModuleType("botocore.exceptions")
    botocore_exceptions.ClientError = type("ClientError", (Exception,), {})
    botocore = types.ModuleType("botocore")
    botocore.exceptions = botocore_exceptions

    sys.modules["boto3"] = boto3
    sys.modules["boto3.dynamodb"] = dynamodb
    sys.modules["boto3.dynamodb.conditions"] = conditions
    sys.modules["botocore"] = botocore
    sys.modules["botocore.exceptions"] = botocore_exceptions
    return fake_aws


def install_bcrypt_stub():
    bcrypt = types.ModuleType("bcrypt")
    bcrypt.gensalt = lambda: b"salt"
    bcrypt.hashpw = lambda password, salt: b"hashed:" + password
    bcrypt.checkpw = lambda password, stored_hash: stored_hash == b"hashed:" + password
    sys.modules["bcrypt"] = bcrypt


def import_lambda_module(relative_path, module_name):
    path = REPO_ROOT / relative_path
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
