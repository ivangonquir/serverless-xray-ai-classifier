from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_dynamodb as dynamodb,
    aws_sqs as sqs,
    aws_opensearchservice as opensearch,
    aws_iam as iam,
    aws_kms as kms,
    CfnOutput,
)
from constructs import Construct
from aws_cdk import aws_secretsmanager as secretsmanager

class StorageStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── S3: DICOM images and medical documents ───────────────────────
        # Stores DICOM CT scans and EHR documents uploaded by clinicians (FR-3.1)
        self.dicom_bucket = s3.Bucket(
            self, "LunaDicomBucket",
            bucket_name=f"luna-dicom-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            cors=[s3.CorsRule(
                allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.GET, s3.HttpMethods.HEAD],
                allowed_origins=["https://*.cloudfront.net", "http://localhost:3000"],
                allowed_headers=["*"],
                max_age=3000,
            )],
        )
        self.sqs_kms_key = kms.Key(
            self, "LunaSQSEncryptionKey",
            description="KMS Key for Luna Diagnostic SQS encryption",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY
        )
        self.sqs_kms_key.add_to_resource_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("s3.amazonaws.com")],
                actions=["kms:GenerateDataKey*", "kms:Decrypt"],
                resources=["*"],
                conditions={
                    "ArnLike": {
                        "aws:SourceArn": self.dicom_bucket.bucket_arn
                    }
                }
            )
        )
        # ── SQS: async diagnostic job queue ─────────────────────────────
        # Decouples DICOM upload from ML inference to support asynchronous
        # processing and notify clinicians only when the result is ready (FR-6.2)
        dlq = sqs.Queue(
            self, "LunaDiagnosticDLQ",
            queue_name="luna-diagnostic-dlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.sqs_kms_key
        )
        self.diagnostic_queue = sqs.Queue(
            self, "LunaDiagnosticQueue",
            queue_name="luna-diagnostic-queue",
            visibility_timeout=Duration.seconds(2160),  # 6× Lambda timeout (360s)
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.sqs_kms_key,
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=dlq,
            ),
        )

        # S3 → SQS: trigger inference pipeline when a DICOM is uploaded
        self.dicom_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(self.diagnostic_queue),
            s3.NotificationKeyFilter(prefix="uploads/"),
        )

        # ── DynamoDB: Users ──────────────────────────────────────────────
        # Clinician accounts — username, hashed password, role (FR-1.1)
        self.users_table = dynamodb.Table(
            self, "LunaUsersTable",
            partition_key=dynamodb.Attribute(
                name="userId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.users_table.add_global_secondary_index(
            index_name="UsernameIndex",
            partition_key=dynamodb.Attribute(
                name="username", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ── DynamoDB: Sessions ───────────────────────────────────────────
        # Session tokens with 24-hour TTL expiry (FR-1.1)
        self.sessions_table = dynamodb.Table(
            self, "LunaSessionsTable",
            partition_key=dynamodb.Attribute(
                name="sessionToken", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="TTL",
        )

        # ── DynamoDB: Patients ───────────────────────────────────────────
        # Core patient records: demographics + clinical risk factors (FR-4.2)
        self.patients_table = dynamodb.Table(
            self, "LunaPatientsTable",
            partition_key=dynamodb.Attribute(
                name="patientId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── DynamoDB: Diagnostic Results ─────────────────────────────────
        # One record per job: LUNA Risk Score, nodule data, heatmap path (FR-4.1-4.3)
        self.diagnostic_results_table = dynamodb.Table(
            self, "LunaDiagnosticResultsTable",
            partition_key=dynamodb.Attribute(
                name="jobId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        # GSI to fetch all results for a patient, newest first
        self.diagnostic_results_table.add_global_secondary_index(
            index_name="PatientIdIndex",
            partition_key=dynamodb.Attribute(
                name="patientId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="createdAt", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ── DynamoDB: Chat History ───────────────────────────────────────
        # Persists Virtual Assistant conversations per patient (FR-5.1 – FR-5.4)
        self.chat_history_table = dynamodb.Table(
            self, "LunaChatHistoryTable",
            partition_key=dynamodb.Attribute(
                name="patientId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── DynamoDB: Audit Log ──────────────────────────────────────────
        # Healthcare compliance — every data access/query is recorded (FR-1.2)
        self.audit_log_table = dynamodb.Table(
            self, "LunaAuditLogTable",
            partition_key=dynamodb.Attribute(
                name="logId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            deletion_protection=True,
            time_to_live_attribute="expiresAt",
        )
        self.audit_log_table.add_global_secondary_index(
            index_name="UserIdIndex",
            partition_key=dynamodb.Attribute(
                name="userId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ── DynamoDB: WebSocket Connections ─────────────────────────────
        # Tracks active WebSocket IDs so async results can be pushed (FR-6.2)
        self.connections_table = dynamodb.Table(
            self, "LunaConnectionsTable",
            partition_key=dynamodb.Attribute(
                name="connectionId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="TTL",
        )

        # DynamoDB: login attempt
        self.login_attempts_table = dynamodb.Table(
            self, "LunaLoginAttemptsTable",
            table_name=f"luna-login-attempts-{self.account}",
            partition_key=dynamodb.Attribute(
                name="ip", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="TTL",
        )

        # ── OpenSearch: RAG Knowledge Base ───────────────────────────────
        # Provides medical literature search for the Virtual Assistant (FR-5.3)
        # The ML team ingests: MIMIC-CXR radiology reports, PubMed/PMC oncology
        # papers, and Fleischner Society guidelines into the "luna-docs" index.
        # NOTE (demo): node_to_node_encryption and encryption_at_rest are
        # intentionally disabled here.  AWS requires Fine-Grained Access Control
        # when all three security options are enabled simultaneously, which adds
        # significant setup complexity.  For a production deployment re-enable
        # them and configure a master user via Secrets Manager.
        self.opensearch_domain = opensearch.Domain(
            self,
            "LunaOpenSearch",
            domain_name="luna-kb",
            version=opensearch.EngineVersion.OPENSEARCH_2_11,
            capacity=opensearch.CapacityConfig(
                data_nodes=1,
                data_node_instance_type="t3.small.search",
            ),
            ebs=opensearch.EbsOptions(
                volume_size=10,
            ),
            zone_awareness=opensearch.ZoneAwarenessConfig(
                enabled=False
            ),
            removal_policy=RemovalPolicy.DESTROY,
            enforce_https=True,
            access_policies=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AccountRootPrincipal()],
                    actions=["es:*"],
                    resources=["*"],
                )
            ],
        )

        # ── Outputs ──────────────────────────────────────────────────────
        CfnOutput(self, "DicomBucketName", value=self.dicom_bucket.bucket_name)
        CfnOutput(self, "DiagnosticQueueUrl", value=self.diagnostic_queue.queue_url)
        CfnOutput(self, "OpenSearchEndpoint", value=self.opensearch_domain.domain_endpoint)
        CfnOutput(self, "LoginAttemptsTableName", value=self.login_attempts_table.table_name)

        # ── Secret Manager ──────────────────────────────────────────────────────
        self.password_secret = secretsmanager.Secret(self, "LunaPasswordSecret",
                                                     secret_name="lunachat",
                                                     description="HMAC salt for password hashing",
                                                     generate_secret_string=secretsmanager.SecretStringGenerator(
                                                         secret_string_template='{"salt": "change-me-in-console"}',
                                                         generate_string_key="salt"
                                                     )
                                                     )
