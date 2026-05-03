# LUNA — Changes Made & Pending Tasks

## Changes Made

### 1. Fixed backend routing bug — `assistant_handler`

**File:** `backend/lambdas/assistant_handler/handler.py`

`lambda_handler` was calling `_handle_query(query_text, user_id)` — passing a plain string as the first argument when `_handle_query` expects the full Lambda event dict. It was also wrapping the result in a second `_resp()`, producing a double-nested response. Fixed to:

```python
if method == "POST" and path.endswith("/query"):
    return _handle_query(event, user_id)
```

---

### 2. Wired frontend chat to real backend

**File:** `frontend/app/components/ChatInterface.tsx`

- Replaced unused `login` import with `apiFetch` from `lib/auth`
- Made `handleSend` async
- Removed the commented-out `fetch` block and the stub `setTimeout`
- Added real call to `POST /assistant/query` using `apiFetch`, with a loading state while waiting and error handling on failure
- Chat now sends `queryType: "patient"` with the selected patient ID when a patient is active, or `"population"` otherwise

---

### 3. Patient triage list in Sidebar

**File:** `frontend/app/components/Sidebar.tsx`

- Added `selectedPatientId` and `onSelectPatient` props
- Fetches `GET /patients` on mount (sorted by LUNA Risk Score descending from the backend)
- Renders a scrollable patient list with a colored risk dot and score number per patient
- Clicking a patient selects it (click again to deselect); selected patient is highlighted
- Added `RiskDot` and `riskScoreColor` helpers mapping `AI_FLAGGED_HIGH_RISK / MODERATE / LOW` to red / amber / cyan

---

### 4. Selected patient state in Dashboard

**File:** `frontend/app/dashboard/page.tsx`

- Added `selectedPatientId` state
- Passed down to `Sidebar` (for highlight + selection callback) and `ChatInterface` (for query routing)

---

### 5. Fixed connection_manager — pushes `connectionId` back to client

**File:** `backend/lambdas/connection_manager/handler.py`

API Gateway assigns a `connectionId` server-side; the browser has no way to read it from the WebSocket handshake. Without it, the upload handler cannot embed it in S3 metadata, so the inference worker cannot push results back to the right browser.

Fixed by having the `$connect` Lambda immediately send the `connectionId` back to the newly connected client:

```python
mgmt = boto3.client("apigatewaymanagementapi", endpoint_url=WEBSOCKET_ENDPOINT)
mgmt.post_to_connection(
    ConnectionId=connection_id,
    Data=json.dumps({"type": "connected", "connectionId": connection_id}).encode(),
)
```

---

### 6. Updated CDK — connection_manager permissions

**File:** `infrastructure/stacks/lambda_stack.py`

- Added `WEBSOCKET_ENDPOINT` env var to `connection_fn`
- Added `execute-api:ManageConnections` IAM policy so the Lambda can post messages back to connected clients

---

### 7. WebSocket hook

**File:** `frontend/lib/websocket.ts` *(new file)*

`useWebSocket` hook that:
- Connects to `NEXT_PUBLIC_WS_URL` on mount
- Listens for the `{ type: "connected", connectionId }` message sent by the fixed connection_manager and stores it in state
- Exposes `connectionId` and `lastMessage` to consumers

---

### 8. PatientBar component — upload + live result display

**File:** `frontend/app/components/PatientBar.tsx` *(new file)*

Appears at the top of the main area when a patient is selected. Handles the full diagnostics flow:

1. Fetches patient name + current risk score from `GET /patients/{id}`
2. File picker (`.dcm`, `.jpg`, `.png`)
3. Calls `POST /patients/{id}/upload` with `connectionId` → gets pre-signed S3 URL
4. Uploads file directly to S3 via `XMLHttpRequest` (shows upload % progress)
5. S3 event auto-triggers the inference pipeline (SQS → Lambda → SageMaker)
6. WebSocket listener waits for `{ type: "result" }` message for the active job
7. Displays inline result card: LUNA Risk Score, risk label, clinical summary

State machine: `idle → requesting → uploading → processing → done / error`

---

### 9. Dashboard renders PatientBar

**File:** `frontend/app/dashboard/page.tsx`

- Added `PatientBar` import
- Renders `<PatientBar patientId={selectedPatientId} />` above the chat when a patient is selected

---

## What Is Left To Do

### 1. Push and redeploy

```bash
# Push the local commits
git push

# Redeploy Lambda stack to apply connection_manager changes
cd infrastructure
cdk deploy LunaLambdaStack
```

---

### 2. Deploy the SageMaker CheXOne endpoint

Requires a Linux machine with a **NVIDIA GPU ≥ 16 GB VRAM**.

#### One-time AWS setup

```bash
aws ecr create-repository --repository-name chexone-inference --region eu-west-1

aws iam create-role \
  --role-name SageMakerExecutionRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"sagemaker.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

aws iam attach-role-policy --role-name SageMakerExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess

aws iam attach-role-policy --role-name SageMakerExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
```

#### Package and deploy

```bash
cd ml/chexone_test_production

./setup.sh           # download model weights from HuggingFace (~14 GB)
make copy-weights    # copy into model_weights/
make package-model   # create model.tar.gz
make upload-model    # upload to S3

make build-docker    # build Docker image
make push-ecr        # push to ECR

make create-model
make create-endpoint-config
make deploy-endpoint
```

#### Wait for InService status (~5–15 min)

```bash
aws sagemaker describe-endpoint \
  --endpoint-name chexone-async \
  --region eu-west-1 \
  --query 'EndpointStatus'
```

---

### 3. Populate the OpenSearch RAG index

The `luna-docs` index exists but is empty — the assistant answers without citations until documents are ingested.

Index schema expected by `assistant_handler`:

```json
{ "title": "string", "excerpt": "string", "source": "string", "embedding": [1024 floats] }
```

Embeddings are generated with **Amazon Titan Embed Text v2** (`dimensions: 1024`). Suggested content: Fleischner Society guidelines, MIMIC-CXR reports, PubMed lung oncology papers.

---

### 4. Fix typo in setup docs

In `project-steps.md` line 60, the doctor password is `Lunca2024!` — should be `Luna2024!`.
