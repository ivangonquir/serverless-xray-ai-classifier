# LUNA — Serverless Lung Cancer AI Platform

## Overview

LUNA is a serverless, AI-driven clinical decision support system for **lung cancer screening and pulmonary nodule analysis**.

It combines:

- 🧠 Medical imaging AI (SageMaker CheXOne)
- 📚 Retrieval-Augmented Generation (OpenSearch + Bedrock)
- 🏥 Patient-level clinical context (DynamoDB)
- ⚡ Real-time inference pipeline (S3 + SQS + Lambda + WebSockets)

The system enables clinicians to:

- Upload chest X-rays (DICOM / JPG / PNG)
- Receive automated risk scoring + findings
- Ask natural language clinical questions
- Retrieve evidence-backed answers with citations

---

## System Architecture

> Include here an image of the final architecture

---

## Core Components

### 1. AI Imaging Model (SageMaker)

**Model:** CheXOne

**Input:** Chest X-ray (DICOM / image)

**Output:**
  - LUNA Risk Score (0–100)
  - Pathology predictions
  - Bounding boxes

---

### 2. LLM Assistant (Bedrock + RAG)

**Model:** Claude Sonnet 4-5 (Bedrock)

**Pipeline:**

1. User query received
2. Retrieve documents from OpenSearch (vector search)
3. Inject:
   - Patient context (DynamoDB)
   - Medical literature (RAG)
4. Generate response via Bedrock

**Output:**
- Structured clinical response
- Inline citations `[1], [2], ...`

---

### 3. Storage Layer

LUNA uses multiple AWS storage services depending on the data type.

---

#### Amazon S3

Used for:

- Frontend static files
- Raw DICOM uploads
- SageMaker model weights

---

#### Amazon DynamoDB

Used for:

- User data
- User session data
- ...

---

## Deployment

### Backend Architecture Deployment

> Install the dependencies

```bash
pip install -r requirements.txt
```

> Execute the following command in `infrastructure/`

```bash
cdk deploy --all
```

By default, backend responses allow local development and any CloudFront distribution origin:

* `http://localhost:3000`
* `https://*.cloudfront.net`

Use the `allowed_origins` CDK context only for additional exact origins, such as a custom frontend domain.

> Update the environment variables in a `.env` file located in the root folder.

**OPENSEARCH_HOST**=Domain endpoint of the created OpenSearch Domain
**BUCKET_NAME_DICOM**=Name of the bucket create for storing Dicom data
**NEXT_PUBLIC_API_URL**=REST API base URL found in LunaApiStack/Outputs/

---

### Uploading Frontend Static Files (S3)

> Create your own `.env.local` and update the environment variables.

> Go to `frontend/` and build the Web UI:

```bash
npm install
npm run build
```

> Execute the following command to send the built files to S3:

```bash
aws s3 sync out/ s3://<BUCKET_NAME_FRONTEND> --delete
```

---

### Uploading Necessary DynamoDB Data

> Execute the script in `data_ingestion/` to upload initial data for local development only.

```bash
python seed_dynamodb.py
```

* Do not keep demo credentials in source control or production environments.
* The `/auth/seed` API route is protected and disabled by default. If you enable it for a controlled dev environment, send explicit users in the request body and rotate/delete them afterwards.
* For the helper script, set `SEED_AUTH_TOKEN` and `SEED_USERS_JSON` in your local environment.

---

### Dicom Data (S3)

> Download the two zip files in Google Drive, unzip them and copy the first five files/folders into `data_ingestion/vindr_dicoms/` and `data_ingestion/vindr_results/`.

> Only the first five have been used (In order to limit the costs of AWS).

> Execute the following command in `data_ingestion/` to upload the data.

```bash
python seed_dicom.py
```

---

### Opensearch

> Download the following pdfs from Google Drive.

- **1_ACR Routine Chest Imaging.pdf**
- **5_1705.02315v5.pdf**

> Move them to `data_ingestion/rag_docs/`.

> Add the following configuration in OpenSearch → Domain → Security configuration (replace placeholders with your own AWS account details).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::<ACCOUNT_ID>:user/<IAM_USER_NAME>"
      },
      "Action": "es:*",
      "Resource": "arn:aws:es:<REGION>:<ACCOUNT_ID>:domain/<DOMAIN_NAME>/*"
    }
  ]
}
```

> Execute the following command in `data_ingestion/` to upload the data.

```bash
python seed_opensearch.py
```
