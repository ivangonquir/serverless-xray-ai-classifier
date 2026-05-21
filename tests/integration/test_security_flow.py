import json
import os
import types
import unittest

from tests.fakes import REPO_ROOT, import_lambda_module, install_aws_stubs, install_bcrypt_stub


class SecurityFlowIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.fake_aws = install_aws_stubs()
        install_bcrypt_stub()
        os.environ.update({
            "USERS_TABLE": "users",
            "SESSIONS_TABLE": "sessions",
            "PATIENTS_TABLE": "patients",
            "DIAGNOSTIC_RESULTS_TABLE": "results",
            "AUDIT_LOG_TABLE": "audit",
            "LOGIN_ATTEMPTS_TABLE": "login-attempts",
            "DICOM_BUCKET": "dicom-bucket",
            "SECRET_NAME": "test-secret",
            "ALLOWED_ORIGINS": "http://localhost:3000",
            "AUDIT_RETENTION_SECONDS": "220752000",
            "ENABLE_SEED_ENDPOINT": "false",
            "SESSION_EXTEND_THRESHOLD": "3600",
        })
        self.context = types.SimpleNamespace(aws_request_id="req-flow")

    def test_login_authorizer_and_patient_list_share_session_and_audit(self):
        self.fake_aws.table("users").put_item(Item={
            "userId": "user-1",
            "username": "doctor",
            "passwordHash": "hashed:CorrectHorse",
            "role": "doctor",
        })
        self.fake_aws.table("patients").put_item(Item={
            "patientId": "patient-1",
            "name": "Test Patient",
            "dateOfBirth": "1970-01-01",
            "lastLunaRiskScore": 10,
        })

        auth = import_lambda_module("backend/lambdas/auth_handler/handler.py", "flow_auth_handler")
        authorizer = import_lambda_module("backend/lambdas/authorizer/handler.py", "flow_authorizer")
        patient = import_lambda_module("backend/lambdas/patient_handler/handler.py", "flow_patient_handler")

        login_response = auth.lambda_handler({
            "httpMethod": "POST",
            "path": "/auth/login",
            "headers": {"Origin": "https://d333333abcdef8.cloudfront.net"},
            "requestContext": {"requestId": "req-login", "http": {"sourceIp": "198.51.100.7"}},
            "body": json.dumps({"username": "doctor", "password": "CorrectHorse"}),
        }, self.context)
        self.assertEqual(login_response["statusCode"], 200)
        token = json.loads(login_response["body"])["sessionToken"]

        authz_response = authorizer.lambda_handler({
            "authorizationToken": f"Bearer {token}",
            "methodArn": "arn:aws:execute-api:eu-west-1:111122223333:api/prod/GET/patients",
        }, self.context)
        self.assertEqual(authz_response["principalId"], "user-1")

        list_response = patient.lambda_handler({
            "httpMethod": "GET",
            "path": "/patients",
            "headers": {"Origin": "https://d333333abcdef8.cloudfront.net"},
            "requestContext": {"authorizer": {"userId": "user-1"}},
            "pathParameters": {},
        }, self.context)
        self.assertEqual(list_response["statusCode"], 200)
        self.assertEqual(
            list_response["headers"]["Access-Control-Allow-Origin"],
            "https://d333333abcdef8.cloudfront.net",
        )

        audit_actions = [(item["action"], item["statusCode"]) for item in self.fake_aws.table("audit").items]
        self.assertIn(("LOGIN", 200), audit_actions)
        self.assertTrue(any(action.startswith("API_ACCESS") and status == 200 for action, status in audit_actions))
        self.assertIn(("LIST_PATIENTS", 200), audit_actions)
        self.assertTrue(all("expiresAt" in item for item in self.fake_aws.table("audit").items))

    def test_infrastructure_security_controls_are_declared(self):
        api_stack = (REPO_ROOT / "infrastructure/stacks/api_stack.py").read_text(encoding="utf-8")
        lambda_stack = (REPO_ROOT / "infrastructure/stacks/lambda_stack.py").read_text(encoding="utf-8")
        storage_stack = (REPO_ROOT / "infrastructure/stacks/storage_stack.py").read_text(encoding="utf-8")

        self.assertIn('add_auth_method(auth_resource.add_resource("seed")', api_stack)
        self.assertIn("allow_origins=apigw.Cors.ALL_ORIGINS", api_stack)
        self.assertIn('"ENABLE_SEED_ENDPOINT"', lambda_stack)
        self.assertIn('"ALLOWED_ORIGINS"', lambda_stack)
        self.assertIn('endswith(".cloudfront.net")', (REPO_ROOT / "backend/lambdas/auth_handler/handler.py").read_text(encoding="utf-8"))
        self.assertIn('"https://*.cloudfront.net"', storage_stack)
        self.assertIn("removal_policy=RemovalPolicy.RETAIN", storage_stack)
        self.assertIn("point_in_time_recovery=True", storage_stack)
        self.assertIn("deletion_protection=True", storage_stack)
        self.assertIn('time_to_live_attribute="expiresAt"', storage_stack)


if __name__ == "__main__":
    unittest.main()
