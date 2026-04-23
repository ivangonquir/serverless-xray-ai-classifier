#!/usr/bin/env python3
"""
inference.py – SageMaker Async Endpoint entry point for CheXOne.

SageMaker invokes these four functions (MME / async pattern):
    model_fn(model_dir)        → load model once at container start
    input_fn(request_body, …)  → deserialise the incoming DICOM bytes
    predict_fn(input_data, …)  → run the full report + grounding pipeline
    output_fn(prediction, …)   → serialise output as tar.gz → S3

Input : raw DICOM bytes   (content-type: application/dicom)
Output: tar.gz containing {image_id}_results.json,
        {image_id}_original.png, {image_id}_model_only.png,
        {image_id}_annotated.png
        (content-type: application/x-tar)

The synthetic EHR for known patients is bundled inside the container
at /opt/ml/model/data/ehr/.
"""

import io
import json
import os
import tarfile
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pydicom
import yaml
from PIL import Image

# ─────────────────────────────────────────────────────────────────────────────
# Imports from our production code (packaged alongside this file)
# ─────────────────────────────────────────────────────────────────────────────
from pipeline import (
    generate_report,
    load_model,
    run_grounding,
)
from utils import (
    dicom_to_pil,
    draw_boxes_on_image,
    extract_positive_findings,
    is_degenerate_grounding,
    load_dicom_metadata,
    parse_grounding_boxes,
    parse_report_output,
    save_results,
    scale_boxes_to_pixels,
)


# ─────────────────────────────────────────────────────────────────────────────
# SageMaker hooks
# ─────────────────────────────────────────────────────────────────────────────

def model_fn(model_dir: str):
    """
    Called once when the container starts.

    ``model_dir`` is ``/opt/ml/model`` — the directory where model.tar.gz
    was extracted.  It contains:
        model_weights/    – HuggingFace model snapshot
        data/ehr/         – pre-generated synthetic EHR JSONs
        config_production.yaml
        pipeline.py, utils.py, inference.py
    """
    config_path = os.path.join(model_dir, "config_production.yaml")
    with open(config_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    # Override paths to match SageMaker layout
    cfg["model_weights_dir"] = os.path.join(model_dir, "model_weights")
    cfg["_ehr_dir"]          = os.path.join(model_dir, "data", "ehr")
    cfg["_output_dir"]       = "/tmp/chexone_outputs"

    # Ensure device is set
    import torch
    cfg["device"] = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"[model_fn] Loading CheXOne from {cfg['model_weights_dir']}")
    model, processor = load_model(cfg)
    print("[model_fn] Model ready")
    return {"model": model, "processor": processor, "cfg": cfg}


def input_fn(request_body: bytes, content_type: str = "application/dicom"):
    """
    Deserialise the incoming request.

    Accepts:
        application/dicom  → raw DICOM bytes
        application/json   → JSON with base64-encoded DICOM (fallback)
    """
    if content_type in ("application/dicom", "application/octet-stream"):
        return {"dicom_bytes": request_body}

    if content_type == "application/json":
        import base64
        payload = json.loads(request_body)
        dicom_b64 = payload.get("dicom_base64", "")
        return {
            "dicom_bytes": base64.b64decode(dicom_b64),
            "image_id":    payload.get("image_id"),
        }

    raise ValueError(f"Unsupported content type: {content_type}")


def predict_fn(input_data: dict, model_bundle: dict):
    """
    Run the full CheXOne pipeline: report generation → grounding → annotated
    images.  Returns a dict with all results and file paths.
    """
    model     = model_bundle["model"]
    processor = model_bundle["processor"]
    cfg       = model_bundle["cfg"]
    max_pixels = int(cfg.get("max_pixels") or 1003520)

    dicom_bytes = input_data["dicom_bytes"]

    # Write DICOM bytes to a temp file for pydicom
    tmp_dir  = tempfile.mkdtemp(prefix="chexone_")
    image_id = input_data.get("image_id") or uuid.uuid4().hex[:32]
    dicom_path = os.path.join(tmp_dir, f"{image_id}.dicom")
    with open(dicom_path, "wb") as fh:
        fh.write(dicom_bytes)

    # Read DICOM
    metadata = load_dicom_metadata(dicom_path)
    img      = dicom_to_pil(dicom_path)
    img_w, img_h = img.size

    # Save original PNG
    out_dir = os.path.join(cfg["_output_dir"], image_id)
    os.makedirs(out_dir, exist_ok=True)
    png_path = os.path.join(out_dir, f"{image_id}_original.png")
    img.save(png_path)

    # Load synthetic EHR if available
    ehr_path = os.path.join(cfg["_ehr_dir"], f"{image_id}_synthetic_ehr.json")
    ehr_data = None
    if os.path.exists(ehr_path):
        with open(ehr_path, encoding="utf-8") as fh:
            ehr_data = json.load(fh)

    # ── Report ────────────────────────────────────────────────────────────
    raw_output = generate_report(model, processor, png_path, cfg)
    report     = parse_report_output(raw_output)

    # ── Grounding ─────────────────────────────────────────────────────────
    grounding_results = []
    if cfg.get("run_grounding", True):
        report_findings = extract_positive_findings(report["final_answer"])
        seen: set = set()
        findings = []
        for f in report_findings:
            if f.lower() not in seen:
                seen.add(f.lower())
                findings.append(f)

        for finding in findings:
            raw_gr     = run_grounding(model, processor, png_path, finding, cfg)
            boxes_norm = parse_grounding_boxes(raw_gr)
            boxes_px   = scale_boxes_to_pixels(boxes_norm, img_w, img_h, max_pixels)
            grounding_results.append({
                "finding":      finding,
                "source":       "report",
                "prompt":       f"Locate {finding} in the CXR.",
                "raw_response": raw_gr,
                "boxes":        boxes_px,
                "degenerate":   is_degenerate_grounding(boxes_px),
            })

    # ── Annotated images ──────────────────────────────────────────────────
    model_only_img = draw_boxes_on_image(img, grounding_results, include_gt=False)
    annotated_img  = draw_boxes_on_image(img, grounding_results, include_gt=True)

    # ── Assemble results ──────────────────────────────────────────────────
    results = {
        "image_name":       f"{image_id}.dicom",
        "image_id":         image_id,
        "image_dimensions": {"width": img_w, "height": img_h},
        "metadata":         metadata,
        "report":           report,
        "grounding":        grounding_results,
        "synthetic_ehr":    ehr_data.get("historical_ehr_context") if ehr_data else None,
        "run_timestamp":    datetime.now().isoformat(),
        "model_id":         cfg["model_id"],
    }

    json_path = save_results(
        out_dir, f"{image_id}.dicom", results,
        annotated_img, model_only_image=model_only_img,
    )

    return {"output_dir": out_dir, "image_id": image_id, "json_path": json_path}


def output_fn(prediction: dict, accept: str = "application/x-tar"):
    """
    Pack all output files into a tar.gz and return the bytes.
    SageMaker Async will upload this to the configured S3 output path.
    """
    out_dir  = prediction["output_dir"]
    image_id = prediction["image_id"]

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for fname in sorted(os.listdir(out_dir)):
            fpath = os.path.join(out_dir, fname)
            tar.add(fpath, arcname=f"{image_id}/{fname}")
    buf.seek(0)
    return buf.getvalue(), "application/x-tar"
