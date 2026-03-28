# Serverless AI-Driven X-Ray Classifier

A real-time, serverless web platform for assisted X-Ray diagnosis built on AWS.

## Architecture

- **Frontend**: Next.js (static export) → S3 + CloudFront
- **API**: API Gateway WebSocket + Lambda
- **Storage**: S3 (images), DynamoDB (connections + history), SQS (async queue)
- **ML**: SageMaker (ResNet training) → SageMaker Serverless Endpoint
- **Secrets**: AWS Systems Manager Parameter Store

## Project Structure

```
ccbda_project/
├── frontend/          # Next.js application
├── backend/
│   └── lambdas/
│       ├── connection_manager/   # WebSocket $connect/$disconnect
│       ├── url_generator/        # S3 pre-signed URL generator
│       └── inference_worker/     # SQS → SageMaker → DynamoDB → WebSocket push
├── ml/
│   ├── training/      # SageMaker training script (ResNet/PyTorch)
│   └── inference/     # SageMaker inference script
├── infrastructure/    # AWS CDK (Python)
│   └── stacks/
└── research/
    └── tutorial/      # SageMaker tutorial for classmates
```

## Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- AWS CLI configured (`aws configure`)
- AWS CDK CLI (`npm install -g aws-cdk`)

### Install dependencies

```bash
# Infrastructure
cd infrastructure
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

### Deploy

```bash
cd infrastructure
cdk bootstrap
cdk deploy --all
```

## Flow

1. Clinician uploads X-ray via frontend
2. Image saved to S3 (via pre-signed URL)
3. S3 event → SQS queue
4. Inference Lambda reads SQS → invokes SageMaker endpoint
5. Result written to DynamoDB
6. Result pushed to frontend via WebSocket (API Gateway Management API)
