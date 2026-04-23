# CheXOne – Production Inference Package

Self-contained package for running the **CheXOne VLM** (StanfordAIMI/CheXOne)
on chest X-ray DICOM images — both **locally** (for testing) and on
**AWS SageMaker** as an **asynchronous inference endpoint**.

---

## 📁 Folder Structure

```
luna_production/
├── config_production.yaml   # All configuration (local + AWS placeholders)
├── Dockerfile               # SageMaker-compatible Docker image
├── Makefile                 # Automation targets
├── requirements.txt         # Python dependencies
├── run_local.py             # Local inference runner (batch + single)
├── inference.py             # SageMaker entry point (model_fn / predict_fn)
├── pipeline.py              # Model loading + VLM inference calls
├── utils.py                 # DICOM I/O, parsing, drawing, persistence
├── .gitignore
├── data/
│   ├── dicoms/              # 5 sample DICOM files (~60 MB total)
│   ├── ehr/                 # Pre-generated synthetic EHR JSONs
│   └── reference_outputs/   # Known-good outputs for validation
└── outputs/                 # Generated at runtime (git-ignored)
```

---

## 🧪 Local Testing

### First-time setup (run once)

```bash
cd luna_production/
chmod +x setup.sh
./setup.sh
```

`setup.sh` automates the full setup in one command:
1. Creates the `chexone311` conda environment (Python 3.11) if it doesn't exist
2. Installs all Python packages from `requirements.txt`
3. Downloads the model weights from HuggingFace Hub (~14 GB, cached at `~/.cache/huggingface/`)
4. Runs a smoke test on one sample patient and verifies all output files

