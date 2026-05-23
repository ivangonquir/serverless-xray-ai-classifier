# LUNA — Serverless Thoracic Screening AI Platform

> **Cloud Computing & Big Data Architecture — MSc Data Science, FIB**  
> Team: Carlos Gil · Geming Wu · Iván Quirante · Marta Borrás · Zheshuo Lin

---

## What is LUNA?

LUNA (**L**ung **U**nit **N**eural **A**ssistant) is a fully serverless, cloud-native clinical decision support platform for **thoracic X-ray screening and pulmonary disease follow-up**. It is deployed entirely on AWS and requires zero server management.

Clinicians interact with a single web interface that combines:

| Capability | Technology |
|---|---|
| **AI risk scoring** from chest X-rays | CheXOne VLM via Amazon SageMaker *(partially implemented — see below)* |
| **Annotated X-ray viewer** with bounding boxes | Pre-computed VLM outputs stored in S3 |
| **Patient triage list** sorted by LUNA Risk Score | DynamoDB + Lambda |
| **AI clinical assistant** with medical literature citations | Amazon Bedrock (Claude) + OpenSearch RAG |
| **Real-time result delivery** | API Gateway WebSocket + SQS |

### Demo entry point

```
URL:       <NEXT_PUBLIC_FRONTEND_URL from CDK output>
Username:  xxx
Password:  XXX
```

---

## How the demo works

The demo environment is pre-loaded with **5 real patient cases** from the VinDr chest X-ray dataset. All diagnostic outputs (risk scores, pathology predictions, bounding boxes) are pre-computed and stored in S3 — no live SageMaker GPU endpoint is needed to run the demo.

**Workflow from the browser:**

1. Log in → land on the triage dashboard showing 5 patients sorted by LUNA Risk Score (highest risk first).
2. Click any patient → see their EHR summary, raw X-ray, and annotated X-ray (bounding boxes drawn by the VLM).
3. Ask the AI assistant a clinical question in natural language → receive a structured, citation-backed answer grounded in indexed medical literature.

> **Note on SageMaker:** The full inference pipeline (S3 upload → SQS → Lambda → SageMaker async → WebSocket push) is implemented in code but the live GPU endpoint is kept offline to avoid continuous infrastructure costs. The `inference_worker` Lambda automatically falls back to the pre-computed S3 outputs for the 5 demo patients.

---

## Architecture overview

```
Browser (CloudFront + Next.js)
    │
    ├── REST API (API Gateway)          ← all routes protected by Lambda Authorizer
    │       ├── POST /auth/login         → auth_handler
    │       ├── GET  /patients           → patient_handler
    │       ├── GET  /patients/{id}      → patient_handler
    │       ├── POST /patients/{id}/diagnose → diagnostic_handler → SQS
    │       └── POST /assistant/query    → assistant_handler (RAG + Bedrock)
    │
    └── WebSocket API (API Gateway)      ← real-time push
            └── $connect / $disconnect  → connection_manager
                                               ↑
S3 event → SQS → inference_worker Lambda ──────┘
                        ↓
          reference_outputs/{id}/results.json   ← pre-computed VLM (demo)
          OR SageMaker InvokeEndpointAsync       ← live inference (production)
```

**Six CDK stacks** deploy the full system in `eu-west-1`:

| Stack | What it creates |
|---|---|
| `LunaStorageStack` | S3 bucket, 7 DynamoDB tables, SQS + DLQ, KMS key, Secrets Manager |
| `LunaWebSocketStack` | API Gateway WebSocket API + `connection_manager` Lambda |
| `LunaSageMakerStack` | SageMaker model + endpoint config (offline in demo) |
| `LunaLambdaStack` | All 8 Lambda functions + IAM grants + SQS event source |
| `LunaApiStack` | REST API Gateway + Lambda Authorizer + all routes |
| `LunaFrontendStack` | S3 frontend bucket + CloudFront distribution |

---

## Repository layout

```
├── backend/lambdas/        # 8 Lambda handlers (Python 3.11)
│   ├── auth_handler/       # login, logout, session management
│   ├── authorizer/         # custom token validation for API Gateway
│   ├── patient_handler/    # patient list + detail
│   ├── upload_handler/     # pre-signed S3 URL generation
│   ├── diagnostic_handler/ # enqueue diagnostic job to SQS
│   ├── inference_worker/   # SQS consumer: runs VLM + pushes result via WebSocket
│   ├── assistant_handler/  # RAG pipeline: OpenSearch + Bedrock
│   └── connection_manager/ # WebSocket connect/disconnect
├── data_ingestion/         # one-off seed scripts (run after deploy)
│   ├── seed_dynamodb.py    # create demo user account
│   ├── seed_dicom.py       # upload DICOMs + pre-computed VLM outputs to S3
│   ├── seed_opensearch.py  # chunk PDFs → embeddings → OpenSearch index
│   └── seed_patients.py    # load 5 demo patients into DynamoDB
├── frontend/               # Next.js 14 + Tailwind CSS
├── infrastructure/         # AWS CDK (Python) — 6 stacks
├── ml/chexone_test_production/
│   └── data/
│       ├── dicoms/         # 5 DICOM files (VinDr dataset)
│       ├── reference_outputs/  # pre-computed VLM JSON + PNG renders
│       ├── ehr/            # patient EHR JSON files
│       └── rag/            # medical PDF documents for RAG indexing
└── tests/                  # unit + integration tests
```

---

## Quick start

See **[DEPLOYMENT_INSTRUCTIONS.md](./DEPLOYMENT_INSTRUCTIONS.md)** for the full step-by-step guide.

Short version:

```bash
# 1. Deploy infrastructure
cd infrastructure && cdk deploy --all --require-approval never

# 2. Seed data (after OpenSearch domain is Active, ~15 min)
cd data_ingestion
python seed_dynamodb.py    # create demo user
python seed_dicom.py       # upload DICOMs + VLM outputs to S3
python seed_opensearch.py  # index medical literature
python seed_patients.py    # load 5 demo patients into DynamoDB

# 3. Build and deploy frontend
cd frontend && npm install && npm run build
aws s3 sync out/ s3://$FRONTEND_BUCKET --delete
```
