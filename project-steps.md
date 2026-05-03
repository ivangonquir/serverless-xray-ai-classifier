# Overview

## AI part
### SageMaker --  CheXOne (Image Classifier)
- Takes a DICOM X-ray image as input.
- Runs through the CheXOne vision model on a SageMaker async endpoint.
- Outputs a malignancy score + detected findings with bounding boxes.
- Combined with clinical factors (age, smoking, familiy history) -> **LUNA Risk Score**

1. We go to `chexone_test_production` and run `./setup.sh` to download model weights, but we need a GPU machine with >= 16 GB RAM. 
2. Copy weights for packaging with `make copy-weights`.
3. Package into `model.tar.gz` with `make package-model`. 
4. Upload to S3 with `make upload-model`.
5. Build Docker Image with `make build-docker`.
6. Push to ECR with `make push-ecr`. It needs ECR permissions.
7. Register SageMaker model with `make create-model`, which again needs SageMaker permissions.
8. Create endpoint config with `make create-endpoint-config` (needs permissions).
9. Deploy endpoint with `make deploy-endpoint`.


### RAG + Bedrock -- LUNA Assistant (Chat)
- Clinician asks a natural language question.
- Retrieves relevant medical literature from **OpenSearch** (vector search).
- Combines that with patient data from DynamoDB.
- Sends everything to **Amazon Bedrock Claude** as context.
- Returns an answer with citations.

```bash
aws sts get-caller-identity
```
To create a new access key, go to AWS --> IAM -> Users ->  Select the user ->  Create access key ->  CLI.
1. Install frontend dependencies
	```bash
		cd frontend
		npm install
	```
	
	If you have problems, run `npm audit fix --force` to solve it. 
	
	
2. Set up environment variables
	```bash
	cp frontend/.env.local.example frontend/.env.local
	```

3. Then edit `frontend/.env.local` and fill in two values.
	- `NEXT_PUBLIC_WS_URL`: The WebSocket API Gateway

	To see these URLs, go to AWS ->  CloudFormation -> Click on a stack (LunaApiStack for the REST URL and LunaWebSocketStack for the WebSocketURL) ->  Outputs tab
	
4. Run the dev server
	```bash
	cd frontend
	npm run dev # local development
	npm run build # uplodad out/ to S3
	```

One fix: `@import` must come before the `@tailwind` directives.

5. Open `http://localhost:3000` and use the credentials `doctor:Luna2024!` (doctor) or `admin:Luna2024!` (admin).


Regarding the AI part:
![[Pasted image 20260429105156.png]]


