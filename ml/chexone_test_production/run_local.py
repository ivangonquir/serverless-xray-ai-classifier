#!/usr/bin/env python3
"""
run_local.py – Local CheXOne production inference runner.

Processes DICOM images from data/dicoms/ using the CheXOne VLM, bundling
pre-generated synthetic EHR data into the output.

Usage:
    # All patients in data/dicoms/
    python run_local.py

    # Single patient
    python run_local.py --patient 1915f70378cedb6947df0126db6e8aad

    # Custom config
    python run_local.py --config config_production.yaml
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent

from pipeline import generate_report, load_model, run_grounding
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
# Config
# ─────────────────────────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    # Resolve paths relative to luna_production/
    cfg["_dicoms_dir"] = str(_HERE / cfg["dicoms_dir"])
    cfg["_ehr_dir"]    = str(_HERE / cfg["ehr_dir"])
    cfg["_output_dir"] = str(_HERE / cfg["output_dir"])
    # Model weights override
    if cfg.get("model_weights_dir"):
        wd = _HERE / cfg["model_weights_dir"]
        if wd.is_dir():
            cfg["model_weights_dir"] = str(wd)
        else:
            cfg["model_weights_dir"] = None
    return cfg


def discover_patients(cfg: dict, patient_id: str | None = None) -> list[str]:
    """Return list of image_ids to process (stem of DICOM filenames)."""
    dicoms_dir = cfg["_dicoms_dir"]
    if patient_id:
        dicom_path = os.path.join(dicoms_dir, f"{patient_id}.dicom")
        if not os.path.exists(dicom_path):
            print(f"[ERROR] DICOM not found: {dicom_path}")
            sys.exit(1)
        return [patient_id]
    return sorted(
        Path(f).stem
        for f in os.listdir(dicoms_dir)
        if f.endswith(".dicom")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Single-patient pipeline
# ─────────────────────────────────────────────────────────────────────────────

def process_patient(
    image_id: str, cfg: dict, model, processor, idx: int, total: int,
) -> str | None:
    """
    Run the full inference pipeline for one DICOM image.
    Returns the output JSON path, or None on skip/error.
    """
    dicom_path  = os.path.join(cfg["_dicoms_dir"], f"{image_id}.dicom")
    img_out_dir = os.path.join(cfg["_output_dir"], image_id)
    max_pixels  = int(cfg.get("max_pixels") or 1003520)

    print(f"\n{'─' * 62}")
    print(f"  [{idx}/{total}]  {image_id}")
    print(f"{'─' * 62}")

    if not os.path.exists(dicom_path):
        print(f"  ⚠  Skipped – DICOM not found")
        return None

    # Load DICOM
    metadata = load_dicom_metadata(dicom_path)
    print(f"  Dimensions : {metadata['columns']}×{metadata['rows']} px")
    print(f"  Patient    : sex={metadata.get('patientsex', 'N/A')} "
          f"age={metadata.get('patientage', 'N/A')}")

    img = dicom_to_pil(dicom_path)
    img_w, img_h = img.size

    os.makedirs(img_out_dir, exist_ok=True)
    tmp_png = os.path.join(img_out_dir, f"{image_id}_original.png")
    img.save(tmp_png)

    # Load synthetic EHR (pre-generated, bundled in data/ehr/)
    ehr_path = os.path.join(cfg["_ehr_dir"], f"{image_id}_synthetic_ehr.json")
    ehr_data = None
    if os.path.exists(ehr_path):
        with open(ehr_path, encoding="utf-8") as fh:
            ehr_data = json.load(fh)
        print(f"  EHR loaded : ✓")
    else:
        print(f"  EHR loaded : ⚠ not found (proceeding without)")

    # ── Report ────────────────────────────────────────────────────────────────
    print("  Generating report …", end="", flush=True)
    raw_output = generate_report(model, processor, tmp_png, cfg)
    report = parse_report_output(raw_output)
    print(f" ✓  [{len(report['final_answer'])} chars]")

    # ── Grounding ─────────────────────────────────────────────────────────────
    grounding_results = []
    if cfg.get("run_grounding", True):
        report_findings = extract_positive_findings(report["final_answer"])

        # Deduplicate findings
        seen: set = set()
        findings_to_ground = []
        for f in report_findings:
            if f.lower() not in seen:
                seen.add(f.lower())
                findings_to_ground.append((f, "report"))

        print(f"  Findings   : {[f for f, _ in findings_to_ground]}")

        for finding, source in findings_to_ground:
            entry = {
                "finding": finding,
                "source": source,
                "prompt": f"Locate {finding} in the CXR.",
            }
            print(f"    → [{source}] {finding} …", end="", flush=True)
            raw_gr = run_grounding(model, processor, tmp_png, finding, cfg)
            boxes_norm = parse_grounding_boxes(raw_gr)
            boxes_px = scale_boxes_to_pixels(boxes_norm, img_w, img_h, max_pixels)
            print(f" {len(boxes_px)} box(es)")

            entry.update({
                "raw_response": raw_gr,
                "boxes": boxes_px,
                "degenerate": is_degenerate_grounding(boxes_px),
            })
            grounding_results.append(entry)

    # ── Annotated images (model-only + with GT placeholder for consistency) ──
    model_only_img = draw_boxes_on_image(img, grounding_results, include_gt=False)
    annotated_img  = draw_boxes_on_image(img, grounding_results, include_gt=True)

    # ── Assemble results ──────────────────────────────────────────────────────
    results = {
        "image_name":       f"{image_id}.dicom",
        "image_id":         image_id,
        "dicom_path":       dicom_path,
        "image_dimensions": {"width": img_w, "height": img_h},
        "metadata":         metadata,
        "report":           report,
        "grounding":        grounding_results,
        "synthetic_ehr":    ehr_data.get("historical_ehr_context") if ehr_data else None,
        "run_timestamp":    datetime.now().isoformat(),
        "model_id":         cfg["model_id"],
    }

    json_path = save_results(
        img_out_dir, f"{image_id}.dicom", results,
        annotated_img, model_only_image=model_only_img,
    )
    print(f"  ✓  → {img_out_dir}/")
    return json_path


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CheXOne local production inference runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=str(_HERE / "config_production.yaml"))
    parser.add_argument("--patient", "-p", default=None,
                        help="Single patient image_id (without .dicom extension)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    patient_ids = discover_patients(cfg, args.patient)
    total = len(patient_ids)

    print(f"\n{'═' * 62}")
    print(f"  CheXOne – Production Inference (Local)")
    print(f"  Patients : {total}")
    print(f"  Output   : {cfg['_output_dir']}")
    print(f"{'═' * 62}")

    print("\nLoading model …")
    model, processor = load_model(cfg)
    print("✓ Model ready\n")

    succeeded, failed = [], []
    for idx, pid in enumerate(patient_ids, start=1):
        try:
            result = process_patient(pid, cfg, model, processor, idx, total)
            (succeeded if result else failed).append(
                pid if result else (pid, "skipped")
            )
        except Exception as exc:
            failed.append((pid, str(exc)))
            print(f"  ✗  ERROR: {exc}")
            traceback.print_exc()

    print(f"\n{'═' * 62}")
    print(f"  Done!  {len(succeeded)}/{total} succeeded")
    if failed:
        print(f"  Issues ({len(failed)}):")
        for item in failed:
            name, reason = item if isinstance(item, tuple) else (item, "skipped")
            print(f"    • {name} – {reason}")
    print(f"  Outputs in: {cfg['_output_dir']}/")
    print(f"{'═' * 62}\n")


if __name__ == "__main__":
    main()
