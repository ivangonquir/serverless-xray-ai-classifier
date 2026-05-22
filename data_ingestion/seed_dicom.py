"""
seed_dicom.py — Upload patient DICOM files and pre-computed VLM outputs to S3.

Run from anywhere inside the repository:

    cd data_ingestion
    python seed_dicom.py

S3 layout after seeding:
    dicoms/{patient_id}.dicom                        ← original DICOM scan
    reference_outputs/{patient_id}/results.json      ← pre-computed VLM JSON
    reference_outputs/{patient_id}/original.png      ← raw X-ray PNG
    reference_outputs/{patient_id}/annotated.png     ← X-ray + bounding boxes

The inference_worker Lambda reads reference_outputs/{patient_id}/results.json
to simulate real-time SageMaker inference for the 5 demo patients.

Required env var (loaded from .env):
    DICOM_BUCKET  — name of the S3 bucket (e.g. luna-dicom-961341555821)
"""

import os
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────

BUCKET_NAME = os.getenv("DICOM_BUCKET", "").strip()

# Locate data directory relative to this file so script works from any cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "ml" / "chexone_test_production" / "data"

DICOM_DIR = DATA_DIR / "dicoms"
REF_DIR = DATA_DIR / "reference_outputs"

# ── S3 client ─────────────────────────────────────────────────────────────

s3 = boto3.client("s3")


def upload(local: Path, s3_key: str):
    print(f"  {local.name:50s} → s3://{BUCKET_NAME}/{s3_key}")
    s3.upload_file(str(local), BUCKET_NAME, s3_key)


def main():
    if not BUCKET_NAME:
        sys.exit("ERROR: DICOM_BUCKET is not set in .env")
    if not DICOM_DIR.exists():
        sys.exit(f"ERROR: DICOM directory not found: {DICOM_DIR}")
    if not REF_DIR.exists():
        sys.exit(f"ERROR: Reference-outputs directory not found: {REF_DIR}")

    # 1. Upload original DICOM scans
    print("\n[1/2] Uploading DICOM scans …")
    for dcm in sorted(DICOM_DIR.glob("*.dicom")):
        patient_id = dcm.stem
        upload(dcm, f"dicoms/{patient_id}.dicom")

    # 2. Upload pre-computed VLM outputs (results.json + PNG renders)
    print("\n[2/2] Uploading pre-computed VLM reference outputs …")
    for patient_dir in sorted(REF_DIR.iterdir()):
        if not patient_dir.is_dir():
            continue
        pid = patient_dir.name

        for src_name, dest_name in [
            (f"{pid}_results.json",  "results.json"),
            (f"{pid}_original.png",  "original.png"),
            (f"{pid}_annotated.png", "annotated.png"),
        ]:
            src = patient_dir / src_name
            if src.exists():
                upload(src, f"reference_outputs/{pid}/{dest_name}")
            else:
                print(f"  SKIP  {pid}/{src_name} — file not found")

    print("\n✅  DICOM seeding complete.")


if __name__ == "__main__":
    main()