"""
Inference Worker — SQS trigger → SageMaker → multimodal fusion → WebSocket

This is the core of the LUNA Automated Diagnostics pipeline (FR-4.1, FR-4.2).

Flow per SQS message:
  1. Parse the SQS message to get jobId, patientId, s3Key, connectionId.
     Messages arrive from two sources:
       a) S3 event notification (automatic, from bucket upload)
       b) Direct SQS send from DiagnosticHandler (manual trigger with context)
  2. Download the DICOM / image bytes from S3.
  3. Invoke the LUNA classifier SageMaker endpoint → image prediction score.
  4. Fetch the patient's clinical risk factors from PatientsTable.
  5. Run multimodal fusion (image score + clinical score → LUNA Risk Score).
  6. Write the completed job to DiagnosticResultsTable.
  7. Update PatientsTable with the new risk score and status.
  8. Push the result to the clinician's browser via WebSocket (FR-6.2).
"""

import io
import json
import os
import tarfile
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

s3_client = boto3.client("s3")
sagemaker_runtime = boto3.client("sagemaker-runtime")
dynamodb = boto3.resource("dynamodb")
apigw_mgmt = boto3.client(
    "apigatewaymanagementapi",
    endpoint_url=os.environ["WEBSOCKET_ENDPOINT"],
)

patients_table = dynamodb.Table(os.environ["PATIENTS_TABLE"])
results_table = dynamodb.Table(os.environ["DIAGNOSTIC_RESULTS_TABLE"])
SAGEMAKER_ENDPOINT = os.environ["SAGEMAKER_ENDPOINT"]
DICOM_BUCKET = os.environ["DICOM_BUCKET"]


def lambda_handler(event, context):
    for record in event["Records"]:
        _process_record(record)


def _process_record(sqs_record: dict):
    """Process one SQS message end-to-end."""
    body = json.loads(sqs_record["body"])

    # Support both direct SQS sends (from diagnostic_handler) and
    # S3 event notifications (from bucket notifications)
    if "jobId" in body:
        job_id = body["jobId"]
        patient_id = body["patientId"]
        s3_key = body["s3Key"]
        connection_id = body.get("connectionId", "")
    elif "Records" in body:
        # S3 event notification wrapped in SQS
        s3_rec = body["Records"][0]
        s3_key = s3_rec["s3"]["object"]["key"]

        # Read metadata embedded by upload_handler
        head = s3_client.head_object(Bucket=DICOM_BUCKET, Key=s3_key)
        meta = head.get("Metadata", {})
        job_id = meta.get("jobid", str(uuid.uuid4()))
        patient_id = meta.get("patientid", "")
        connection_id = meta.get("connectionid", "")
    else:
        print(f"Unrecognised SQS message format: {body}")
        return

    _notify(connection_id, {"type": "status", "jobId": job_id, "status": "processing"})

    try:
        _run_pipeline(job_id, patient_id, s3_key, connection_id)
    except Exception as exc:
        print(f"Pipeline failed for job {job_id}: {exc}")
        _update_job_status(job_id, "FAILED", error=str(exc))
        _notify(connection_id, {
            "type": "error",
            "jobId": job_id,
            "message": f"Diagnostic pipeline failed: {exc}",
        })


# ── Pipeline ──────────────────────────────────────────────────────────────

def _run_pipeline(job_id: str, patient_id: str, s3_key: str, connection_id: str):
    # ── Step 1: Run image classifier ────────────────────────────────────
    image_prediction = _parse_chexone_output(_invoke_sagemaker(s3_key))

    # ── Step 2: Fetch clinical risk factors ─────────────────────────────
    patient = _get_patient(patient_id)
    clinical_factors = {
        "smokingHistory": patient.get("smokingHistory", "never"),
        "packYears": int(patient.get("packYears", 0)),
        "age": int(patient.get("age", 50)),
        "familyHistory": bool(patient.get("familyHistory", False)),
    }

    # ── Step 3: Multimodal fusion → LUNA Risk Score (FR-4.2) ─────────────
    image_score = float(image_prediction.get("malignancyScore", 0))
    luna_risk_score = _calculate_luna_risk_score(image_score, clinical_factors)

    # ── Step 4: Determine clinical summary and status ────────────────────
    status, status_label = _classify_risk(luna_risk_score)
    nodules = image_prediction.get("nodulesDetected", [])
    clinical_summary = _build_clinical_summary(
        luna_risk_score, status_label, nodules, clinical_factors,
        report_text=image_prediction.get("reportText", ""),
    )

    now = datetime.now(timezone.utc).isoformat()

    # ── Step 5: Write completed result to DynamoDB ───────────────────────
    results_table.update_item(
        Key={"jobId": job_id},
        UpdateExpression=(
            "SET #st = :st, lunaRiskScore = :score, nodulesDetected = :nod, "
            "imagePrediction = :ip, clinicalFactors = :cf, "
            "clinicalSummary = :cs, completedAt = :ts"
        ),
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={
            ":st": "COMPLETED",
            ":score": str(luna_risk_score),
            ":nod": nodules,
            ":ip": image_prediction,
            ":cf": clinical_factors,
            ":cs": clinical_summary,
            ":ts": now,
        },
    )

    # ── Step 6: Update patient record with latest score and status ───────
    patients_table.update_item(
        Key={"patientId": patient_id},
        UpdateExpression="SET lastLunaRiskScore = :score, #st = :st, updatedAt = :ts",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={
            ":score": str(luna_risk_score),
            ":st": status,
            ":ts": now,
        },
    )

    # ── Step 7: Push result to browser via WebSocket (FR-6.2) ────────────
    _notify(connection_id, {
        "type": "result",
        "jobId": job_id,
        "status": "COMPLETED",
        "lunaRiskScore": luna_risk_score,
        "riskLabel": status_label,
        "nodulesDetected": nodules,
        "imagePrediction": image_prediction,
        "clinicalSummary": clinical_summary,
        "completedAt": now,
    })


