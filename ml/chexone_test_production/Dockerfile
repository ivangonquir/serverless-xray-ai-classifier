# ─────────────────────────────────────────────────────────────────────────────
# CheXOne Production – Docker image for SageMaker Async Inference
#
# Base: AWS Deep Learning Container (DLC) – PyTorch 2.5.1, CUDA 12.1, Py 3.11
# Region: eu-west-1  (change the ECR URI below for other regions)
# ─────────────────────────────────────────────────────────────────────────────

FROM 763104351884.dkr.ecr.eu-west-1.amazonaws.com/pytorch-inference:2.5.1-gpu-py311-cu121-ubuntu22.04-sagemaker

# ── Install additional Python packages ────────────────────────────────────────
COPY requirements.txt /opt/ml/code/requirements.txt
RUN pip install --no-cache-dir -r /opt/ml/code/requirements.txt

# ── Copy inference code ───────────────────────────────────────────────────────
COPY inference.py  /opt/ml/code/inference.py
COPY pipeline.py   /opt/ml/code/pipeline.py
COPY utils.py      /opt/ml/code/utils.py

# ── Copy bundled data (synthetic EHR for known patients) ──────────────────────
COPY data/ehr/ /opt/ml/model/data/ehr/

# ── Copy production config ────────────────────────────────────────────────────
COPY config_production.yaml /opt/ml/model/config_production.yaml

# ── SageMaker environment variables ───────────────────────────────────────────
# Tell the SageMaker serving stack where to find the inference script
ENV SAGEMAKER_PROGRAM inference.py
ENV SAGEMAKER_SUBMIT_DIRECTORY /opt/ml/code

# Model weights are NOT baked into the image.
# They are downloaded from S3 at container startup and placed in /opt/ml/model/.
# Use `make copy-weights && make package-model` to create the model.tar.gz.

WORKDIR /opt/ml/code
