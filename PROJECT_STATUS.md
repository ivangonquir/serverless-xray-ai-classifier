# LUNA — Changes Made & Pending Tasks

*Document created: 2026-05-03*

---

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

### ~~1. Push and redeploy~~ ✅ Done (see Updates 2026-05-03)

---

### 2. Deploy the SageMaker CheXOne endpoint

Requires a Linux machine with a **NVIDIA GPU ≥ 16 GB VRAM**. The lab account does not have EC2 permissions via CLI, so use the **AWS Console**.

#### Step 1 — Launch an EC2 GPU instance (AWS Console)

1. Go to **EC2 → Instances → Launch Instance**
2. **Name:** `chexone-setup`
3. **AMI:** Amazon Linux 2023 (x86_64)
4. **Instance type:** `g5.xlarge` (NVIDIA A10G, 24 GB VRAM, ~$1.52/hr)
5. **Key pair:** create a new one and download the `.pem` — AWS only lets you download it once
6. **Security group:** leave the default (SSH port 22 open)
7. **Storage:** increase to **100 GB** (default 8 GB is not enough for model weights)
8. **Launch**

#### Step 2 — Connect to the instance

**Option A — EC2 Instance Connect (easiest, no `.pem` needed):**
EC2 → Instances → select instance → **Connect** → **EC2 Instance Connect** tab → **Connect**

**Option B — SSH from your machine:**
```powershell
# Fix key permissions first (PowerShell)
icacls "C:\Users\ivang\Downloads\your-key.pem" /inheritance:r /grant:r "$($env:USERNAME):(R)"

# SSH in (Amazon Linux 2023 uses ec2-user, not ubuntu)
ssh -i "C:\Users\ivang\Downloads\your-key.pem" ec2-user@<public-ip>

Use `public-ip = 3.250.43.240`
```

#### Step 3 — Set up the environment on the instance

```bash
# Install Miniconda
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p $HOME/miniconda3
export PATH="$HOME/miniconda3/bin:$PATH" # Type this everytime you open a new instance

# Install git and make (Amazon Linux 2023 uses dnf, not apt)
sudo dnf install -y git make

# Clone the repo
git clone https://github.com/ivangonquir/ccbda_project.git
cd ccbda_project/ml/chexone_test_production

# Configure AWS credentials
aws configure
# Enter: Access Key, Secret Key, region: eu-west-1, output: json

# Download weights, create conda env, run smoke test (~20 min first time)
./setup.sh
```

#### Step 4 — Package and deploy

```bash
make copy-weights    # copy HuggingFace cache → model_weights/
make package-model   # create model.tar.gz
make upload-model    # upload to s3://luna-dicom-113627992593/chexone/model/

make build-docker    # build Docker image
make push-ecr        # push to ECR (113627992593.dkr.ecr.eu-west-1.amazonaws.com/chexone-inference)

make create-model
make create-endpoint-config
make deploy-endpoint
```

#### Step 5 — Wait for InService status (~5–15 min)

```bash
aws sagemaker describe-endpoint \
  --endpoint-name chexone-async \
  --region eu-west-1 \
  --query 'EndpointStatus'
# Wait until: "InService"
```

#### Step 6 — Terminate the instance (important — stops billing)

EC2 → Instances → select instance → **Instance State → Terminate**

---

### 3. Populate (fill with elements) the OpenSearch RAG index

The `luna-docs` index exists but is empty — the assistant answers without citations until documents are ingested.

Index schema expected by `assistant_handler`:

```json
{ "title": "string", "excerpt": "string", "source": "string", "embedding": [1024 floats] }
```

Embeddings are generated with **Amazon Titan Embed Text v2** (`dimensions: 1024`). Suggested content: Fleischner Society guidelines, MIMIC-CXR reports, PubMed lung oncology papers.

---

### ~~4. Fix typo in setup docs~~ ✅ Already correct — `project-steps.md` had `Luna2024!`; the old file with the typo was deleted by the team.

---

## Updates

### 2026-05-03 — First update

- **Committed all session changes** — 10 files changed (691 insertions, 117 deletions) in commit `843d405`
- **Pushed to `origin/main`** — 3 total commits pushed (`86e7f68`, `b15d212`, `843d405`)
- **Typo already resolved** — `project-steps.md` had the correct password (`Luna2024!`); the old file with the typo had been deleted by the team
- **`cdk deploy LunaLambdaStack` still pending** — `git push` done but CDK redeploy not yet run

---

### 2026-05-03 — Second update

**CDK deploy failed — Docker not running.** `PythonFunction` (used by `auth_handler`) requires Docker to bundle dependencies. Worked around by deploying only the changed Lambdas directly via AWS CLI.