# ── SageMaker async inference ─────────────────────────────────────────────

def _invoke_sagemaker(s3_key: str) -> dict:
    """
    Submits the DICOM to the CheXOne async SageMaker endpoint and waits for
    the result.

    Flow:
      1. Pass the existing S3 URI directly as InputLocation (no re-upload).
      2. invoke_endpoint_async() returns OutputLocation immediately — the
         endpoint writes a tar.gz there once inference completes.
      3. Poll that S3 path until the file appears (up to 5 minutes).
      4. Extract {image_id}_results.json from the tar.gz and return it.

    The returned dict has the structure produced by chexone_test_production:
      {
        "image_id": "...",
        "report":   {"final_answer": "...", ...},
        "grounding": [{"finding": "...", "boxes": [...], "degenerate": bool}],
        ...
      }
    """
    input_location = f"s3://{DICOM_BUCKET}/{s3_key}"

    response = sagemaker_runtime.invoke_endpoint_async(
        EndpointName=SAGEMAKER_ENDPOINT,
        InputLocation=input_location,
        ContentType="application/dicom",
        Accept="application/x-tar",
    )

    output_location = response["OutputLocation"]
    failure_location = response.get("FailureLocation", "")

    return _poll_async_result(output_location, failure_location)


def _poll_async_result(output_location: str, failure_location: str, timeout_seconds: int = 300) -> dict:
    """Polls S3 until the async endpoint writes its output tar.gz, then parses it."""
    out_bucket, out_key = _parse_s3_uri(output_location)
    deadline = time.time() + timeout_seconds
    delay = 10

    while time.time() < deadline:
        # Check for failure output first
        if failure_location:
            fail_bucket, fail_key = _parse_s3_uri(failure_location)
            try:
                s3_client.head_object(Bucket=fail_bucket, Key=fail_key)
                raise RuntimeError("CheXOne async inference failed — check SageMaker failure output")
            except ClientError as exc:
                if exc.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                    raise

        # Check for success output
        try:
            s3_client.head_object(Bucket=out_bucket, Key=out_key)
            return _extract_results_json(out_bucket, out_key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                raise

        time.sleep(delay)
        delay = min(delay * 1.5, 30)

    raise TimeoutError(f"CheXOne async inference timed out after {timeout_seconds}s")


def _extract_results_json(bucket: str, key: str) -> dict:
    """Downloads the output tar.gz from S3 and returns the _results.json contents."""
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    tar_bytes = io.BytesIO(obj["Body"].read())

    with tarfile.open(fileobj=tar_bytes, mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name.endswith("_results.json"):
                f = tar.extractfile(member)
                if f is not None:
                    return json.loads(f.read())

    raise ValueError(f"No _results.json found in SageMaker output at s3://{bucket}/{key}")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Splits 's3://bucket/key' into ('bucket', 'key')."""
    without_prefix = uri[len("s3://"):]
    bucket, key = without_prefix.split("/", 1)
    return bucket, key


# ── CheXOne output parser ─────────────────────────────────────────────────

_HIGH_RISK_TERMS = {
    "malignant", "carcinoma", "cancer", "metastasis", "mass", "tumor", "adenocarcinoma",
}
_MEDIUM_RISK_TERMS = {
    "nodule", "opacity", "consolidation", "infiltrate", "lesion",
    "effusion", "pneumonia", "atelectasis", "pleural",
}

def _parse_chexone_output(results: dict) -> dict:
    """
    Converts the raw CheXOne results.json into the format expected by
    _run_pipeline:
      {
        "malignancyScore": float (0-100),
        "nodulesDetected": list of confirmed findings with bounding boxes,
        "label":           "BENIGN" | "INDETERMINATE" | "MALIGNANT",
        "reportText":      str (full report for clinical summary),
        "imageId":         str,
      }
    """
    report_text = (results.get("report") or {}).get("final_answer", "")
    grounding = results.get("grounding") or []

    malignancy_score = _derive_malignancy_score(report_text.lower(), grounding)

    # Map each confirmed (non-degenerate) grounding finding to a nodule-like entry
    nodules_detected = [
        {
            "finding": g["finding"],
            "boxes": g.get("boxes", []),
            "confidence": 0.9 if not g.get("degenerate") else 0.3,
        }
        for g in grounding
        if not g.get("degenerate") and g.get("boxes")
    ]

    if malignancy_score >= 70:
        label = "MALIGNANT"
    elif malignancy_score >= 40:
        label = "INDETERMINATE"
    else:
        label = "BENIGN"

    return {
        "malignancyScore": malignancy_score,
        "nodulesDetected": nodules_detected,
        "label": label,
        "reportText": report_text,
        "imageId": results.get("image_id", ""),
    }


def _derive_malignancy_score(report_text_lower: str, grounding: list) -> float:
    """
    Derives a 0-100 malignancy score from the CheXOne report text and
    grounding results.

    Text signal (up to 60 pts): presence of high- or medium-risk terms.
    Grounding signal (up to 40 pts): each confirmed non-degenerate finding
    adds 10 pts, reflecting spatial evidence of abnormality.
    """
    text_score = 0.0
    if any(t in report_text_lower for t in _HIGH_RISK_TERMS):
        text_score = 60.0
    elif any(t in report_text_lower for t in _MEDIUM_RISK_TERMS):
        text_score = 30.0

    confirmed = [g for g in grounding if not g.get("degenerate") and g.get("boxes")]
    grounding_score = min(len(confirmed) * 10, 40.0)

    return min(round(text_score + grounding_score, 1), 100.0)


# ── Multimodal fusion (FR-4.2) ────────────────────────────────────────────

def _calculate_luna_risk_score(image_score: float, clinical_factors: dict) -> float:
    """
    Fuses the image malignancy probability with structured clinical risk
    factors to produce the unified LUNA Risk Score (0–100).

    Weights: 60% image signal, 40% clinical signal.
    Clinical score is derived from the Brock University lung cancer model
    risk factors (smoking, age, family history).
    """
    # Clinical risk component
    clinical_score = 0.0

    smoking = clinical_factors.get("smokingHistory", "never")
    pack_years = int(clinical_factors.get("packYears", 0))
    age = int(clinical_factors.get("age", 50))
    family_history = bool(clinical_factors.get("familyHistory", False))

    if smoking == "current":
        clinical_score += 30
    elif smoking == "former":
        clinical_score += 15

    if pack_years >= 30:
        clinical_score += 25
    elif pack_years >= 15:
        clinical_score += 15
    elif pack_years >= 5:
        clinical_score += 8

    if age >= 65:
        clinical_score += 20
    elif age >= 55:
        clinical_score += 12
    elif age >= 45:
        clinical_score += 5

    if family_history:
        clinical_score += 10

    clinical_score = min(clinical_score, 100.0)

    luna_risk_score = (0.6 * image_score) + (0.4 * clinical_score)
    return round(luna_risk_score, 1)


def _classify_risk(score: float) -> tuple[str, str]:
    """Maps a LUNA Risk Score to a DynamoDB status and a display label."""
    if score >= 70:
        return "AI_FLAGGED_HIGH_RISK", "High Risk"
    if score >= 40:
        return "AI_FLAGGED_MODERATE_RISK", "Moderate Risk"
    return "AI_FLAGGED_LOW_RISK", "Low Risk"


def _build_clinical_summary(
    score: float,
    label: str,
    nodules: list,
    clinical_factors: dict,
    report_text: str = "",
) -> str:
    nodule_count = len(nodules)
    age = clinical_factors.get("age", "unknown")
    smoking = clinical_factors.get("smokingHistory", "unknown")
    nodule_text = (
        f"{nodule_count} finding(s) detected"
        if nodule_count
        else "No findings detected"
    )
    summary = (
        f"LUNA Risk Score: {score}/100 ({label}). "
        f"{nodule_text}. "
        f"Patient profile: age {age}, smoking history: {smoking}. "
        f"Clinical review recommended."
    )
    if report_text:
        summary += f" Model report: {report_text}"
    return summary


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_patient(patient_id: str) -> dict:
    if not patient_id:
        return {}
    resp = patients_table.get_item(Key={"patientId": patient_id})
    return resp.get("Item") or {}


def _update_job_status(job_id: str, status: str, error: str = ""):
    try:
        results_table.update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #st = :st, errorMessage = :err, completedAt = :ts",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":st": status,
                ":err": error,
                ":ts": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception:
        pass


def _notify(connection_id: str, payload: dict):
    """Pushes a JSON payload to the browser via WebSocket. Silent on failure."""
    if not connection_id:
        return
    try:
        apigw_mgmt.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(payload).encode("utf-8"),
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "GoneException":
            # Connection closed — clean up silently
            pass
        else:
            print(f"WebSocket push failed ({code}): {exc}")
