from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_dynamodb as dynamodb,
    aws_s3_notifications as s3n,
)
from constructs import Construct


class StorageStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # S3 bucket for X-ray image uploads
        self.image_bucket = s3.Bucket(
            self,
            "XRayImageBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT],
                    allowed_origins=["*"],  # Restrict to CloudFront URL in production
                    allowed_headers=["*"],
                )
            ],
        )

        # Dead-letter queue for failed inference jobs
        dlq = sqs.Queue(
            self,
            "InferenceDLQ",
            retention_period=Duration.days(14),
        )

        # Main SQS queue — triggered by S3 upload events
        self.queue = sqs.Queue(
            self,
            "InferenceQueue",
            visibility_timeout=Duration.seconds(300),  # Must be >= Lambda timeout
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

        # Notify SQS when an image is uploaded to S3
        self.image_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(self.queue),
            s3.NotificationKeyFilter(suffix=".jpg"),
        )
        self.image_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(self.queue),
            s3.NotificationKeyFilter(suffix=".png"),
        )

        # DynamoDB: active WebSocket connections
        self.connections_table = dynamodb.Table(
            self,
            "ConnectionsTable",
            partition_key=dynamodb.Attribute(
                name="connectionId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",  # Auto-expire stale connections
        )

        # DynamoDB: diagnostic results history
        self.results_table = dynamodb.Table(
            self,
            "ResultsTable",
            partition_key=dynamodb.Attribute(
                name="jobId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
