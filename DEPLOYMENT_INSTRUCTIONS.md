# LUNA — Deployment Instructions

> **Platform:** AWS (eu-west-1)  
> **Stack:** CDK (Python) · Next.js · Lambda · DynamoDB · OpenSearch · S3 · SQS · Bedrock  
> **Demo login:** `doctorluna` / `DoctorLuna#2026!`

---

## Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| Python | 3.11 | `brew install python` / official installer |
| Node.js | 18 | `brew install node` |
| AWS CDK | 2.x | `npm install -g aws-cdk` |
| AWS CLI | v2 | [docs.aws.amazon.com](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |

Configure AWS credentials with permissions to create IAM roles, Lambda, DynamoDB, S3, OpenSearch, SQS, Secrets Manager, CloudFront, and API Gateway:

```bash
aws configure          # enter access key, secret, region eu-west-1
aws sts get-caller-identity   # verify — should print your account ID
```

---

## Step 1 — Clone & install dependencies

```bash
git clone <repo-url>
cd serverless-xray-ai-classifier
```

### Infrastructure (CDK)
```bash
cd infrastructure
pip install -r requirements.txt
npm install         # installs CDK CLI locally as well
cd ..
```

### Data-ingestion scripts
```bash
cd data_ingestion
pip install boto3 python-dotenv bcrypt pdfplumber opensearch-py requests-aws4auth
cd ..
```

---

## Step 2 — Configure environment variables

Copy the template and fill in any blank values:

```bash
cp .env .env.local     # optional local override
```

The `.env` file at the repo root is pre-filled with the deployed stack outputs.  
After a fresh deployment the outputs will change — update `.env` with the new values printed by CDK.

Key variables:

| Variable | Description |
|----------|-------------|
| `DICOM_BUCKET` | S3 bucket name for DICOMs and PNG renders |
| `USERS_TABLE` | DynamoDB table for user accounts |
| `PATIENTS_TABLE` | DynamoDB table for patient records |
| `DIAGNOSTIC_RESULTS_TABLE` | DynamoDB table for ML results |
| `OPENSEARCH_HOST` | OpenSearch domain endpoint (no `https://`) |
| `WEBSOCKET_ENDPOINT` | WebSocket API Gateway URL (`https://…`) |
| `NEXT_PUBLIC_API_URL` | REST API Gateway URL (`https://…`) |
| `NEXT_PUBLIC_WS_URL` | WebSocket URL for the browser (`wss://…`) |
| `NEXT_PUBLIC_FRONTEND_URL` | CloudFront distribution URL |
| `BEDROCK_MODEL_ID` | `anthropic.claude-haiku-4-5` |
| `DOCTORLUNA_PASSWORD` | `DoctorLuna#2026!` — demo credentials |

---

## Step 3 — Bootstrap CDK (first time only)

```bash
cd infrastructure
cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/eu-west-1
cd ..
```

---

## Step 4 — Deploy all stacks

```bash
cd infrastructure

# Deploy in dependency order (CDK resolves this automatically)
cdk deploy --all --require-approval never

# Or deploy stacks individually for troubleshooting:
# cdk deploy LunaStorageStack
# cdk deploy LunaWebSocketStack
# cdk deploy LunaSageMakerStack
# cdk deploy LunaLambdaStack
# cdk deploy LunaApiStack
# cdk deploy LunaFrontendStack

cd ..
```

> **Note on OpenSearch:** The domain takes ~10–15 minutes to become `Active` after the  
> `LunaStorageStack` deployment completes. Run the seed scripts after that window.

After deployment, CDK prints outputs like:

```
LunaStorageStack.OpenSearchEndpoint  = search-luna-knowledge-base-…es.amazonaws.com
LunaStorageStack.DicomBucketName     = luna-dicom-961341555821
LunaApiStack.ApiUrl                  = https://…execute-api.eu-west-1.amazonaws.com/prod
LunaFrontendStack.CloudFrontUrl      = https://d….cloudfront.net
LunaWebSocketStack.WebSocketUrl      = wss://….execute-api.eu-west-1.amazonaws.com/prod
```

Copy these into `.env` — specifically `OPENSEARCH_HOST`, `NEXT_PUBLIC_API_URL`,  
`NEXT_PUBLIC_FRONTEND_URL`, and `NEXT_PUBLIC_WS_URL`.

---

## Step 5 — Seed all data (run once after deploy)

All seed scripts are in `data_ingestion/` and load `.env` automatically.

### 5a — Upload DICOM scans and pre-computed VLM outputs to S3

```bash
cd data_ingestion
python seed_dicom.py
```

This uploads from `ml/chexone_test_production/data/` to S3:

| S3 path | Content |
|---------|---------|
| `dicoms/{patient_id}.dicom` | Original DICOM scan |
| `reference_outputs/{patient_id}/results.json` | Pre-computed VLM output (bypasses SageMaker) |
| `reference_outputs/{patient_id}/original.png` | Raw X-ray render |
| `reference_outputs/{patient_id}/annotated.png` | X-ray with bounding boxes |

### 5b — Seed OpenSearch with medical RAG documents

```bash
python seed_opensearch.py
```

Reads the 3 PDFs from `ml/chexone_test_production/data/rag/`, chunks them,  
generates Amazon Titan embeddings, and indexes them into the `luna-docs` index.

> Requires Bedrock model `amazon.titan-embed-text-v2:0` to be enabled in your account.  
> Go to **AWS Console → Bedrock → Model access** and request access if not already active.

### 5c — Create the demo user account

```bash
python seed_dynamodb.py
```

Creates user `doctorluna` with password `DoctorLuna#2026!` directly in DynamoDB.  
Safe to run multiple times — existing usernames are skipped.

To add additional users set `SEED_USERS_JSON` before running:

```bash
SEED_USERS_JSON='[{"username":"alice","password":"Secure#1","role":"doctor"}]' \
    python seed_dynamodb.py
```

### 5d — Load the 5 demo patients and their pre-computed diagnoses

```bash
python seed_patients.py
```

Reads `ml/chexone_test_production/data/ehr/` and `reference_outputs/`, computes the  
LUNA Risk Score using the same fusion logic as the inference_worker Lambda, and writes:

- **PatientsTable** — one record per patient (no personal names, identified by DICOM image ID)  
- **DiagnosticResultsTable** — one COMPLETED record per patient with risk score, nodule findings, and clinical summary

---

## Step 6 — Deploy the frontend

```bash
cd frontend
npm install
npm run build

# Upload to S3 and invalidate CloudFront cache
aws s3 sync out/ s3://$FRONTEND_BUCKET --delete
aws cloudfront create-invalidation \
    --distribution-id $(aws cloudfront list-distributions \
        --query "DistributionList.Items[?Origins.Items[0].DomainName=='$FRONTEND_BUCKET.s3.amazonaws.com'].Id" \
        --output text) \
    --paths "/*"
```

> **Note:** Set `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`, and  
> `NEXT_PUBLIC_FRONTEND_URL` in your shell (or `.env.local`) before building.

---

## Step 7 — Verify the deployment

1. Open `NEXT_PUBLIC_FRONTEND_URL` in your browser  
2. Log in with `doctorluna` / `DoctorLuna#2026!`  
3. The sidebar should list 5 patients identified by their DICOM image ID  
4. Click a patient — the workspace shows:  
   - **ORIGINAL** tab: raw X-ray PNG  
   - **ANNOTATED** tab: X-ray with VLM bounding boxes  
   - **EHR panel**: age, smoking history, comorbidities, LUNA Risk Score  
5. Ask the chatbot: *"What is the LUNA risk score for this patient?"*  
6. Upload a new DICOM for an existing patient — the inference_worker will load the  
   pre-computed result from S3 (simulating SageMaker) and push the result via WebSocket

---

## Architecture diagram

```
Browser (CloudFront / Next.js)
    │
    ├── REST (API Gateway)
    │       ├── POST /auth/login          → auth_handler
    │       ├── GET  /patients            → patient_handler
    │       ├── GET  /patients/{id}       → patient_handler (+ presigned URLs)
    │       ├── POST /patients/{id}/upload → upload_handler  → S3 presigned PUT
    │       ├── POST /patients/{id}/diagnose → diagnostic_handler → SQS
    │       └── POST /assistant/query     → assistant_handler (RAG + Bedrock)
    │
    └── WebSocket (API Gateway)
            └── $connect / $disconnect   → connection_manager
                                               ↑
S3 upload → SQS → inference_worker ────────────┘
                       ↓
         reference_outputs/{id}/results.json   ← pre-computed VLM bypass
         (falls back to SageMaker async if file not found)
```

---

## Demo workflow

1. **Triage view** — sidebar shows all 5 patients sorted by LUNA Risk Score (highest first)  
2. **Patient workspace** — click any patient to see their X-ray and EHR summary  
3. **Toggle ORIGINAL ↔ ANNOTATED** — see bounding boxes drawn by the VLM  
4. **Upload new scan** — click the upload button in the patient bar, pick a `.dcm` or `.png`  
   file, watch the WebSocket status update in real-time  
5. **Chat** — ask the LUNA AI assistant clinical questions; it uses RAG over the 3 PDFs  
   and full patient context from DynamoDB

---

## Common issues

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| OpenSearch deployment fails | Validation error | Fixed: removed `node_to_node_encryption` + `encryption_at_rest`; re-deploy |
| Login fails | User not seeded | Run `python data_ingestion/seed_dynamodb.py` |
| No patients in sidebar | Patients not seeded | Run `python data_ingestion/seed_patients.py` |
| Images don't load | DICOMs not uploaded or old presigned URL | Run `python data_ingestion/seed_dicom.py` |
| RAG returns no results | OpenSearch not seeded | Run `python data_ingestion/seed_opensearch.py` |
| Chatbot fails | Bedrock model not enabled | Enable `anthropic.claude-haiku-4-5` and `amazon.titan-embed-text-v2:0` in Bedrock console |
| WebSocket pushes not received | Connection not stored | Refresh the browser page to re-connect |

---

## Teardown

```bash
cd infrastructure
cdk destroy --all
```

> `LunaAuditLogTable` has `deletion_protection=True` and `RETAIN` policy.  
> Delete it manually via the AWS Console if you want a full cleanup.

---

## Security notes (production hardening)

- The OpenSearch domain uses HTTP-only access-policy authentication (no FGAC).  
  For production: enable `node_to_node_encryption`, `encryption_at_rest`, and configure  
  Fine-Grained Access Control with a master user stored in Secrets Manager.  
- The `/auth/seed` endpoint is **disabled** by default (`ENABLE_SEED_ENDPOINT=false`).  
  Use `seed_dynamodb.py` instead.  
- Rotate `DOCTORLUNA_PASSWORD` before any non-demo deployment.
