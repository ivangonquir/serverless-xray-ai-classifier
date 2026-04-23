# ─────────────────────────────────────────────────────────────────────────────
# CheXOne Production – Makefile
#
# Local testing:
#   make run-local                       → process all 5 sample patients
#   make run-local-single P=<image_id>   → process one patient
#
# S3 / SageMaker deployment:
#   make copy-weights       → copy HF cache → model_weights/
#   make package-model      → create model.tar.gz for S3 upload
#   make build-docker       → build Docker image
#   make push-ecr           → tag + push to ECR
#   make create-model       → register SageMaker Model
#   make create-endpoint-config
#   make deploy-endpoint
#   make invoke-async P=<image_id>
#   make delete-endpoint    → teardown
# ─────────────────────────────────────────────────────────────────────────────

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Load config ──────────────────────────────────────────────────────────────
CONFIG := config_production.yaml

# AWS config (parsed from YAML; requires yq or fallback to grep)
AWS_REGION        := $(shell grep 'region:' $(CONFIG) | head -1 | awk '{print $$2}' | tr -d '"')
S3_BUCKET         := $(shell grep 's3_bucket:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
S3_PREFIX_MODEL   := $(shell grep 's3_prefix_model:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
S3_PREFIX_INPUTS  := $(shell grep 's3_prefix_inputs:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
S3_PREFIX_OUTPUTS := $(shell grep 's3_prefix_outputs:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
ECR_REPO          := $(shell grep 'ecr_repository:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
ECR_TAG           := $(shell grep 'ecr_image_tag:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
SAGEMAKER_ROLE    := $(shell grep 'sagemaker_role_arn:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
ENDPOINT_NAME     := $(shell grep 'endpoint_name:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
MODEL_NAME        := $(shell grep 'model_name:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
EP_CONFIG_NAME    := $(shell grep 'endpoint_config_name:' $(CONFIG) | awk '{print $$2}' | tr -d '"')
INSTANCE_TYPE     := $(shell grep 'instance_type:' $(CONFIG) | awk '{print $$2}' | tr -d '"')

AWS_ACCOUNT_ID := $(shell aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "<AWS_ACCOUNT_ID>")
ECR_URI        := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/$(ECR_REPO)

# Local paths
CONDA_ENV   := chexone311
HF_MODEL_ID := StanfordAIMI/CheXOne
HF_CACHE    := $(HOME)/.cache/huggingface/hub/models--StanfordAIMI--CheXOne/snapshots

# ─────────────────────────────────────────────────────────────────────────────
# LOCAL TESTING
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: run-local
run-local: ## Run all 5 sample patients locally
	cd $(CURDIR) && conda run --no-capture-output -n $(CONDA_ENV) python run_local.py

.PHONY: run-local-single
run-local-single: ## Run a single patient: make run-local-single P=<image_id>
ifndef P
	$(error P is not set. Usage: make run-local-single P=<image_id>)
endif
	cd $(CURDIR) && conda run --no-capture-output -n $(CONDA_ENV) python run_local.py --patient $(P)

# ─────────────────────────────────────────────────────────────────────────────
# MODEL PACKAGING
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: copy-weights
copy-weights: ## Copy HuggingFace cache → model_weights/ for S3 packaging
	@echo "Looking for HF snapshot in $(HF_CACHE) ..."
	@SNAP=$$(ls -td $(HF_CACHE)/*/ 2>/dev/null | head -1) && \
	if [ -z "$$SNAP" ]; then echo "ERROR: No HF snapshot found. Run inference first to download the model."; exit 1; fi && \
	echo "Copying from $$SNAP → model_weights/" && \
	mkdir -p model_weights && \
	rsync -a --info=progress2 "$$SNAP" model_weights/
	@echo "✓ Weights copied to model_weights/ ($$(du -sh model_weights/ | cut -f1))"

.PHONY: package-model
package-model: ## Create model.tar.gz for S3 upload (requires model_weights/)
	@if [ ! -d model_weights ]; then echo "ERROR: model_weights/ not found. Run 'make copy-weights' first."; exit 1; fi
	@echo "Creating model.tar.gz ..."
	tar -czf model.tar.gz \
		model_weights/ \
		data/ehr/ \
		config_production.yaml \
		inference.py pipeline.py utils.py
	@echo "✓ model.tar.gz ($$(du -sh model.tar.gz | cut -f1))"

.PHONY: upload-model
upload-model: ## Upload model.tar.gz to S3
	@if [ ! -f model.tar.gz ]; then echo "ERROR: model.tar.gz not found. Run 'make package-model' first."; exit 1; fi
	aws s3 cp model.tar.gz s3://$(S3_BUCKET)/$(S3_PREFIX_MODEL)/model.tar.gz --region $(AWS_REGION)
	@echo "✓ Uploaded to s3://$(S3_BUCKET)/$(S3_PREFIX_MODEL)/model.tar.gz"

# ─────────────────────────────────────────────────────────────────────────────
# DOCKER
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: build-docker
build-docker: ## Build the Docker image
	docker build -t $(ECR_REPO):$(ECR_TAG) .
	@echo "✓ Built $(ECR_REPO):$(ECR_TAG)"

.PHONY: push-ecr
push-ecr: ## Authenticate with ECR and push the Docker image
	aws ecr get-login-password --region $(AWS_REGION) | \
		docker login --username AWS --password-stdin $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com
	docker tag $(ECR_REPO):$(ECR_TAG) $(ECR_URI):$(ECR_TAG)
	docker push $(ECR_URI):$(ECR_TAG)
	@echo "✓ Pushed $(ECR_URI):$(ECR_TAG)"

# ─────────────────────────────────────────────────────────────────────────────
# SAGEMAKER DEPLOYMENT
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: create-model
create-model: ## Register the SageMaker Model (points to S3 weights + ECR image)
	aws sagemaker create-model \
		--region $(AWS_REGION) \
		--model-name $(MODEL_NAME) \
		--primary-container \
			Image=$(ECR_URI):$(ECR_TAG),ModelDataUrl=s3://$(S3_BUCKET)/$(S3_PREFIX_MODEL)/model.tar.gz \
		--execution-role-arn $(SAGEMAKER_ROLE)
	@echo "✓ SageMaker model '$(MODEL_NAME)' created"

.PHONY: create-endpoint-config
create-endpoint-config: ## Create async endpoint configuration
	aws sagemaker create-endpoint-config \
		--region $(AWS_REGION) \
		--endpoint-config-name $(EP_CONFIG_NAME) \
		--production-variants \
			VariantName=AllTraffic,ModelName=$(MODEL_NAME),InstanceType=$(INSTANCE_TYPE),InitialInstanceCount=1 \
		--async-inference-config \
			'OutputConfig={S3OutputPath=s3://$(S3_BUCKET)/$(S3_PREFIX_OUTPUTS)/},ClientConfig={MaxConcurrentInvocationsPerInstance=2}'
	@echo "✓ Endpoint config '$(EP_CONFIG_NAME)' created"

.PHONY: deploy-endpoint
deploy-endpoint: ## Create the async SageMaker endpoint
	aws sagemaker create-endpoint \
		--region $(AWS_REGION) \
		--endpoint-name $(ENDPOINT_NAME) \
		--endpoint-config-name $(EP_CONFIG_NAME)
	@echo "✓ Endpoint '$(ENDPOINT_NAME)' deploying … (check SageMaker console for status)"

.PHONY: invoke-async
invoke-async: ## Invoke async endpoint: make invoke-async P=<image_id>
ifndef P
	$(error P is not set. Usage: make invoke-async P=<image_id>)
endif
	@echo "Uploading DICOM to S3 …"
	aws s3 cp data/dicoms/$(P).dicom s3://$(S3_BUCKET)/$(S3_PREFIX_INPUTS)/$(P).dicom --region $(AWS_REGION)
	@echo "Invoking async endpoint …"
	aws sagemaker-runtime invoke-endpoint-async \
		--region $(AWS_REGION) \
		--endpoint-name $(ENDPOINT_NAME) \
		--content-type "application/dicom" \
		--input-location s3://$(S3_BUCKET)/$(S3_PREFIX_INPUTS)/$(P).dicom \
		--accept "application/x-tar"
	@echo "✓ Async invocation submitted. Output will appear at s3://$(S3_BUCKET)/$(S3_PREFIX_OUTPUTS)/"

.PHONY: delete-endpoint
delete-endpoint: ## Tear down endpoint, config, and model
	-aws sagemaker delete-endpoint --endpoint-name $(ENDPOINT_NAME) --region $(AWS_REGION) 2>/dev/null
	-aws sagemaker delete-endpoint-config --endpoint-config-name $(EP_CONFIG_NAME) --region $(AWS_REGION) 2>/dev/null
	-aws sagemaker delete-model --model-name $(MODEL_NAME) --region $(AWS_REGION) 2>/dev/null
	@echo "✓ Endpoint, config, and model deleted"

# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove local outputs and model.tar.gz
	rm -rf outputs/ model.tar.gz
	@echo "✓ Cleaned"

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'
