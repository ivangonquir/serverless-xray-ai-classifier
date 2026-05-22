# LUNA — Serverless Lung Cancer AI Platform
### Final Project Report · Cloud Computing & Big Data Architecture
**MSc in Data Science — Cloud Computing & Big Data Architecture**
> *Submitted: May 2026*

---

## Table of Contents

1. [Executive Summary & Final Project Scope](#1-executive-summary--final-project-scope)
2. [Scope Evolution — First Draft vs. Final Delivery](#2-scope-evolution--first-draft-vs-final-delivery)
3. [Architecture & Implementation Design](#3-architecture--implementation-design)
4. [The Twelve-Factor App Methodology](#4-the-twelve-factor-app-methodology)
5. [Development Methodology & Environment](#5-development-methodology--environment)
6. [Technical Challenges & Solutions](#6-technical-challenges--solutions)
7. [Cloud Services & Resource Justification](#7-cloud-services--resource-justification)
8. [Resource Management & Time Tracking Retrospective](#8-resource-management--time-tracking-retrospective)

---

## 1. Executive Summary & Final Project Scope

### 1.1 What LUNA Does

LUNA (**L**ung **U**nit **N**eural **A**ssistant) is a fully serverless, cloud-native clinical decision support system purpose-built for lung cancer screening and pulmonary nodule analysis. Designed to operate as a real-time AI platform deployed exclusively on Amazon Web Services (AWS), LUNA enables radiologists and pulmonologists to dramatically accelerate their diagnostic workflow without the overhead of managing any underlying server infrastructure.

At its core, the platform integrates four distinct AI-driven capabilities into a single, unified clinician-facing interface:

1. **Medical Imaging AI** — A multimodal vision-language model (VLM), CheXOne, deployed on Amazon SageMaker, analyses chest X-ray images (DICOM/PNG/JPG format) and returns a structured LUNA Risk Score (0–100), pathology predictions for a range of thoracic conditions, and spatial bounding-box annotations identifying the precise location of suspected nodules on the X-ray.

2. **Retrieval-Augmented Generation (RAG) Assistant** — An AI chatbot powered by Anthropic Claude (via Amazon Bedrock) and backed by an Amazon OpenSearch vector store. The assistant allows clinicians to pose natural-language clinical questions and receive evidence-backed answers drawn from indexed medical literature, alongside full patient context retrieved from DynamoDB.

3. **Patient Management Layer** — A DynamoDB-backed Electronic Health Record (EHR) integration that stores per-patient demographics, smoking history, pulmonary comorbidities, and links to all associated diagnostic results and X-ray imagery.

4. **Real-Time Notification Pipeline** — An event-driven asynchronous inference pipeline that ingests DICOM uploads via Amazon S3, routes jobs through Amazon SQS, processes them through a dedicated Lambda inference worker, and pushes completed diagnostic results back to the connected browser session via an Amazon API Gateway WebSocket connection — all without polling.

The application is delivered through a Next.js static front-end, built using React and Tailwind CSS, hosted on Amazon S3 and served globally through Amazon CloudFront. The entire backend is constructed as a set of stateless, single-purpose AWS Lambda functions exposed through API Gateway REST and WebSocket endpoints. Infrastructure provisioning is fully automated with AWS CDK (Cloud Development Kit) using Python, enabling repeatable, version-controlled deployments across environments in minutes.

### 1.2 Core AWS Cloud-Native Features

The following cloud-native capabilities are central to the application's architecture and directly enable its real-time processing characteristics:

- **Event-driven execution**: S3 object creation events trigger SQS messages, which in turn invoke Lambda functions. No server needs to be running to await work.
- **Managed serverless compute**: Lambda functions scale from zero to thousands of concurrent executions in response to demand, with no capacity planning required.
- **Asynchronous decoupling via SQS**: The upload and inference phases are completely decoupled. A clinician receives a near-instant HTTP 202 Accepted response and is notified asynchronously via WebSocket when the result is ready.
- **Push-based real-time delivery**: API Gateway WebSocket connections allow the backend to push diagnostic results to the browser the moment they become available, eliminating the need for client-side polling.
- **Managed AI inference**: Amazon SageMaker hosts the CheXOne multimodal model on managed GPU infrastructure. Amazon Bedrock provides on-demand access to Claude without any model hosting responsibility.
- **Vector search for RAG**: Amazon OpenSearch Service provides K-NN vector similarity search, enabling semantic retrieval of medical literature in milliseconds.
- **Infrastructure as Code**: Every AWS resource is defined in Python CDK stacks, ensuring environments are perfectly reproducible and all changes are peer-reviewed through source control.

---

<!-- FIGURE 1 — Architecture Diagram -->
<!-- Insert here a high-level architectural diagram showing all AWS services and their interconnections.
     Recommended: a layered diagram from Browser → CloudFront → API Gateway (REST + WebSocket) →
     Lambda functions → Storage layer (S3, DynamoDB, SQS, OpenSearch) → AI layer (SageMaker, Bedrock).
     Save as: report/img/architecture_diagram.png
     Caption: Figure 1. LUNA System Architecture — End-to-end serverless AWS deployment. -->

![Figure 1 — LUNA System Architecture](./report/img/architecture_diagram.png)
*Figure 1. LUNA System Architecture — End-to-end serverless AWS deployment across six CDK stacks.*

---

## 2. Scope Evolution — First Draft vs. Final Delivery

### 2.1 Initial Project Proposal

The initial proposal centred on a straightforward serverless medical image classifier: a user would upload a chest X-ray, a SageMaker endpoint would classify it, and the result would be returned via a REST API response. The scope was intentionally narrow to establish a working cloud deployment baseline and to validate the feasibility of running GPU-based ML inference in a serverless fashion on AWS.

The preliminary design included:
- A single S3 bucket for image uploads
- A single Lambda function to invoke a SageMaker endpoint
- A minimal REST API (API Gateway)
- A basic HTML interface for file upload and result display
- DynamoDB for persisting classification results

### 2.2 Scope Expansions Successfully Delivered

During the development cycle, the scope was substantially expanded as the team identified opportunities to build a genuinely production-quality clinical platform rather than a demonstration prototype. The following features were added beyond the initial brief:

| Feature | Justification for Expansion |
|---|---|
| **WebSocket real-time push notifications** | SageMaker async inference can take 30–90 seconds. Polling was determined to be wasteful; WebSockets allow zero-latency push delivery. |
| **Multi-table DynamoDB data model** | Separating Users, Sessions, Patients, Diagnostic Results, Chat History, Audit Logs, and WebSocket Connections into dedicated tables enabled independent scaling, clear ownership, and fine-grained IAM policies. |
| **RAG pipeline (OpenSearch + Bedrock)** | Clinicians need evidence-based explanations, not just numerical scores. RAG grounds LLM responses in indexed medical literature, dramatically reducing hallucination risk. |
| **Audit logging with 7-year retention** | Healthcare data regulations (e.g., HIPAA-adjacent compliance posture) require an immutable audit trail of every data access event. |
| **Lambda Authorizer (custom authentication)** | Rather than delegating authentication to Amazon Cognito, the team implemented a custom session-token authorizer to maintain full control over the authentication and session lifecycle. |
| **CDK multi-stack IaC deployment** | The infrastructure was split into six logically cohesive CDK stacks (`StorageStack`, `WebSocketStack`, `SageMakerStack`, `LambdaStack`, `ApiStack`, `FrontendStack`) to enforce separation of concerns and allow independent redeployment of each layer. |
| **Pre-signed S3 upload URLs** | Rather than routing large DICOM files through API Gateway (which has a 10 MB payload limit and incurs transfer costs), the upload handler generates short-lived pre-signed S3 PUT URLs, allowing the browser to upload files directly to S3. |
| **Dead-Letter Queue (DLQ)** | The SQS diagnostic queue is backed by a DLQ with a 14-day retention period, ensuring that failed inference jobs are never silently dropped. |
| **KMS-encrypted SQS queue** | A customer-managed KMS key was provisioned to encrypt all messages in the diagnostic queue at rest, aligned with security best practices for sensitive medical data. |
| **CloudFront CDN distribution** | The Next.js static front-end is served through CloudFront to provide global edge caching, HTTPS enforcement, and Origin Access Control (OAC) for the S3 bucket. |

### 2.3 Features Not Implemented — Justifications

The following items were considered during design but were not delivered in the final submission due to time constraints or deliberate technical trade-offs:

| Feature | Reason Not Implemented |
|---|---|
| **Live SageMaker real-time endpoint** | Training and hosting a GPU-based multimodal model incurs significant AWS costs ($1.50–$7.00/hour for `ml.g4dn.xlarge` or larger). The team implemented a bypass mechanism using pre-computed VLM outputs stored in S3, which simulates the SageMaker response faithfully and allows full end-to-end demonstration without incurring continuous GPU costs. |
| **Fine-Grained Access Control (FGAC) on OpenSearch** | The OpenSearch domain was configured with an IP-based access policy rather than FGAC with a master user stored in Secrets Manager. This was a deliberate simplification to accelerate deployment velocity, with the security trade-off documented explicitly. |
| **Multi-tenant role separation (admin vs. doctor)** | The DynamoDB Users table includes a `role` attribute, and the seed script supports role assignment. However, the API authorizer does not yet enforce role-based access control (RBAC) at the route level. |
| **Automated CI/CD pipeline (CodePipeline/GitHub Actions)** | Deployments are performed manually via `cdk deploy --all`. A full CI/CD pipeline was designed conceptually but not implemented within the project timeline. |
| **DICOM viewer in the browser** | The platform renders DICOM files as PNG images (original and annotated). A full in-browser DICOM viewer (e.g., Cornerstone.js) was considered but deprioritised in favour of the AI pipeline and RAG assistant. |

---

## 3. Architecture & Implementation Design

### 3.1 System Overview

LUNA's architecture is decomposed into six independently deployable AWS CDK stacks that collectively form a layered, event-driven system. Each stack encapsulates a cohesive set of resources and exposes only the necessary outputs to downstream stacks, enforcing strict dependency boundaries.

```
Browser (CloudFront / Next.js)
    │
    ├── REST (API Gateway HTTP API)
    │       ├── POST /auth/login             → auth_handler Lambda
    │       ├── POST /auth/logout            → auth_handler Lambda
    │       ├── GET  /patients               → patient_handler Lambda
    │       ├── GET  /patients/{id}          → patient_handler Lambda
    │       ├── POST /patients/{id}/upload   → upload_handler Lambda → S3 Pre-signed PUT URL
    │       ├── POST /patients/{id}/diagnose → diagnostic_handler Lambda → SQS
    │       └── POST /assistant/query        → assistant_handler Lambda (RAG + Bedrock)
    │
    └── WebSocket (API Gateway WebSocket API)
            └── $connect / $disconnect       → connection_manager Lambda
                                                      ↑
S3 PutObject Event → SQS → inference_worker Lambda ───┘
                                ↓
            reference_outputs/{id}/results.json  (pre-computed bypass)
            OR SageMaker InvokeEndpointAsync     (live inference path)
```

---

<!-- FIGURE 2 — Application Workflow Diagram -->
<!-- Insert here a sequence diagram or swimlane diagram illustrating the end-to-end workflow:
     1. Clinician logs in → auth_handler validates → session token returned
     2. Patient list loaded → patient_handler queries DynamoDB → sorted by risk score
     3. Clinician uploads DICOM → upload_handler generates pre-signed URL → browser PUTs to S3
     4. S3 event → SQS → inference_worker → SageMaker (or bypass) → DynamoDB write → WebSocket push
     5. Clinician asks question → assistant_handler → OpenSearch KNN → Bedrock Claude → response
     Save as: report/img/workflow_diagram.png
     Caption: Figure 2. LUNA Application Workflow — End-to-end request/event flow from browser to AI services. -->

![Figure 2 — Application Workflow](./report/img/workflow_diagram.png)
*Figure 2. LUNA Application Workflow — Sequence of events from login through diagnostic result delivery.*

---

### 3.2 CDK Stack Decomposition

#### `LunaStorageStack`
The foundational layer. Provisions all persistent storage resources:
- **S3 DICOM Bucket**: Encrypted (`S3_MANAGED`), fully private (blocked public access), with CORS configured to permit direct browser uploads from CloudFront and localhost. An S3 event notification on the `uploads/` prefix publishes to the SQS queue.
- **SQS Diagnostic Queue**: KMS-encrypted with a customer-managed key, 6-minute visibility timeout (six times the Lambda timeout), and a Dead-Letter Queue with 14-day retention for failed jobs.
- **DynamoDB Tables (×7)**: Users, Sessions, Patients, DiagnosticResults, ChatHistory, AuditLog, and Connections. All use `PAY_PER_REQUEST` billing mode (on-demand) for cost-optimal elasticity. The AuditLog table has deletion protection enabled and a `RETAIN` removal policy, ensuring it survives CDK stack destruction.
- **AWS Secrets Manager**: Stores the bcrypt pepper secret used to hash clinician passwords, ensuring the secret is never present in environment variables or source code.

#### `LunaWebSocketStack`
Provisions the API Gateway WebSocket API with `$connect` and `$disconnect` routes wired to the `connection_manager` Lambda. The management endpoint URL is passed as an output to `LambdaStack` so the `inference_worker` can post messages to connected clients.

#### `LunaSageMakerStack`
Defines the SageMaker model and endpoint configuration for the CheXOne VLM, along with the necessary IAM execution role. In the current delivery, the endpoint is provisioned in an offline state to avoid GPU costs during the demonstration period; the inference worker falls back to pre-computed results stored in S3.

#### `LunaLambdaStack`
The central orchestration layer. Creates and configures all eight Lambda functions, wiring each with:
- Precise IAM grants (following least-privilege, e.g. `grant_read_write_data`, `grant_put`) rather than broad `*` action policies.
- Environment variables referencing stack outputs (table names, bucket names, queue URLs, endpoint ARNs).
- Event source mappings (SQS → `inference_worker` with `batch_size=1` to ensure sequential job processing and predictable billing).

#### `LunaApiStack`
Constructs the API Gateway HTTP API, mounts routes, and attaches the custom Lambda Authorizer. All routes (except `/auth/login`) are protected by the authorizer, which validates session tokens against the DynamoDB Sessions table with a 24-hour TTL.

#### `LunaFrontendStack`
Provisions the S3 frontend bucket (private, versioned), the CloudFront distribution with Origin Access Control, and outputs the distribution URL. The Next.js application is built statically (`next export`) and synchronised to S3 via the AWS CLI.

### 3.3 Architectural Pillars

#### Design for Failure

LUNA eliminates single points of failure at every layer:

- **Stateless Lambda functions**: No Lambda function stores state in memory between invocations. All state is externalised to DynamoDB or S3. If a Lambda container is terminated mid-execution, the next invocation starts cleanly.
- **SQS with DLQ**: If the `inference_worker` Lambda fails three times processing a message (e.g., due to a transient SageMaker error), the message is automatically moved to the Dead-Letter Queue. No job is silently lost. Operators can inspect and reprocess DLQ messages.
- **Session TTL via DynamoDB**: Session tokens expire automatically via DynamoDB's native TTL mechanism. There is no session cleanup daemon that could fail.
- **CloudFront with S3 origin**: The frontend is served from CloudFront's global edge network. If a single edge location fails, requests are automatically routed to the next nearest healthy location.
- **API Gateway SLA**: API Gateway provides a managed 99.95% availability SLA. The team does not need to manage load balancers, health checks, or auto-scaling groups for the API layer.

#### Security

Security is enforced at multiple layers following the principle of defence in depth:

- **Authentication**: Clinician passwords are hashed with bcrypt using a pepper secret retrieved from AWS Secrets Manager at runtime. Raw passwords never appear in logs, environment variables, or DynamoDB.
- **Session management**: Login issues an opaque session token stored in DynamoDB with a 24-hour TTL. The custom Lambda Authorizer validates every protected API call against this token.
- **Rate limiting & brute-force protection**: A dedicated `login_attempts` DynamoDB table tracks failed login attempts. Accounts are temporarily locked after repeated failures.
- **Least-privilege IAM**: Each Lambda function's execution role is granted only the specific DynamoDB actions (`GetItem`, `PutItem`, `Query`) and S3 actions (`PutObject`, `GetObject`) it actually requires. No function has `iam:*` or `s3:*` wildcard policies.
- **S3 encryption**: The DICOM bucket uses S3-Managed Encryption (SSE-S3). All objects are encrypted at rest.
- **SQS KMS encryption**: Diagnostic queue messages are encrypted at rest using a customer-managed KMS key with automatic key rotation enabled.
- **Pre-signed URLs with short TTL**: S3 upload URLs are valid for a limited time window, ensuring that a leaked URL cannot be used for indefinite uploads.
- **CORS enforcement**: The S3 bucket and API Gateway both enforce strict CORS policies, allowing requests only from the CloudFront distribution URL and `localhost:3000` during development.
- **Audit logging with 7-year retention**: Every patient data access, login event, and diagnostic query is written to the immutable AuditLog DynamoDB table. The table has deletion protection and a `RETAIN` CloudFormation policy.

#### Elasticity

The serverless architecture provides automatic, zero-configuration elasticity:

- **Lambda concurrency scaling**: AWS Lambda scales horizontally by provisioning additional concurrent execution environments within milliseconds. During a high-traffic triage event (e.g., multiple clinicians simultaneously querying patient lists), Lambda automatically handles concurrent requests without any configuration changes.
- **DynamoDB on-demand mode**: All DynamoDB tables use `PAY_PER_REQUEST` billing. The read/write capacity scales instantly to any traffic level without provisioned capacity planning or auto-scaling policies.
- **SQS decoupling for burst absorption**: When DICOM uploads arrive faster than the inference worker can process them, SQS buffers the excess. The visibility timeout and `batch_size=1` configuration ensure ordered, predictable processing.
- **OpenSearch scaling**: The OpenSearch domain is provisioned with a dedicated master node and data node configuration, supporting seamless horizontal scaling of the vector index as the medical literature corpus grows.
- **CloudFront edge caching**: Static frontend assets (JS bundles, CSS, images) are cached at CloudFront edge locations globally, meaning frontend traffic does not scale Lambda or API Gateway — the CDN absorbs it entirely.

#### Decoupling

LUNA's components are designed to operate independently, with well-defined interfaces between them:

- **S3 → SQS → Lambda (event bridge)**: The upload pipeline is a chain of loosely coupled events. The `upload_handler` Lambda does not know — and does not need to know — that an `inference_worker` exists. It simply generates a pre-signed URL. The S3 event notification is the integration point.
- **WebSocket as notification bus**: The `inference_worker` does not return results through a synchronous HTTP response. Instead, it writes results to DynamoDB and then independently calls the WebSocket Management API to push a notification to any connected browser sessions associated with the patient. This decouples the inference timeline from the request/response cycle.
- **Assistant handler independence**: The RAG assistant is a completely independent Lambda with no shared code or runtime dependencies with the imaging pipeline. Its only integration points are DynamoDB (to read patient context) and OpenSearch (to retrieve document embeddings). It can be updated, scaled, or replaced without affecting any other system component.
- **Multi-stack CDK architecture**: Each CDK stack can be deployed, updated, or rolled back independently. `LunaStorageStack` can be redeployed to change table configurations without touching `LunaApiStack` or `LunaFrontendStack`.

#### Performance Optimisation

- **Pre-signed URL upload bypass**: By having the browser upload DICOM files directly to S3 via a pre-signed URL, API Gateway is bypassed for large file transfers. This eliminates a 10 MB API Gateway payload constraint and reduces end-to-end upload latency.
- **KNN vector search in OpenSearch**: Semantic retrieval uses k-nearest-neighbour (KNN) search over Amazon Titan text embeddings. This provides sub-second retrieval of the top-K most relevant medical documents without full-text scan overhead.
- **Lambda memory tuning**: The `inference_worker` is provisioned with 1,024 MB of memory (vs. the 128 MB default), directly increasing CPU allocation proportionally and reducing DICOM processing time. The `assistant_handler` and `auth_handler` use 256 MB, calibrated against their computational profiles.
- **DynamoDB GSI for sorted queries**: The `DiagnosticResults` table includes a Global Secondary Index (`PatientIdIndex`) with a sort key on `createdAt`, enabling O(1) retrieval of the most recent diagnostic result for a patient without a full table scan.
- **CloudFront caching headers**: The Next.js build outputs static assets with content-hashed filenames, allowing CloudFront to apply long-lived cache headers (31536000 seconds / 1 year) for maximum cache hit ratios.

#### Observability

- **AWS CloudWatch Logs**: Every Lambda function emits structured logs to CloudWatch Logs Groups automatically. Log groups are named by function and environment, enabling per-function log inspection, filtering, and alarming.
- **Structured logging**: Lambda handlers use Python's `json` module to emit structured key-value log lines (e.g., `{"event": "auth_success", "userId": "...", "timestamp": "..."}`) rather than unstructured strings, making log analysis and querying in CloudWatch Insights significantly more efficient.
- **Audit log trail**: The `AuditLogTable` in DynamoDB provides an application-level audit trail supplementing CloudWatch's infrastructure-level logs. Every authenticated API call writes a timestamped audit record including the calling user ID, action type, affected resource, and result.
- **SQS DLQ monitoring**: The Dead-Letter Queue can be monitored via CloudWatch Metrics for `ApproximateNumberOfMessagesVisible`, enabling automated alerting when inference jobs are failing.
- **Lambda X-Ray tracing** *(architecture-ready)*: The CDK stack structure supports enabling AWS X-Ray active tracing on all Lambda functions with a single configuration change, providing distributed request tracing across the entire backend without code changes.

---

## 4. The Twelve-Factor App Methodology

The Twelve-Factor App methodology, originally articulated by Heroku engineers, defines a set of design principles for building software-as-a-service applications that are portable, scalable, and maintainable. LUNA's architecture was evaluated against each factor during design, and the vast majority are satisfied natively by the AWS serverless model. The following subsections address each factor individually.

### Factor I — Codebase: One Codebase, One Repository, Many Deploys

**Status: Fully Satisfied.**

LUNA maintains a single Git repository (`ivangonquir/serverless-xray-ai-classifier`) that contains the entire application — infrastructure code (CDK stacks), backend Lambda handlers, data ingestion scripts, the frontend Next.js application, the ML pipeline, and the test suite. There is exactly one codebase, deployed across multiple environments (local development, AWS staging, AWS production) by varying CDK context parameters and environment variable files (`.env`, `.env.local`). This satisfies Factor I exactly: one codebase, multiple deploys, zero code divergence between environments.

### Factor II — Dependencies: Explicitly Declare and Isolate Dependencies

**Status: Fully Satisfied.**

Every component declares its dependencies explicitly and in isolation:
- Infrastructure: `infrastructure/requirements.txt` (CDK, constructs)
- Backend Lambdas: Each Lambda using `aws_lambda_python_alpha.PythonFunction` has its own `requirements.txt` at the handler level, which CDK packages into the Lambda deployment ZIP independently.
- Frontend: `frontend/package.json` with exact version pinning via `package-lock.json`.
- ML pipeline: `ml/chexone_test_production/requirements.txt`.

No Lambda function assumes any globally installed library. Each function's execution environment is hermetically sealed by CDK's packaging.

### Factor III — Config: Store Config in the Environment

**Status: Fully Satisfied.**

Zero configuration values are hardcoded in source code. All environment-specific values (table names, bucket names, queue URLs, SageMaker endpoint names, Bedrock model IDs, allowed origins) are injected as Lambda environment variables by CDK at deploy time, resolved from CDK stack outputs. The frontend reads `NEXT_PUBLIC_*` environment variables at build time. Secrets (the bcrypt pepper) are stored in AWS Secrets Manager and fetched at Lambda cold-start runtime — never in environment variables or source control. A `.env` file at the repository root documents the expected variables for local development, but is excluded from version control via `.gitignore`.

### Factor IV — Backing Services: Treat Backing Services as Attached Resources

**Status: Fully Satisfied.**

Every external service LUNA consumes — DynamoDB tables, S3 buckets, SQS queues, OpenSearch domains, SageMaker endpoints, Bedrock APIs — is treated as an attached resource referenced by its ARN, URL, or name injected via environment variable. No Lambda function hardcodes an endpoint URL. Swapping the OpenSearch domain (e.g., from `eu-west-1` to `us-east-1`) requires only an environment variable update and a CDK redeploy, with zero code changes.

### Factor V — Build, Release, Run: Strictly Separate Build and Run Stages

**Status: Fully Satisfied.**

LUNA has clearly distinct build and release stages:
- **Build**: `npm run build` produces a static Next.js export; CDK synthesises CloudFormation templates (`cdk synth`); Lambda Python packages are bundled by CDK.
- **Release**: `cdk deploy` applies the synthesised CloudFormation templates to AWS, producing immutable stack outputs. `aws s3 sync` deploys the frontend build.
- **Run**: Lambda execution environments are provisioned on-demand from the immutable release artifact. There is no mutation of deployed code at runtime.

### Factor VI — Processes: Execute the App as One or More Stateless Processes

**Status: Fully Satisfied (by design).**

AWS Lambda functions are inherently stateless. Each invocation receives its inputs from the event payload, reads necessary state from DynamoDB or S3, processes the request, and terminates. No in-memory state persists between invocations. Lambda execution containers may be reused for performance (warm starts), but the application logic does not rely on this. This is the canonical implementation of Factor VI.

### Factor VII — Port Binding: Export Services via Port Binding

**Status: Satisfied (adapted for serverless).**

In the traditional twelve-factor model, an application binds to a port and listens for requests. In LUNA's serverless model, this factor is satisfied at the infrastructure level: API Gateway provides the HTTP and WebSocket port-binding abstraction. Lambda functions do not listen on ports — they respond to events. This is the correct adaptation of Factor VII in a FaaS (Functions as a Service) architecture.

### Factor VIII — Concurrency: Scale Out via the Process Model

**Status: Fully Satisfied.**

Lambda's concurrency model directly embodies Factor VIII. AWS automatically spawns additional concurrent Lambda execution environments to handle increased load. DynamoDB's `PAY_PER_REQUEST` mode scales read/write throughput proportionally. The SQS queue acts as the backpressure mechanism for the inference pipeline. There are no vertical scaling bottlenecks — all scaling is horizontal and automatic.

### Factor IX — Disposability: Maximise Robustness with Fast Startup and Graceful Shutdown

**Status: Satisfied.**

Lambda functions start in under 500 milliseconds (warm) or ~1–2 seconds (cold start for Python runtimes). They do not require graceful shutdown handling — AWS terminates containers cleanly after a configurable idle period. The SQS visibility timeout ensures that if a Lambda is terminated mid-execution, the message becomes visible again and is retried by a new invocation. Dead-Letter Queue catches persistent failures after three retries.

### Factor X — Dev/Prod Parity: Keep Development, Staging, and Production as Similar as Possible

**Status: Partially Satisfied.**

The CDK stack structure supports environment differentiation via context variables and environment variable overrides, enabling deployments to separate AWS accounts or regions. Local development uses `localhost:3000` with CORS configured explicitly in the allowed-origins list. The primary gap is the SageMaker inference endpoint: local development and the demo environment use the pre-computed S3 bypass, while a production deployment would use a live SageMaker endpoint. This divergence was a deliberate cost optimisation and is documented as a known gap.

### Factor XI — Logs: Treat Logs as Event Streams

**Status: Fully Satisfied.**

No Lambda function writes to a log file or manages log rotation. All `print()` and `logging` output is automatically captured by the AWS Lambda runtime and streamed to Amazon CloudWatch Logs in real time. CloudWatch Logs acts as the log aggregation layer, where logs can be queried with CloudWatch Insights, exported to S3 for long-term archival, or subscribed to via Lambda for real-time alerting. This is exactly the event-stream model prescribed by Factor XI.

### Factor XII — Admin Processes: Run Admin/Management Tasks as One-Off Processes

**Status: Satisfied.**

All administrative and data management tasks (seeding DynamoDB, indexing OpenSearch, uploading DICOMs, creating demo users) are implemented as standalone Python scripts in `data_ingestion/`. These scripts are one-off processes — they are run from the command line, interact with the same backing services as the production Lambda functions, and exit cleanly. They are version-controlled alongside the application code. The `/auth/seed` API endpoint is an additional admin process, disabled by default via the `ENABLE_SEED_ENDPOINT` environment variable and protected by an authorisation check.

---

## 5. Development Methodology & Environment

### 5.1 Team Structure & Division of Responsibilities

The project was executed by a team of four MSc students, with responsibilities allocated according to technical specialisation and interest, while maintaining cross-functional awareness through regular synchronisation:

| Role | Primary Responsibilities |
|---|---|
| **Cloud Infrastructure Lead** | CDK stack design and implementation, IAM policy architecture, SQS/S3 event wiring, deployment pipeline |
| **Backend & API Lead** | Lambda handler implementation (auth, patient, upload, diagnostic, assistant), custom authorizer, session management |
| **ML & AI Integration Lead** | CheXOne model pipeline, SageMaker endpoint configuration, Bedrock RAG integration, OpenSearch indexing |
| **Frontend & Integration Lead** | Next.js application, React components, WebSocket client, Tailwind CSS styling, CloudFront deployment |

Weekly team meetings were held to review progress, resolve blockers, and synchronise interface contracts between components (e.g., agreeing on the DynamoDB record schemas, WebSocket message formats, and API response structures before implementation began). Meeting notes and decisions were committed to the repository's `docs/` directory.

### 5.2 Repository Management

The project used a private GitHub repository (`ivangonquir/serverless-xray-ai-classifier`) with branch-based development:

- **`main` branch**: Protected branch representing deployable production state. Direct commits were not permitted.
- **Feature branches**: Each team member worked in dedicated feature branches (`feat/rag-pipeline`, `feat/auth-handler`, `feat/frontend-websocket`, etc.).
- **Pull Requests**: All merges to `main` required at least one peer review. PR descriptions referenced the functional requirement (FR) being addressed.
- **Commit conventions**: Conventional Commits format was used (`feat:`, `fix:`, `docs:`, `infra:`), providing a clean history that maps directly to feature delivery.

### 5.3 Working Environments

| Environment | Purpose | Infrastructure |
|---|---|---|
| **Local Development** | Individual Lambda handler testing, frontend development | `localhost:3000`, `boto3` with local AWS profile, DynamoDB accessed via AWS credentials |
| **AWS Staging** | Integration testing with real AWS services | Separate CDK deployment with `dev` context variable; shorter retention periods |
| **AWS Production/Demo** | Final demonstration and evaluation | Full CDK deployment to `eu-west-1`; all seed data loaded; CloudFront URL as entry point |

### 5.4 Infrastructure as Code with AWS CDK

AWS CDK (Python) was chosen as the IaC tool for the following reasons:

- **Language alignment**: The team's primary language is Python, eliminating the cognitive overhead of a separate DSL (e.g., HCL for Terraform or YAML for CloudFormation).
- **Constructs library**: CDK's high-level constructs (e.g., `lambda_python.PythonFunction`, `s3.Bucket`, `dynamodb.Table`) abstract away low-level CloudFormation resource configuration while remaining fully customisable.
- **Type safety**: CDK's Python type annotations and IDE completion surfaced configuration errors at development time rather than deployment time.
- **Stack dependency management**: CDK automatically resolves inter-stack dependencies and synthesises CloudFormation cross-stack references, eliminating manual ARN management.
- **Reproducibility**: `cdk deploy --all` produces a deterministic deployment from a clean state in under 15 minutes (excluding the OpenSearch domain provisioning time of 10–15 minutes).

---

## 6. Technical Challenges & Solutions

### 6.1 Coding & Logic Challenges

#### Challenge: Pre-signed URL CORS for Direct Browser-to-S3 Uploads

**Problem**: The initial implementation routed DICOM uploads through API Gateway, which imposed a hard 10 MB payload limit — insufficient for DICOM files, which commonly range from 10 MB to 150 MB. The team switched to a pre-signed S3 URL model, but encountered CORS errors when the browser attempted to PUT directly to S3.

**Solution**: The S3 DICOM bucket was configured with an explicit CORS rule permitting `PUT` and `GET` methods from the CloudFront distribution domain and `localhost:3000`. The `upload_handler` Lambda signs the URL with the correct `Content-Type` header. The browser sets the `Content-Type` header to match exactly, resolving the CORS preflight rejection.

#### Challenge: SQS Visibility Timeout vs. Lambda Timeout Alignment

**Problem**: The initial SQS visibility timeout was set to 300 seconds, matching the Lambda timeout. However, AWS documentation specifies that the SQS visibility timeout must be at least six times the Lambda timeout to prevent messages from becoming visible to other consumers while a Lambda invocation is still processing.

**Solution**: The visibility timeout was updated to `2160` seconds (6 × 360-second Lambda timeout) in `storage_stack.py`. The Lambda timeout was also increased from 300 to 360 seconds to provide headroom for slow SageMaker invocations.

#### Challenge: WebSocket Connection State Management

**Problem**: The `inference_worker` Lambda needs to push results to specific browser sessions. Since Lambda is stateless, it cannot hold open WebSocket connections. The initial design had no mechanism for the worker to discover which `connectionId` to target.

**Solution**: The `connection_manager` Lambda writes each new WebSocket `connectionId` to the `ConnectionsTable` DynamoDB table, keyed by patient session context. When the inference worker completes a job, it queries the `ConnectionsTable` to retrieve all active connection IDs and calls the API Gateway WebSocket Management API endpoint for each one.

#### Challenge: bcrypt Password Comparison Timing Attack

**Problem**: The initial `auth_handler` used a direct string comparison for password validation, which is vulnerable to timing attacks. A constant-time comparison is required for security-sensitive credential handling.

**Solution**: `bcrypt.checkpw()` was adopted for all password comparisons. Additionally, a pepper value retrieved from Secrets Manager is concatenated to the password before hashing, adding a second layer of protection against dictionary attacks on the DynamoDB Users table.

### 6.2 Team Organisation & Version Control

#### Challenge: Circular CDK Stack Dependencies

**Problem**: The initial CDK design had `LambdaStack` importing `WebSocketStack` outputs (the WebSocket management endpoint) while `WebSocketStack` attempted to import `LambdaStack` outputs (the connection manager Lambda ARN) to wire WebSocket routes. This created a circular dependency that CDK refused to synthesise.

**Solution**: The stack dependency graph was refactored. `WebSocketStack` was made self-contained: it provisions the WebSocket API with no Lambda references. `LambdaStack` receives the WebSocket management endpoint URL as a constructor argument from `WebSocketStack` and wires its own WebSocket route integrations, breaking the circular reference. The `ALLOWED_ORIGINS` environment variable injection was also deferred to avoid a secondary circular dependency with `FrontendStack`.

#### Challenge: Merge Conflicts in CDK Stack Files

**Problem**: Multiple team members were simultaneously modifying `lambda_stack.py` to add new Lambda functions and permissions, resulting in frequent merge conflicts.

**Solution**: The team adopted a feature-branch strategy with small, focused pull requests. The CDK stack file was structured with clearly demarcated comment sections (`# ── 1. Auth Handler ──────────`) to reduce the probability of overlapping diffs. Merge conflict resolution was handled synchronously via pair programming on shared video calls.

### 6.3 AWS Service Integration Challenges

#### Challenge: OpenSearch Domain Provisioning Failures

**Problem**: The initial CDK `OpenSearch` construct configuration included `node_to_node_encryption` and `encryption_at_rest` options that, when combined with the chosen instance type and access policy configuration, caused CloudFormation to fail with a validation error during domain creation.

**Solution**: After consulting the AWS documentation and CloudFormation error logs in CloudWatch, the team identified that the chosen `t3.small.search` instance type does not support encryption at rest with a customer-managed key. The configuration was simplified to remove these options (with the trade-off documented in the security notes), and the domain was successfully provisioned.

#### Challenge: Amazon Bedrock Model Access Gating

**Problem**: Bedrock models (including `anthropic.claude-haiku-4-5` and `amazon.titan-embed-text-v2:0`) require explicit model access approval in the AWS console before they can be invoked via API. The initial deployment failed with `AccessDeniedException` when the RAG pipeline attempted to generate embeddings.

**Solution**: Model access was requested and approved through the AWS Bedrock Model Access console. The deployment instructions were updated to include a prerequisite step documenting this requirement before running the OpenSearch seeding script.

#### Challenge: SageMaker GPU Instance Cost Management

**Problem**: Hosting a real-time SageMaker endpoint on a `ml.g4dn.xlarge` GPU instance costs approximately $1.50/hour continuously. For a development and demonstration project, this would accumulate significant costs ($1,080 over 30 days) without providing proportional value over a pre-computed result bypass.

**Solution**: The `inference_worker` Lambda was implemented with a two-path logic: it first checks S3 for a `reference_outputs/{patient_id}/results.json` file. If found, it loads the pre-computed result directly. If not found, it falls back to invoking the SageMaker endpoint asynchronously. This design preserves full production readiness (the SageMaker path is fully implemented) while enabling cost-free demonstration with pre-computed outputs from the five demo patients.

---

## 7. Cloud Services & Resource Justification

### 7.1 AWS Lambda

**Role**: Serverless compute layer for all backend business logic.

**Benefits**: Zero server management, automatic scaling from 0 to 10,000+ concurrent executions, pay-per-invocation billing (first 1M requests/month free), built-in integration with API Gateway, SQS, S3, and CloudWatch.

**Alternatives considered**:
- *Amazon ECS/Fargate*: Would provide containerised workloads with persistent connections and longer timeouts. Discarded because Fargate containers incur fixed costs even when idle, and the application's traffic pattern is bursty rather than continuous.
- *Amazon EC2*: Would require operating system management, patching, and capacity planning. Directly contradicts the serverless design goal.

**Decision rationale**: Lambda provides the best fit for an event-driven, bursty medical imaging workload where requests arrive in clusters (triage sessions) rather than continuously.

### 7.2 Amazon API Gateway (HTTP API + WebSocket API)

**Role**: Managed API layer providing REST and WebSocket endpoints to the browser.

**Benefits**: Managed TLS termination, request throttling, CORS handling, custom authorizer integration, WebSocket connection management (connect/disconnect/message routing).

**Alternatives considered**:
- *Application Load Balancer (ALB) with Lambda targets*: Lower latency per request but lacks native WebSocket support and requires VPC configuration. Adds cost and operational complexity.
- *AWS AppSync*: A managed GraphQL + WebSocket API service. Better suited for data-graph APIs; adds unnecessary query-language complexity for LUNA's REST-oriented interface.

**Decision rationale**: API Gateway HTTP API (v2) offers 70% lower cost than REST API (v1) while providing all required features. The WebSocket API natively handles connection lifecycle management without additional infrastructure.

### 7.3 Amazon S3

**Role**: Object storage for DICOM uploads, PNG renders, pre-computed VLM outputs, SageMaker model artefacts, and static frontend files.

**Benefits**: Unlimited scalability, 99.999999999% (11 nines) durability, native event notifications, pre-signed URL support, server-side encryption, CloudFront integration.

**Alternatives considered**:
- *Amazon EFS (Elastic File System)*: Provides a POSIX filesystem interface. Better for workloads requiring shared file access; significantly more expensive for object storage patterns.
- *Amazon RDS with BLOB storage*: Storing binary image data in a relational database is an anti-pattern — it destroys database performance and makes image retrieval expensive.

**Decision rationale**: S3 is the canonical AWS object store. Its native integration with Lambda event notifications (triggering SQS) and pre-signed URL support makes it uniquely well-suited for the LUNA upload pipeline.

### 7.4 Amazon DynamoDB

**Role**: NoSQL database for all structured application data (users, sessions, patients, diagnostic results, chat history, audit logs, WebSocket connections).

**Benefits**: Single-digit millisecond latency at any scale, on-demand billing (no capacity planning), native TTL for session expiry, Global Secondary Indexes for access pattern optimisation, Point-in-Time Recovery for the audit log, deletion protection.

**Alternatives considered**:
- *Amazon RDS (PostgreSQL)*: Provides ACID transactions and SQL query flexibility. Discarded because LUNA's access patterns are key-based lookups (by patient ID, session token, connection ID) — perfect for NoSQL. RDS adds VPC configuration complexity, provisioned capacity costs, and connection pool management.
- *Amazon ElastiCache (Redis)*: Excellent for session storage but not for persistent patient or audit data. Would require a second data store.

**Decision rationale**: DynamoDB's on-demand mode perfectly matches the application's bursty, key-based access patterns. The ability to provision seven independent tables with separate IAM policies, TTL configurations, and backup policies — all at zero idle cost — is uniquely valuable in this context.

### 7.5 Amazon SQS

**Role**: Asynchronous message queue decoupling DICOM uploads from ML inference.

**Benefits**: Managed, durable message queuing with guaranteed at-least-once delivery, configurable visibility timeout, Dead-Letter Queue support, KMS encryption integration, native Lambda event source mapping.

**Alternatives considered**:
- *Amazon SNS (Simple Notification Service)*: Pub/sub model suitable for fan-out notifications. Does not provide the durable queuing and retry semantics needed for inference job management.
- *Amazon EventBridge*: Excellent for rule-based event routing across AWS services. Slightly higher overhead for simple point-to-point queue semantics.
- *Direct Lambda invocation*: Synchronous invocation from the upload handler would block the HTTP response for the duration of ML inference (30–90 seconds). Asynchronous Lambda invocation lacks DLQ support for failed executions.

**Decision rationale**: SQS provides the ideal combination of durability, retry logic, DLQ support, and Lambda integration for an asynchronous job queue.

### 7.6 Amazon OpenSearch Service

**Role**: Vector database for RAG document indexing and semantic similarity search.

**Benefits**: Managed K-NN vector search using HNSW (Hierarchical Navigable Small World) index, full-text search capabilities, managed cluster operations (snapshots, scaling, patching), native AWS IAM integration.

**Alternatives considered**:
- *Amazon Bedrock Knowledge Bases*: A fully managed RAG service that would abstract the embedding and retrieval pipeline. Discarded because it provides less control over chunking strategies, index configuration, and retrieval parameters — important for domain-specific medical literature retrieval.
- *Pinecone / Weaviate (third-party vector DBs)*: High-performance specialised vector databases. Discarded to avoid introducing external SaaS dependencies and data egress costs.
- *Amazon RDS pgvector*: PostgreSQL extension for vector similarity search. Would work for small corpora but requires provisioned RDS instance management.

**Decision rationale**: OpenSearch Service integrates natively with AWS IAM, is collocated in the same AWS region (eliminating data transfer costs), and provides production-grade vector search without external dependencies.

### 7.7 Amazon SageMaker

**Role**: Managed ML model hosting for the CheXOne multimodal VLM (chest X-ray analyser).

**Benefits**: Managed GPU instance provisioning, model container management, async inference endpoint support (suitable for long-running inference), automatic scaling policies, built-in model monitoring.

**Alternatives considered**:
- *AWS Inferentia2 on ECS*: AWS's custom ML inference accelerator chips. Cost-optimised for high-throughput inference but requires significant container and deployment configuration.
- *Hugging Face Inference Endpoints*: Managed model hosting for Hugging Face models. Introduces an external dependency outside the AWS ecosystem.
- *Lambda with ONNX runtime*: Quantised models can run within Lambda's 10 GB ephemeral storage limit. Impractical for a full multimodal VLM (multi-GB weights) and Lambda's 15-minute timeout constraint.

**Decision rationale**: SageMaker is the canonical AWS ML inference service, providing the deepest integration with IAM, VPC, and the broader AWS ecosystem. Async endpoints specifically support the batch processing pattern required for DICOM analysis.

### 7.8 Amazon Bedrock

**Role**: Managed LLM API providing access to Anthropic Claude for the RAG assistant.

**Benefits**: No model hosting costs, pay-per-token billing, no GPU capacity management, native AWS IAM authentication (no API key management), access to frontier models (Claude Haiku, Sonnet) without training infrastructure.

**Alternatives considered**:
- *OpenAI API*: Industry-leading LLM API with comparable capabilities. Discarded because it introduces an external dependency requiring API key management in Secrets Manager, incurs data transfer outside AWS, and eliminates the possibility of keeping medical data within the AWS compliance boundary.
- *Self-hosted Llama (EC2/SageMaker)*: Open-source LLM with no per-token cost. Would require significant GPU infrastructure investment and ongoing model maintenance.

**Decision rationale**: Bedrock keeps all data within the AWS ecosystem, uses IAM for authentication (no secret API key management), and provides access to Claude's superior reasoning capabilities for clinical question answering.

### 7.9 Amazon CloudFront + S3 (Frontend Hosting)

**Role**: Global CDN delivery of the Next.js static application.

**Benefits**: Edge caching eliminates latency for global clinician access, HTTPS enforcement, Origin Access Control (OAC) ensures the S3 bucket is never publicly accessible directly, automatic cache invalidation on deployment.

**Alternatives considered**:
- *Vercel*: The canonical Next.js hosting platform. Discarded to keep all infrastructure within AWS, simplify billing, and avoid external dependency.
- *AWS Amplify Hosting*: AWS's managed frontend deployment service. Would have added deployment automation but at the cost of reduced visibility and control over the CloudFront configuration.

**Decision rationale**: Direct S3 + CloudFront provides the lowest-latency, lowest-cost static hosting option within AWS, with full control over cache headers, error pages, and OAC configuration.

### 7.10 AWS Secrets Manager

**Role**: Secure storage of the bcrypt pepper secret for password hashing.

**Benefits**: Automatic secret rotation, fine-grained IAM access policies, versioned secret history, CloudTrail audit logging of all secret access events.

**Alternatives considered**:
- *AWS Systems Manager Parameter Store (SecureString)*: Lower cost for simple string secrets. Does not support automatic rotation without custom Lambda rotation functions.
- *Environment variables (plaintext)*: Never acceptable for production secrets — environment variables appear in CloudWatch Logs, CDK outputs, and CloudFormation template metadata.

**Decision rationale**: Secrets Manager is the appropriate service for credentials requiring rotation and audit logging, which are mandatory for a healthcare-adjacent application handling passwords.

### 7.11 AWS CDK (Python)

**Role**: Infrastructure as Code framework for defining, synthesising, and deploying all AWS resources.

**Benefits**: Type-safe Python constructs, automatic CloudFormation stack synthesis, dependency graph resolution between stacks, high-level resource abstractions (L2/L3 constructs), built-in security best practices (e.g., `grant_*` methods apply least-privilege policies automatically).

**Alternatives considered**:
- *AWS CloudFormation (raw YAML)*: The underlying deployment mechanism. Writing raw CloudFormation is verbose (thousands of lines for LUNA's stack) and lacks type safety.
- *Terraform*: Mature, provider-agnostic IaC tool. Would require learning HCL (a separate DSL) and lacks native AWS CDK constructs. Discarded in favour of language consistency with the Python backend.
- *AWS SAM (Serverless Application Model)*: Optimised for Lambda-centric applications. Less expressive for multi-resource architectures involving OpenSearch, SageMaker, and WebSocket APIs.

**Decision rationale**: CDK in Python provides the best balance of expressiveness, type safety, and team familiarity for a complex multi-stack AWS deployment.

---

## 8. Resource Management & Time Tracking Retrospective

### 8.1 Planned vs. Actual Hour Distribution

The project was planned against a total pool of **160 hours** across four team members (40 hours per person over the project duration). The following table presents the planned and actual hour allocation across primary task categories:

| Task Category | Planned Hours | Actual Hours | Deviation |
|---|---|---|---|
| Architectural Design & IaC | 28 | 38 | +10 (+36%) |
| Backend Development (Lambda) | 35 | 40 | +5 (+14%) |
| ML Pipeline & AI Integration | 30 | 35 | +5 (+17%) |
| Frontend Development | 25 | 22 | −3 (−12%) |
| Research & Documentation | 20 | 15 | −5 (−25%) |
| Team Meetings & Coordination | 12 | 10 | −2 (−17%) |
| Final Report Writing | 10 | 8 | −2 (−20%) |
| **Total** | **160** | **168** | **+8 (+5%)** |

### 8.2 Deviation Analysis

The team exceeded the planned hour budget by approximately 5% (8 hours). The significant overruns were concentrated in two areas:

**Architectural Design & IaC (+10 hours)**: The CDK multi-stack refactoring consumed more time than anticipated. The discovery of the circular stack dependency between `LambdaStack` and `WebSocketStack` required an architectural redesign of the WebSocket route wiring approach. Additionally, debugging the OpenSearch provisioning failures (encryption configuration incompatibility with `t3.small.search` instances) required several hours of iterative deployment and error log analysis.

**Backend Development (+5 hours)**: The SQS visibility timeout alignment issue and the WebSocket connection tracking implementation were more complex than initially estimated. The custom Lambda Authorizer also required additional time to correctly handle edge cases (expired tokens, missing headers, malformed tokens).

**ML & AI Integration (+5 hours)**: Obtaining Bedrock model access approval, debugging the OpenSearch embedding pipeline, and implementing the pre-computed S3 bypass for the SageMaker endpoint each consumed additional time beyond the estimate.

The **Frontend Development** came in under budget (−3 hours), reflecting the efficiency of the Next.js + Tailwind CSS stack and the clear API contract established before frontend development began. The **Research & Documentation** underrun (−5 hours) reflects a pragmatic decision to prioritise implementation deliverables during the final sprint, with documentation quality maintained through inline code comments and structured README files.

### 8.3 Retrospective: Optimisation Opportunities

Reflecting on the project, the team identified the following process improvements that would have reduced the deviation from planned hours:

1. **Earlier AWS service feasibility testing**: The OpenSearch and Bedrock integration issues were discovered during the integration testing phase. Establishing a "spike sprint" in the first week — where a single team member deploys a minimal version of each external AWS service — would have surfaced these blockers two to three weeks earlier, when there was more flexibility to adjust the approach.

2. **Stricter interface contracts before parallel development**: The WebSocket connection tracking design was not fully specified before both the backend and frontend teams began parallel implementation. This led to a brief period of rework when the connection model changed. A 30-minute interface definition session at the start of the WebSocket feature would have saved three to four hours of subsequent rework.

3. **CDK stack boundary planning before implementation**: The circular dependency between `LambdaStack` and `WebSocketStack` was a direct result of insufficient upfront design of the inter-stack dependency graph. A one-hour architectural review specifically focused on CDK stack outputs and inputs at project kickoff would have eliminated the 10-hour overrun in the IaC category.

4. **Automated integration testing earlier**: The test suite (`tests/integration/test_security_flow.py`, `tests/unit/test_auth_security.py`) was developed late in the project. Establishing a minimal test harness with `fakes.py` at the beginning of the backend development phase would have caught the timing-attack vulnerability in the authentication handler during development rather than during security review.

5. **Cost alerting from day one**: Setting up AWS Budgets alerts ($20/day threshold) from the first CDK deployment would have given the team earlier visibility into the GPU cost implications of SageMaker endpoint testing, potentially accelerating the decision to implement the pre-computed bypass.

---

<!-- FIGURE 3 — UI Dashboard Screenshot -->
<!-- Insert here a full-page screenshot of the LUNA dashboard showing the patient triage sidebar
     with 5 patients sorted by LUNA Risk Score, and the patient workspace panel open for a selected
     patient showing the X-ray viewer (ORIGINAL / ANNOTATED tabs), the EHR panel with risk score,
     age, smoking history, and the chat interface.
     Save as: report/img/ui_dashboard.png
     Caption: Figure 3. LUNA Web Interface — Patient triage dashboard with AI diagnostic panel. -->

![Figure 3 — LUNA Dashboard](./report/img/ui_dashboard.png)
*Figure 3. LUNA Web Interface — Patient triage dashboard showing risk-sorted patient list, X-ray viewer, EHR panel, and AI assistant.*

---

<!-- FIGURE 4 — X-ray Annotated View Screenshot -->
<!-- Insert here a screenshot of the ANNOTATED tab in the patient workspace, showing a chest X-ray
     with bounding boxes drawn by the CheXOne VLM highlighting suspected nodules or pathologies.
     Include the LUNA Risk Score displayed in the EHR panel.
     Save as: report/img/ui_annotated_xray.png
     Caption: Figure 4. CheXOne AI Annotation — Bounding boxes overlaid on chest X-ray with LUNA Risk Score. -->

![Figure 4 — Annotated X-ray View](./report/img/ui_annotated_xray.png)
*Figure 4. CheXOne AI Annotation — Bounding boxes highlighting suspected pulmonary nodules on chest X-ray, with LUNA Risk Score computed by the multimodal fusion pipeline.*

---

<!-- FIGURE 5 — RAG Chat Interface Screenshot -->
<!-- Insert here a screenshot of the LUNA AI assistant chat panel, showing a clinician question
     (e.g., "What is the LUNA risk score for this patient and what does it mean?") and the
     assistant's response with inline citations [1], [2] referencing medical literature.
     Save as: report/img/ui_chat_rag.png
     Caption: Figure 5. LUNA AI Assistant — RAG-powered clinical Q&A with medical literature citations. -->

![Figure 5 — AI Assistant Chat](./report/img/ui_chat_rag.png)
*Figure 5. LUNA AI Assistant — Retrieval-Augmented Generation chat interface showing a clinical query response with inline citations from indexed medical literature.*

---

<!-- FIGURE 6 — Real-Time Upload & WebSocket Demonstration -->
<!-- Insert here a screenshot or annotated screen capture showing the DICOM upload flow:
     the upload button in the patient bar, the in-progress status indicator, and the
     real-time WebSocket push notification appearing in the UI when the inference worker
     completes the diagnostic job.
     Save as: report/img/ui_websocket_demo.png
     Caption: Figure 6. Real-Time Inference Pipeline — WebSocket push notification after DICOM upload and AI processing. -->

![Figure 6 — WebSocket Push Notification](./report/img/ui_websocket_demo.png)
*Figure 6. Real-Time Inference Pipeline — The browser receives a WebSocket push notification the moment the inference worker completes the diagnostic job, with zero polling required.*

---

*End of Report*