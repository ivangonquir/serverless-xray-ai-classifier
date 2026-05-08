import os
import boto3
from dotenv import load_dotenv

load_dotenv()

BUCKET_NAME = os.getenv("BUCKET_NAME_DICOM").strip()
LOCAL_FOLDERS = [
    "vindr_dicoms",
    "vindr_results"
]

# Optional S3 root prefix
S3_PREFIX = ""

# ─────────────────────────────────────────────
# S3 CLIENT
# ─────────────────────────────────────────────
s3 = boto3.client("s3")

# ─────────────────────────────────────────────
# UPLOAD FUNCTION
# ─────────────────────────────────────────────
def upload_folder(local_folder, bucket, s3_prefix=""):
    for root, _, files in os.walk(local_folder):
        for file in files:
            local_path = os.path.join(root, file)

            # preserve folder structure
            relative_path = os.path.relpath(local_path, local_folder)

            s3_key = "/".join(part.strip("/") for part in [s3_prefix, local_folder, relative_path] if part).replace("\\", "/")

            print(f"Uploading: {local_path} -> s3://{bucket}/{s3_key}")

            try:
                s3.upload_file(local_path, bucket, s3_key)
            except Exception as e:
                print(f"Failed to upload {local_path}: {e}")

if __name__ == "__main__":
    for folder in LOCAL_FOLDERS:
        if os.path.exists(folder):
            upload_folder(folder, BUCKET_NAME, S3_PREFIX)
        else:
            print(f"Folder not found: {folder}")

    print("✅ Dicom Seeding Complete")