# LUNA — Deployment Instructions

> **Platform:** AWS `eu-west-1`  
> **IaC:** AWS CDK (Python) — 6 stacks  
> **Demo login:** `xxx` / `xxx`

---

## Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| Python | 3.11 | [python.org](https://www.python.org/downloads/) |
| Node.js | 18 | [nodejs.org](https://nodejs.org/) |
| AWS CDK | 2.x | `npm install -g aws-cdk` |
| AWS CLI | v2 | [docs.aws.amazon.com](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |

Configure your AWS credentials:

```bash
aws configure                 # region: eu-west-1
aws sts get-caller-identity   # verify — prints your account ID
```

The IAM user/role needs permissions to create Lambda, DynamoDB, S3, SQS, OpenSearch, Secrets Manager, KMS, API Gateway, and CloudFront resources.

---

## Step 1 — Clone the repository

```bash
git clone <repo-url>
cd serverless-xray-ai-classifier
```

---

## Step 2 — Install dependencies

### CDK infrastructure
```bash
cd infrastructure
pip install -r requirements.txt
cd ..
```

### Data ingestion scripts
```bash
pip install boto3 python-dotenv bcrypt pdfplumber opensearch-py requests-aws4auth
```

### Frontend
```bash
cd frontend
npm install
cd ..
```

---

## Step 3 — Enable Bedrock model access

Before deploying, make sure these two models are enabled in your AWS account:

1. Go to **AWS Console → Amazon Bedrock → Model access** (region: `eu-west-1`)
2. Request access to:
   - `anthropic.claude-haiku-4-5` — used by the AI assistant
   - `amazon.titan-embed-text-v2:0` — used to generate OpenSearch embeddings

> This step is required before running the seed scripts. Model access approval is usually instant.

---

## Step 4 — Bootstrap CDK (first time only)

```bash
cd infrastructure
cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/eu-west-1
cd ..
```

---

## Step 5 — Deploy all stacks

```bash
cd infrastructure
cdk deploy --all --require-approval never
cd ..
```

CDK deploys 6 stacks in dependency order. This takes about **5–10 minutes**, plus an additional **10–15 minutes** for the OpenSearch domain to become `Active`.

After deployment, the terminal prints the stack outputs:

```
LunaStorageStack.OpenSearchEndpoint  = search-luna-…es.amazonaws.com
LunaStorageStack.DicomBucketName     = luna-dicom-<account-id>
LunaApiStack.ApiUrl                  = https://….execute-api.eu-west-1.amazonaws.com/prod
LunaFrontendStack.CloudFrontUrl      = https://d….cloudfront.net
LunaFrontendStack.FrontendBucketName = luna-frontend-…
LunaWebSocketStack.WebSocketUrl      = wss://….execute-api.eu-west-1.amazonaws.com/prod
```

Copy these values into the `.env` file at the repo root:

```bash
DICOM_BUCKET=luna-dicom-<account-id>
OPENSEARCH_HOST=search-luna-…es.amazonaws.com
NEXT_PUBLIC_API_URL=https://….execute-api.eu-west-1.amazonaws.com/prod
NEXT_PUBLIC_WS_URL=wss://….execute-api.eu-west-1.amazonaws.com/prod
NEXT_PUBLIC_FRONTEND_URL=https://d….cloudfront.net
FRONTEND_BUCKET=luna-frontend-…
```

> The repo ships with a `.env` pre-filled with the team's deployed values. If you deploy to your own account, replace all values with the ones printed above.

---

## Step 6 — Seed all data

All scripts live in `data_ingestion/` and read variables from `.env` automatically. Run them from that folder:

```bash
cd data_ingestion
```

### 6a — Create the demo user

```bash
python seed_dynamodb.py
```

Creates `doctorluna` / `DoctorLuna#2026!` in DynamoDB. Safe to run multiple times — skips existing usernames.

### 6b — Upload DICOMs and pre-computed VLM outputs to S3

```bash
python seed_dicom.py
```

Uploads from `ml/chexone_test_production/data/` to S3:

| S3 path | Content |
|---------|---------|
| `dicoms/{patient_id}.dicom` | Original DICOM scan |
| `reference_outputs/{patient_id}/results.json` | Pre-computed VLM output (used instead of live SageMaker) |
| `reference_outputs/{patient_id}/original.png` | Raw X-ray render |
| `reference_outputs/{patient_id}/annotated.png` | X-ray with bounding boxes |

### 6c — Index medical literature into OpenSearch

```bash
python seed_opensearch.py
```

Reads the PDFs from `ml/chexone_test_production/data/rag/`, splits them into chunks, generates Amazon Titan embeddings via Bedrock, and indexes everything into the `luna-docs` OpenSearch index.

> ⚠️ Wait for the OpenSearch domain status to be **Active** before running this script. Check in the AWS Console under Amazon OpenSearch Service.

### 6d — Load the 5 demo patients into DynamoDB

```bash
python seed_patients.py
```

Reads patient EHR data from `ml/chexone_test_production/data/ehr/` and the pre-computed VLM outputs, computes the LUNA Risk Score for each patient, and writes:

- One record per patient in **PatientsTable** (demographics, risk factors, LUNA score)
- One completed diagnostic record per patient in **DiagnosticResultsTable** (findings, bounding boxes, clinical summary)

```bash
cd ..   # back to repo root
```

---

## Step 7 — Build and deploy the frontend

Set the environment variables before building (they get baked into the Next.js static output):

```bash
export NEXT_PUBLIC_API_URL=<value from .env>
export NEXT_PUBLIC_WS_URL=<value from .env>
export NEXT_PUBLIC_FRONTEND_URL=<value from .env>
```

Build and sync to S3:

```bash
cd frontend
npm run build
aws s3 sync out/ s3://$FRONTEND_BUCKET --delete
cd ..
```

Invalidate the CloudFront cache so the new build is served immediately:

```bash
aws cloudfront create-invalidation \
    --distribution-id $(aws cloudfront list-distributions \
        --query "DistributionList.Items[?Origins.Items[0].DomainName=='${FRONTEND_BUCKET}.s3.amazonaws.com'].Id" \
        --output text) \
    --paths "/*"
```

---

## Step 8 — Verify the deployment

1. Open the `NEXT_PUBLIC_FRONTEND_URL` in your browser.
2. Log in with `doctorluna` / `DoctorLuna#2026!`
3. The sidebar should show **5 patients** sorted by LUNA Risk Score (highest first).
4. Click any patient to see:
   - **ORIGINAL** tab — raw X-ray PNG
   - **ANNOTATED** tab — X-ray with bounding boxes from the VLM
   - **EHR panel** — age, smoking history, comorbidities, LUNA Risk Score
5. Type a clinical question in the chat (e.g. *"What does this patient's risk score mean?"*) and verify you get a cited response from the AI assistant.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Login fails | User not seeded | Run `python data_ingestion/seed_dynamodb.py` |
| No patients in sidebar | Patients not seeded | Run `python data_ingestion/seed_patients.py` |
| X-ray images don't load | DICOMs not uploaded | Run `python data_ingestion/seed_dicom.py` |
| Chat returns no results | OpenSearch not indexed | Run `python data_ingestion/seed_opensearch.py` |
| Chat fails entirely | Bedrock model not enabled | Enable both models in Bedrock → Model access |
| OpenSearch seed fails | Domain not yet Active | Wait 10–15 min after `LunaStorageStack` deploy |
| WebSocket push not received | Stale connection | Refresh the browser page to reconnect |
| CDK deploy fails on SageMaker | Region quota | The SageMaker stack can be skipped — it is not required for the demo |

---

## Teardown

```bash
cd infrastructure
cdk destroy --all
```

> `LunaAuditLogTable` has `deletion_protection=True` and a `RETAIN` removal policy. It will **not** be deleted automatically. Remove it manually from the AWS Console if you want a full cleanup.

---

## Notes

- **SageMaker endpoint:** The `LunaSageMakerStack` provisions the model and endpoint configuration but the live GPU endpoint is kept offline in the demo environment to avoid continuous costs (~$1.50/h). The `inference_worker` Lambda automatically uses the pre-computed S3 outputs for the 5 demo patients. The live SageMaker path activates automatically if no pre-computed output is found.
- **CORS:** By default, API Gateway and S3 allow requests from `http://localhost:3000` and any `https://*.cloudfront.net` origin. No extra configuration is needed for the CloudFront deployment.
- **OpenSearch security:** The domain uses an IP-based access policy (no Fine-Grained Access Control). This is sufficient for the demo but should be hardened for production use.
- **`/auth/seed` endpoint:** Disabled by default (`ENABLE_SEED_ENDPOINT=false`). Use `seed_dynamodb.py` to create users instead.
