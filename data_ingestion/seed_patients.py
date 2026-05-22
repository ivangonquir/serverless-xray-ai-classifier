"""
seed_patients.py — Load 5 demo patients into DynamoDB from pre-computed data.

Reads from:
    ml/chexone_test_production/data/ehr/{patient_id}_synthetic_ehr.json
    ml/chexone_test_production/data/reference_outputs/{patient_id}/{patient_id}_results.json

For each patient it:
  1. Maps EHR fields → PatientsTable record (patientId = DICOM image_id)
  2. Parses the VLM results.json using the same logic as inference_worker
  3. Computes the LUNA Risk Score (60 % image + 40 % clinical)
  4. Writes a COMPLETED DiagnosticResultsTable record
  5. Updates the PatientsTable with the final status and risk score

S3 image keys (populated by seed_dicom.py, referenced here):
    dicoms/{patient_id}.dicom
    reference_outputs/{patient_id}/original.png
    reference_outputs/{patient_id}/annotated.png

Run from anywhere inside the repository:
    cd data_ingestion
    python seed_patients.py

Required env vars (from .env):
    PATIENTS_TABLE              DynamoDB patients table name
    DIAGNOSTIC_RESULTS_TABLE    DynamoDB diagnostic results table name
    AWS_REGION                  AWS region (default: eu-west-1)
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
PATIENTS_TABLE_NAME = os.getenv("PATIENTS_TABLE", "").strip()
RESULTS_TABLE_NAME = os.getenv("DIAGNOSTIC_RESULTS_TABLE", "").strip()

REPO_ROOT = Path(__file__).resolve().parent.parent
EHR_DIR = REPO_ROOT / "ml" / "chexone_test_production" / "data" / "ehr"
REF_DIR = REPO_ROOT / "ml" / "chexone_test_production" / "data" / "reference_outputs"


def _floats_to_decimal(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(i) for i in obj]
    return obj

# ── Risk scoring — mirrors inference_worker/handler.py exactly ────────────

_HIGH_RISK_TERMS = {
    "malignant", "carcinoma", "cancer", "metastasis", "mass", "tumor", "adenocarcinoma",
}
_MEDIUM_RISK_TERMS = {
    "nodule", "opacity", "consolidation", "infiltrate", "lesion",
    "effusion", "pneumonia", "atelectasis", "pleural",
}


def _derive_malignancy_score(report_text_lower: str, grounding: list) -> float:
    text_score = 0.0
    if any(t in report_text_lower for t in _HIGH_RISK_TERMS):
        text_score = 60.0
    elif any(t in report_text_lower for t in _MEDIUM_RISK_TERMS):
        text_score = 30.0
    confirmed = [g for g in grounding if not g.get("degenerate") and g.get("boxes")]
    grounding_score = min(len(confirmed) * 10, 40.0)
    return min(round(text_score + grounding_score, 1), 100.0)


def _parse_chexone_output(results: dict) -> dict:
    report_text = (results.get("report") or {}).get("final_answer", "")
    grounding = results.get("grounding") or []
    malignancy_score = _derive_malignancy_score(report_text.lower(), grounding)
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


def _calculate_luna_risk_score(image_score: float, clinical_factors: dict) -> float:
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
    return round((0.6 * image_score) + (0.4 * clinical_score), 1)


def _classify_risk(score: float) -> tuple:
    if score >= 70:
        return "AI_FLAGGED_HIGH_RISK", "High Risk"
    if score >= 40:
        return "AI_FLAGGED_MODERATE_RISK", "Moderate Risk"
    return "AI_FLAGGED_LOW_RISK", "Low Risk"


def _build_clinical_summary(score, label, nodules, clinical_factors, report_text="") -> str:
    nodule_count = len(nodules)
    age = clinical_factors.get("age", "unknown")
    smoking = clinical_factors.get("smokingHistory", "unknown")
    nodule_text = f"{nodule_count} finding(s) detected" if nodule_count else "No findings detected"
    summary = (
        f"LUNA Risk Score: {score}/100 ({label}). "
        f"{nodule_text}. "
        f"Patient profile: age {age}, smoking history: {smoking}. "
        f"Clinical review recommended."
    )
    if report_text:
        summary += f" Model report: {report_text}"
    return summary


# ── EHR mapping ───────────────────────────────────────────────────────────

def _smoking_status(ehr_status: str) -> str:
    mapping = {
        "Never Smoker": "never",
        "Former Smoker": "former",
        "Current Smoker": "current",
        "E-Cigarette/Vaping User": "current",
    }
    return mapping.get(ehr_status, "never")


def _comorbidities(medical_history: dict) -> list:
    fields = [
        "pulmonary_conditions",
        "cardiovascular_conditions",
        "systemic_and_immunological_conditions",
        "oncological_history",
    ]
    return [
        medical_history[f]
        for f in fields
        if medical_history.get(f) and medical_history[f] != "None"
    ]


def _map_ehr_to_patient(ehr: dict) -> dict:
    ctx = ehr.get("historical_ehr_context", {})
    demographics = ctx.get("patient_demographics", {})
    lifestyle = ctx.get("lifestyle_and_exposures", {})
    medical = ctx.get("medical_history", {})

    age = int(demographics.get("Patient_age", 0))
    smoking = _smoking_status(lifestyle.get("smoking_status", "Never Smoker"))
    pack_years = int(lifestyle.get("pack_years", 0))

    # The EHR schema does not include a family-history-of-lung-cancer field.
    # We infer it conservatively from the patient's own oncological history.
    oncological = medical.get("oncological_history", "None")
    family_history = "Lung Cancer" in oncological and "Primary" not in oncological

    comorbidities = _comorbidities(medical)

    return {
        "age": age,
        "smokingHistory": smoking,
        "packYears": pack_years,
        "familyHistory": family_history,
        "comorbidities": comorbidities,
        # Additional rich EHR fields stored for the assistant chatbot context
        "ehrContext": ctx,
    }


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    if not PATIENTS_TABLE_NAME:
        sys.exit("ERROR: PATIENTS_TABLE is not set in .env")
    if not RESULTS_TABLE_NAME:
        sys.exit("ERROR: DIAGNOSTIC_RESULTS_TABLE is not set in .env")
    if not EHR_DIR.exists():
        sys.exit(f"ERROR: EHR directory not found: {EHR_DIR}")

    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    patients_table = dynamodb.Table(PATIENTS_TABLE_NAME)
    results_table = dynamodb.Table(RESULTS_TABLE_NAME)

    ehr_files = sorted(EHR_DIR.glob("*_synthetic_ehr.json"))
    if not ehr_files:
        sys.exit(f"ERROR: no EHR files found in {EHR_DIR}")

    print(f"\nSeeding {len(ehr_files)} patients …\n")

    for ehr_path in ehr_files:
        # patient_id is the part before _synthetic_ehr.json
        patient_id = ehr_path.name.replace("_synthetic_ehr.json", "")
        print(f"  Patient {patient_id[:12]}…")

        # 1. Load EHR
        ehr = json.loads(ehr_path.read_text())
        patient_fields = _map_ehr_to_patient(ehr)

        # 2. Load pre-computed VLM results
        results_path = REF_DIR / patient_id / f"{patient_id}_results.json"
        if not results_path.exists():
            print(f"    SKIP — results.json not found at {results_path}")
            continue
        vlm_results = json.loads(results_path.read_text())

        # 3. Parse VLM output + compute LUNA Risk Score
        image_prediction = _parse_chexone_output(vlm_results)
        image_score = float(image_prediction["malignancyScore"])
        clinical_factors = {
            "smokingHistory": patient_fields["smokingHistory"],
            "packYears": patient_fields["packYears"],
            "age": patient_fields["age"],
            "familyHistory": patient_fields["familyHistory"],
        }
        luna_risk_score = _calculate_luna_risk_score(image_score, clinical_factors)
        status, status_label = _classify_risk(luna_risk_score)
        nodules = image_prediction["nodulesDetected"]
        clinical_summary = _build_clinical_summary(
            luna_risk_score, status_label, nodules, clinical_factors,
            report_text=image_prediction.get("reportText", ""),
        )

        # S3 keys (uploaded by seed_dicom.py)
        dicom_key = f"dicoms/{patient_id}.dicom"
        original_key = f"reference_outputs/{patient_id}/original.png"
        annotated_key = f"reference_outputs/{patient_id}/annotated.png"

        now = datetime.now(timezone.utc).isoformat()
        job_id = str(uuid.uuid4())

        # 4. Write patient record
        patient_item = _floats_to_decimal({
            "patientId": patient_id,
            # patientId is used as the display identifier; no personal name stored
            "age": patient_fields["age"],
            "smokingHistory": patient_fields["smokingHistory"],
            "packYears": patient_fields["packYears"],
            "familyHistory": patient_fields["familyHistory"],
            "comorbidities": patient_fields["comorbidities"],
            "ehrContext": json.dumps(patient_fields["ehrContext"]),  # stored as string for DynamoDB
            "status": status,
            "lastLunaRiskScore": str(luna_risk_score),
            "createdAt": now,
            "updatedAt": now,
        })
        patients_table.put_item(Item=patient_item)

        # 5. Write completed diagnostic result
        result_item = _floats_to_decimal({
            "jobId": job_id,
            "patientId": patient_id,
            "status": "COMPLETED",
            "s3Key": dicom_key,
            "originalImageKey": original_key,
            "annotatedImageKey": annotated_key,
            "lunaRiskScore": str(luna_risk_score),
            "nodulesDetected": nodules,
            "imagePrediction": image_prediction,
            "clinicalFactors": clinical_factors,
            "clinicalSummary": clinical_summary,
            "createdAt": now,
            "completedAt": now,
            "requestedBy": "seed_patients",
        })
        results_table.put_item(Item=result_item)

        print(f"    ✓ LUNA Risk Score {luna_risk_score:5.1f}  ({status_label})"
              f"  |  {len(nodules)} finding(s)")

    print("\n✅  Patient seeding complete.")


if __name__ == "__main__":
    main()
