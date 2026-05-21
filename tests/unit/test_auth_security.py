import json
import os
import types
import unittest

from tests.fakes import import_lambda_module, install_aws_stubs, install_bcrypt_stub


class AuthSecurityUnitTest(unittest.TestCase):
    def setUp(self):
        self.fake_aws = install_aws_stubs()
        install_bcrypt_stub()
        os.environ.update({
            "USERS_TABLE": "users",
            "SESSIONS_TABLE": "sessions",
            "AUDIT_LOG_TABLE": "audit",
            "LOGIN_ATTEMPTS_TABLE": "login-attempts",
            "SECRET_NAME": "test-secret",
            "ALLOWED_ORIGINS": "http://localhost:3000",
            "AUDIT_RETENTION_SECONDS": "220752000",
            "ENABLE_SEED_ENDPOINT": "false",
        })
        self.auth = import_lambda_module("backend/lambdas/auth_handler/handler.py", "unit_auth_handler")
        self.context = types.SimpleNamespace(aws_request_id="req-1")

    def test_seed_endpoint_is_disabled_and_audited(self):
        response = self.auth.lambda_handler({
            "httpMethod": "POST",
            "path": "/auth/seed",
            "headers": {"Origin": "https://d111111abcdef8.cloudfront.net"},
            "requestContext": {"requestId": "req-1", "authorizer": {"userId": "admin-user"}},
            "body": json.dumps({"users": [{"username": "doctor", "password": "secret"}]}),
        }, self.context)

        self.assertEqual(response["statusCode"], 403)
        self.assertEqual(
            response["headers"]["Access-Control-Allow-Origin"],
            "https://d111111abcdef8.cloudfront.net",
        )
        self.assertEqual(self.fake_aws.table("users").items, [])
        audit = self.fake_aws.table("audit").items[-1]
        self.assertEqual(audit["action"], "SEED_BLOCKED")
        self.assertEqual(audit["statusCode"], 403)
        self.assertIn("expiresAt", audit)

    def test_disallowed_origin_gets_no_allow_origin_header_and_failure_audit(self):
        response = self.auth.lambda_handler({
            "httpMethod": "POST",
            "path": "/auth/login",
            "headers": {"Origin": "https://evil.example"},
            "requestContext": {"requestId": "req-2", "http": {"sourceIp": "203.0.113.1"}},
            "body": "{}",
        }, self.context)

        self.assertEqual(response["statusCode"], 400)
        self.assertNotIn("Access-Control-Allow-Origin", response["headers"])
        audit = self.fake_aws.table("audit").items[-1]
        self.assertEqual(audit["action"], "LOGIN_FAILED")
        self.assertEqual(audit["statusCode"], 400)

    def test_rest_api_source_ip_is_used_for_login_attempt_tracking(self):
        response = self.auth.lambda_handler({
            "httpMethod": "POST",
            "path": "/auth/login",
            "headers": {"Origin": "https://d222222abcdef8.cloudfront.net"},
            "requestContext": {"requestId": "req-3", "identity": {"sourceIp": "192.0.2.5"}},
            "body": json.dumps({"username": "missing", "password": "wrong"}),
        }, self.context)

        self.assertEqual(response["statusCode"], 401)
        attempts = self.fake_aws.table("login-attempts").items
        self.assertEqual(attempts[0]["ip"], "192.0.2.5")


if __name__ == "__main__":
    unittest.main()