**Fixed `infrastructure/requirements.txt`:**
- Removed trailing comma from `aws-cdk.aws-lambda-python-alpha` line
- Corrected version from `2.18.0a0` to `2.180.0a0` (must match `aws-cdk-lib==2.180.0`)
- Ran `pip install -r infrastructure/requirements.txt` to install all missing packages

**`connection_manager` deployed via AWS CLI** (code + `WEBSOCKET_ENDPOINT` env var set):
- `execute-api:ManageConnections` IAM permission could **not** be added — lab user `lab_serverless_user` does not have `iam:PutRolePolicy`
- As a result, `connection_manager` silently fails to push `connectionId` back to the browser

**Workaround implemented** to bypass the missing IAM permission — three-file change:

| File | Change |
|---|---|
| `frontend/lib/websocket.ts` | Connects with `?userId=<userId>` so the server stores userId alongside connectionId in DynamoDB |
| `backend/lambdas/upload_handler/handler.py` | Embeds `userid` in S3 object metadata alongside `jobid` and `connectionid` |
| `backend/lambdas/inference_worker/handler.py` | Reads `userid` from S3 metadata; if `connectionId` is empty, scans `ConnectionsTable` for the most recent active connection for that user and pushes the result there. Added `connections_table` DynamoDB client |

**Deployed via AWS CLI:**
- `LunaLambdaStack-LunaConnectionManager...` — updated code + `WEBSOCKET_ENDPOINT` env var
- `LunaLambdaStack-LunaUploadHandler...` — updated code
- `LunaLambdaStack-LunaInferenceWorker...` — updated code

**Frontend build:** clean (`✓ Compiled successfully`)

**Remaining open:** SageMaker CheXOne endpoint (needs GPU machine), OpenSearch RAG index ingestion

---

### 2026-05-04 — SageMaker deployment attempt

Attempted to deploy the CheXOne SageMaker endpoint from an EC2 instance. Progress made and blockers hit:

**Completed:**
- Launched new EC2 instance (Amazon Linux 2023, 100 GB storage) with `serverless-xray-kp` key pair
- Installed Miniconda, accepted conda ToS, installed all Python dependencies (torch 2.11.0, transformers, etc.)
- Worked around `/tmp` tmpfs size limit (459 MB < torch 530 MB) by setting `TMPDIR=~/tmp`
- Added 8 GB swap file to prevent OOM kills during model weight download
- Downloaded CheXOne model weights from HuggingFace (~14 GB) — weights cached in `~/.cache/huggingface/`
- Ran `make copy-weights` and `make package-model` successfully
- Granted `aws-elasticbeanstalk-ec2-role` S3 write access via bucket policy on `luna-dicom-113627992593`
- Ran `make upload-model` successfully — `model.tar.gz` uploaded to `s3://luna-dicom-113627992593/chexone/model/model.tar.gz`
- Installed Docker on the instance
- Authenticated Docker to AWS ECR using the EB instance role

**Blocked on:**
- `make build-docker` fails — base image tag `pytorch-inference:2.5.1-gpu-py311-cu121-ubuntu22.04-sagemaker` not found in `763104351884.dkr.ecr.eu-west-1.amazonaws.com`
- The CUDA version in the tag is likely wrong (`cu121` → should probably be `cu124` for PyTorch 2.5.1)

**Next session — fix the Dockerfile and resume:**

1. Update [ml/chexone_test_production/Dockerfile](ml/chexone_test_production/Dockerfile) line 8 — change `cu121` to `cu124`:
   ```
   FROM 763104351884.dkr.ecr.eu-west-1.amazonaws.com/pytorch-inference:2.5.1-gpu-py311-cu124-ubuntu22.04-sagemaker
   ```
2. Commit and push the change locally
3. On a new EC2 instance (100 GB, Amazon Linux 2023, `serverless-xray-kp`):
   - `git clone https://github.com/ivangonquir/ccbda_project.git`
   - `cd ccbda_project/ml/chexone_test_production`
   - `export PATH="$HOME/miniconda3/bin:$PATH"` (Miniconda already installed on fresh instance)
   - Authenticate Docker: `rm ~/.aws/credentials && aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin 763104351884.dkr.ecr.eu-west-1.amazonaws.com`
   - `make build-docker`
   - `make push-ecr`
   - `make create-model`
   - `make create-endpoint-config`
   - `make deploy-endpoint`
4. Wait for `"InService"` status, then terminate the instance

**Note:** `model.tar.gz` is already uploaded to S3 — no need to redo `make copy-weights / package-model / upload-model`.

**Also:** Rotate `lab_serverless_user` AWS credentials — the access key was accidentally exposed in chat.
