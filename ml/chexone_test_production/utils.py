"""
utils.py – Data I/O, text parsing, bounding-box drawing and JSON persistence.
Standalone production copy for luna_production/ — VinDr-CXR only.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pydicom
from PIL import Image, ImageDraw

# ─────────────────────────────────────────────────────────────────────────────
# VinDr-CXR finding vocabulary
# ─────────────────────────────────────────────────────────────────────────────
FINDING_SYNONYMS: dict[str, list[str]] = {
    "Aortic enlargement": ["aortic enlargement", "enlarged aorta", "aortic dilatation",
                           "aortic dilation", "dilated aorta", "tortuous aorta",
                           "aorta is tortuous", "aorta remains tortuous",
                           "prominence of the ascending aorta", "prominent aorta",
                           "aorta remains enlarged", "unfolded aorta",
                           "ectatic aorta", "widened mediastinum"],
    "Atelectasis":        ["atelectasis", "atelectatic", "atelectases",
                           "linear atelectasis", "subsegmental atelectasis",
                           "discoid atelectasis", "plate-like atelectasis"],
    "Calcification":      ["calcification", "calcified", "calcific",
                           "calcified granuloma", "calcified granulomas",
                           "calcification of the aorta", "calcification of the thoracic aorta"],
    "Cardiomegaly":       ["cardiomegaly", "enlarged heart", "cardiac enlargement",
                           "enlarged cardiac silhouette", "heart is enlarged",
                           "heart size is enlarged"],
    "Consolidation":      ["consolidation", "consolidative", "consolidations",
                           "focal consolidation", "airspace consolidation"],
    "ILD":                ["ild", "interstitial lung disease", "interstitial opacity",
                           "interstitial pattern", "interstitial markings",
                           "reticular", "reticulonodular", "hyperexpansion",
                           "diffuse opacities", "interstitial changes"],
    "Infiltration":       ["infiltration", "infiltrate", "infiltrates", "infiltrative"],
    "Lung Opacity":       ["lung opacity", "opacity", "opacification", "opacities",
                           "pulmonary opacity", "hazy opacity", "airspace opacity"],
    "Nodule/Mass":        ["nodule", "mass", "nodules", "nodular", "pulmonary nodule",
                           "pulmonary mass", "lung mass", "granuloma", "granulomas"],
    "Other lesion":       ["lesion", "lesions", "abnormality", "port-a-cath",
                           "sternotomy wires", "mediastinal clips"],
    "Pleural effusion":   ["pleural effusion", "effusion", "effusions",
                           "loculated pleural effusion", "loculated effusion"],
    "Pleural thickening": ["pleural thickening", "thickening of the pleura",
                           "apical thickening", "apical cap", "apical scarring",
                           "pleural irregularity"],
    "Pneumothorax":       ["pneumothorax", "pneumothoraces"],
    "Pulmonary fibrosis": ["pulmonary fibrosis", "fibrosis", "fibrotic",
                           "interstitial fibrosis", "scarring", "fibrotic changes",
                           "fibrotic scarring", "honeycombing"],
}

_FLEXIBLE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Cardiomegaly", re.compile(
        r"cardiac\s+silhouette[\w\s]{0,20}enlarged|enlarged[\w\s]{0,20}cardiac\s+silhouette",
        re.IGNORECASE)),
    ("Cardiomegaly", re.compile(
        r"heart[\w\s]{0,15}enlarged|enlarged[\w\s]{0,15}heart",
        re.IGNORECASE)),
    ("Aortic enlargement", re.compile(
        r"aorta[\w\s]{0,15}tortuous|tortuous[\w\s]{0,15}aorta",
        re.IGNORECASE)),
    ("Aortic enlargement", re.compile(
        r"aorta[\w\s]{0,15}enlarged|enlarged[\w\s]{0,15}aorta",
        re.IGNORECASE)),
    ("Aortic enlargement", re.compile(
        r"calcification\s+of\s+the\s+(thoracic\s+)?aorta",
        re.IGNORECASE)),
]

_NEGATION_WORDS: frozenset[str] = frozenset({
    "no", "without", "absence", "absent", "negative", "clear", "free", "not",
    "normal", "unremarkable",
})

_BOX_COLORS = [
    "#FF4444", "#44BB44", "#4488FF", "#FF44FF",
    "#FF8800", "#44DDDD", "#FFFF44", "#BB44BB",
]


# ─────────────────────────────────────────────────────────────────────────────
# DICOM loading
# ─────────────────────────────────────────────────────────────────────────────

def dicom_to_pil(dicom_path: str) -> Image.Image:
    ds = pydicom.dcmread(dicom_path)
    arr = ds.pixel_array.astype(np.float32)
    if getattr(ds, "PhotometricInterpretation", "") == "MONOCHROME1":
        arr = arr.max() - arr
    arr_min, arr_max = arr.min(), arr.max()
    if arr_max > arr_min:
        arr = (arr - arr_min) / (arr_max - arr_min) * 255.0
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8)).convert("RGB")


def load_dicom_metadata(dicom_path: str) -> dict:
    ds = pydicom.dcmread(dicom_path, stop_before_pixels=True)

    def tag(k):
        v = getattr(ds, k, None)
        s = str(v).strip() if v is not None else ""
        return s if s else None

    meta = {
        "rows":    int(getattr(ds, "Rows",    0)),
        "columns": int(getattr(ds, "Columns", 0)),
        "photometric_interpretation": tag("PhotometricInterpretation"),
    }
    ps = getattr(ds, "PixelSpacing", None)
    if ps is not None:
        meta["pixel_spacing_mm"] = [float(ps[0]), float(ps[1])]
    for key in ("PatientID", "PatientAge", "PatientSex", "StudyDate",
                "Modality", "ViewPosition"):
        v = tag(key)
        if v:
            meta[key.lower()] = v
    return meta


# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────────────────────────────────────

def compute_iou(box_a: list, box_b: list) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
    inter  = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union  = area_a + area_b - inter
    return round(inter / union, 4) if union > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Report parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_report_output(full_output: str) -> dict:
    boxed = re.search(r"\\boxed\{(.*?)\}", full_output, re.DOTALL)
    if boxed:
        return {
            "full_output":     full_output,
            "reasoning_trace": full_output[: boxed.start()].strip(),
            "final_answer":    boxed.group(1).strip(),
        }
    return {"full_output": full_output, "reasoning_trace": "", "final_answer": full_output.strip()}


# ─────────────────────────────────────────────────────────────────────────────
# Finding extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_positive_findings(report_text: str) -> list:
    text_lower = report_text.lower()
    found = []
    for canonical, synonyms in FINDING_SYNONYMS.items():
        for synonym in synonyms:
            for match in re.finditer(re.escape(synonym), text_lower):
                preceding = text_lower[max(0, match.start() - 60): match.start()].split()[-5:]
                if not any(neg in preceding for neg in _NEGATION_WORDS):
                    if canonical not in found:
                        found.append(canonical)
                    break
    for canonical, pattern in _FLEXIBLE_PATTERNS:
        if canonical in found:
            continue
        for match in pattern.finditer(text_lower):
            preceding = text_lower[max(0, match.start() - 60): match.start()].split()[-5:]
            if not any(neg in preceding for neg in _NEGATION_WORDS):
                found.append(canonical)
                break
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Grounding / bounding-box parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_grounding_boxes(response: str) -> list:
    pattern = (
        r"<\|ref\|>(.*?)<\|/ref\|>"
        r"<\|box\|>\((\d+),(\d+)\),\((\d+),(\d+)\)<\|/box\|>"
    )
    return [
        {"label": label, "norm_coords": [int(x1), int(y1), int(x2), int(y2)]}
        for label, x1, y1, x2, y2 in re.findall(pattern, response)
    ]


def scale_boxes_to_pixels(boxes: list, img_width: int, img_height: int,
                           max_pixels=None) -> list:
    scaled = []
    for b in boxes:
        x1, y1, x2, y2 = b["norm_coords"]
        scaled.append({
            "label":        b["label"],
            "norm_coords":  b["norm_coords"],
            "coord_scale":  "0-100%",
            "pixel_coords": [
                max(0, min(img_width  - 1, round(x1 / 100.0 * img_width))),
                max(0, min(img_height - 1, round(y1 / 100.0 * img_height))),
                max(0, min(img_width  - 1, round(x2 / 100.0 * img_width))),
                max(0, min(img_height - 1, round(y2 / 100.0 * img_height))),
            ],
        })
    return scaled


def is_degenerate_grounding(boxes: list) -> bool:
    if not boxes:
        return False
    valid = 0
    for b in boxes:
        nc = b.get("norm_coords", [])
        if len(nc) == 4:
            x1, y1, x2, y2 = nc
            if x2 > x1 and y2 > y1 and (x2 - x1) >= 1 and (y2 - y1) >= 1:
                valid += 1
        elif b.get("pixel_coords"):
            px1, py1, px2, py2 = b["pixel_coords"]
            if px2 > px1 and py2 > py1:
                valid += 1
    return valid == 0


# ─────────────────────────────────────────────────────────────────────────────
# Image annotation
# ─────────────────────────────────────────────────────────────────────────────

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _get_font(size: int):
    try:
        from PIL import ImageFont
        return ImageFont.truetype(_FONT_PATH, size=size)
    except Exception:
        from PIL import ImageFont
        return ImageFont.load_default(size=size)


def _draw_single_box(draw, coords, label, color, line_width, font_size: int = 15):
    x1, y1, x2, y2 = coords
    draw.rectangle([x1, y1, x2, y2], outline=color, width=line_width)
    font = _get_font(font_size)
    pad = max(4, font_size // 6)
    text_xy = (x1, max(0, y1 - font_size - pad * 2))
    try:
        tb = draw.textbbox(text_xy, label, font=font)
        draw.rectangle(
            [tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad],
            fill=color,
        )
    except Exception:
        pass
    draw.text(text_xy, label, fill="white", font=font)


def draw_boxes_on_image(
    image: Image.Image,
    grounding_results: list,
    gt_bboxes: Optional[list] = None,
    include_gt: bool = True,
) -> Image.Image:
    img = image.copy().convert("RGB")
    draw = ImageDraw.Draw(img)
    ref = 1024
    scale = max(img.width, img.height) / ref
    lw = max(5, round(5 * scale))
    font_size = max(15, round(15 * scale))

    for i, result in enumerate(grounding_results):
        color = _BOX_COLORS[i % len(_BOX_COLORS)]
        boxes = result.get("boxes", [])
        if not boxes or is_degenerate_grounding(boxes):
            continue
        for box in boxes:
            if box.get("pixel_coords"):
                _draw_single_box(draw, box["pixel_coords"],
                                 result["finding"], color, lw, font_size)

    if include_gt and gt_bboxes:
        for gt in gt_bboxes:
            _draw_single_box(draw, gt["bbox_xyxy"],
                             f"{gt['finding']} [GT]", "#00DD55", lw, font_size)

    return img


# ─────────────────────────────────────────────────────────────────────────────
# Output persistence
# ─────────────────────────────────────────────────────────────────────────────

def _save_image(image: Image.Image, path: str, max_side: int) -> None:
    img = image
    if max(img.width, img.height) > max_side:
        scale = max_side / max(img.width, img.height)
        img = img.resize(
            (round(img.width * scale), round(img.height * scale)),
            Image.LANCZOS,
        )
    img.save(path)


def save_results(
    output_dir: str,
    image_name: str,
    results: dict,
    annotated_image: Optional[Image.Image],
    model_only_image: Optional[Image.Image] = None,
    max_side: int = 2048,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    stem = Path(image_name).stem

    if model_only_image is not None:
        img_out = os.path.join(output_dir, f"{stem}_model_only.png")
        _save_image(model_only_image, img_out, max_side)
        results["output_model_only_image"] = img_out

    if annotated_image is not None:
        img_out = os.path.join(output_dir, f"{stem}_annotated.png")
        _save_image(annotated_image, img_out, max_side)
        results["output_annotated_image"] = img_out

    json_path = os.path.join(output_dir, f"{stem}_results.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    return json_path