> **Prerequisites** (must already be installed):
> - [Miniconda or Anaconda](https://docs.conda.io/en/latest/miniconda.html)
> - NVIDIA GPU with ≥16 GB VRAM (A100 / A10G / V100) + CUDA 12.1+ drivers

### Run all 5 patients

```bash
conda activate chexone311
make run-local
```

### Run a single patient

```bash
make run-local-single P=1915f70378cedb6947df0126db6e8aad
```

Or directly:
```bash
python run_local.py --patient 1915f70378cedb6947df0126db6e8aad
```

### Output

For each patient, `outputs/<image_id>/` will contain:

| File | Description |
|------|-------------|
| `<id>_original.png` | Raw DICOM converted to 8-bit PNG (no annotations) |
| `<id>_model_only.png` | Model bounding boxes only |
| `<id>_annotated.png` | Model boxes + GT boxes (green, if GT available) |
| `<id>_results.json` | Full metadata, report, grounding, synthetic EHR |

---

## 🏥 Sample Patients

| # | Image ID | GT Findings | Type |
|---|----------|-------------|------|
| P1 | `1915f70378cedb6947df0126db6e8aad` | Aortic enlargement, Cardiomegaly | Pathology |
| P2 | `12bd4c85000b33c532fb9d57b5f2a08e` | Infiltration, Nodule/Mass, Other lesion, Pulmonary fibrosis | Pathology |
| P3 | `0bee0cde729de2d82b39527c37f11934` | Aortic enlargement, Cardiomegaly, Other lesion, Pleural thickening | Pathology |
| P4 | `15adb042e5149aca8f045e3fab6cf7f8` | *(No pathology in GT)* | Normal |
| P5 | `09cd361cf999660b8bfc4c5833875d21` | *(No pathology in GT)* | Normal |

---

## ☁️ AWS SageMaker Deployment

### Architecture

```
┌────────────┐    DICOM     ┌─────────────┐   tar.gz    ┌──────────┐
│  Frontend  │ ──────────── │  S3 Inputs  │             │S3 Outputs│
│  (App)     │   upload     │  bucket     │             │  bucket  │
└─────┬──────┘              └──────┬──────┘             └────┬─────┘
      │                            │                         │
      │  invoke-endpoint-async     │  SageMaker pulls        │
      └────────────────────────────┤  DICOM from S3          │
                                   ▼                         │
                          ┌────────────────┐                 │
                          │  SageMaker     │  writes output  │
                          │  Async Endpoint│ ────────────────┘
                          │  (GPU)         │
                          │                │
                          │  inference.py  │
                          │  ┌──────────┐  │
                          │  │ CheXOne  │  │
                          │  │  VLM     │  │
                          │  └──────────┘  │
                          └────────────────┘
```

### Configuration Required

Edit `config_production.yaml` and replace all `<PLACEHOLDER>` values:

| Field | Description | Example |
|-------|-------------|---------|
| `aws.s3_bucket` | S3 bucket name | `my-chexone-bucket` |
| `aws.ecr_repository` | ECR repo name | `chexone-inference` |
| `aws.sagemaker_role_arn` | IAM role ARN | `arn:aws:iam::123456789012:role/SageMakerRole` |

### Step-by-step Deployment

```bash
# 1. Copy model weights from HuggingFace cache to model_weights/
make copy-weights

# 2. Create model.tar.gz (weights + code + data)
make package-model

# 3. Upload model tarball to S3
make upload-model

# 4. Build Docker image
make build-docker

# 5. Push to ECR
make push-ecr

# 6. Register SageMaker Model
make create-model

# 7. Create async endpoint configuration
make create-endpoint-config

# 8. Deploy the endpoint
make deploy-endpoint

# 9. Invoke for a patient (uploads DICOM to S3, triggers async)
make invoke-async P=1915f70378cedb6947df0126db6e8aad

# 10. Clean up when done
make delete-endpoint
```

### Instance & Region

| Setting | Value |
|---------|-------|
| **AWS Region** | `eu-west-1` (Ireland) |
| **Instance Type** | `ml.g5.2xlarge` (NVIDIA A10G, 24 GB VRAM) |
| **Base Image** | AWS DLC `pytorch-inference:2.5.1-gpu-py311-cu121-ubuntu22.04-sagemaker` |
| **DLC ECR URI** | `763104351884.dkr.ecr.eu-west-1.amazonaws.com/pytorch-inference:2.5.1-gpu-py311-cu121-ubuntu22.04-sagemaker` |

### Input Format

The async endpoint accepts **raw DICOM bytes** with content-type `application/dicom`.

```python
import boto3

runtime = boto3.client("sagemaker-runtime", region_name="eu-west-1")
response = runtime.invoke_endpoint_async(
    EndpointName="chexone-async",
    ContentType="application/dicom",
    InputLocation="s3://my-bucket/chexone/inputs/patient_001.dicom",
    Accept="application/x-tar",
)
# response["OutputLocation"] → S3 URI of the output tar.gz
```

### Output Format

A `.tar.gz` file written to S3 containing:

```
<image_id>/
├── <image_id>_results.json       # full report, grounding, EHR, metadata
├── <image_id>_original.png       # raw DICOM → PNG
├── <image_id>_model_only.png     # model bounding boxes only
└── <image_id>_annotated.png      # model + GT boxes
```

---

## 🔧 Model Details

- **Model**: [StanfordAIMI/CheXOne](https://huggingface.co/StanfordAIMI/CheXOne)
- **Architecture**: Qwen2.5-VL (Vision-Language Model)
- **Capabilities**: Chest X-ray report generation + finding grounding (bounding boxes)
- **Weights size**: ~14 GB (fp16)
- **Inference**: ~20–45 sec per patient (report + grounding per finding)

---

## 📋 All Makefile Targets

```bash
make help    # shows all available targets
```

| Target | Description |
|--------|-------------|
| `run-local` | Process all 5 sample patients locally |
| `run-local-single P=<id>` | Process one patient locally |
| `copy-weights` | Copy HF cache → `model_weights/` |
| `package-model` | Create `model.tar.gz` for S3 |
| `upload-model` | Upload tarball to S3 |
| `build-docker` | Build Docker image |
| `push-ecr` | Push image to ECR |
| `create-model` | Register SageMaker Model |
| `create-endpoint-config` | Create async endpoint config |
| `deploy-endpoint` | Deploy the endpoint |
| `invoke-async P=<id>` | Submit async inference request |
| `delete-endpoint` | Tear down everything |
| `clean` | Remove local outputs + model.tar.gz |
