"""
pipeline.py – Model loading and inference calls (report generation + grounding).
Standalone production copy for luna_production/.
"""

import torch
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info

# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates
# ─────────────────────────────────────────────────────────────────────────────

REPORT_PROMPT = (
    "Describe the findings visible in this chest X-ray. "
    "Report only abnormalities you can directly observe in the image. "
    "If the image appears normal, state that clearly. "
    "Please reason step by step, and put your final answer within \\boxed{}."
)

GROUNDING_PROMPT_TEMPLATE = (
    "Locate {finding} in the CXR.\n"
    "Output format:\n"
    "<|ref|>target name<|/ref|><|box|>(x1,y1),(x2,y2)<|/box|>\n"
    "Example: <|ref|>pneumothorax<|/ref|><|box|>(12,60),(18,87)<|/box|>\n"
)


# ─────────────────────────────────────────────────────────────────────────────
# Model loading
# ─────────────────────────────────────────────────────────────────────────────

def load_model(cfg: dict) -> tuple:
    """
    Load the CheXOne model and its processor.

    If ``model_weights_dir`` is set in *cfg* and points to an existing
    directory, weights are loaded from there (self-contained / S3 deployment).
    Otherwise falls back to HuggingFace Hub cache (local dev).
    """
    import os

    model_source = cfg["model_id"]
    weights_dir = cfg.get("model_weights_dir")
    if weights_dir and os.path.isdir(weights_dir):
        model_source = weights_dir
        print(f"  Loading from local weights: {weights_dir}")
    else:
        print(f"  Loading from HuggingFace Hub: {model_source}")

    processor_kwargs = {}
    if cfg.get("max_pixels"):
        processor_kwargs["max_pixels"] = int(cfg["max_pixels"])

    processor = AutoProcessor.from_pretrained(model_source, **processor_kwargs)

    print("  Loading model weights …")
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_source,
        torch_dtype="auto",
        device_map="auto",
    )
    model.eval()
    return model, processor


# ─────────────────────────────────────────────────────────────────────────────
# Shared inference helper
# ─────────────────────────────────────────────────────────────────────────────

def _infer(model, processor, messages: list, max_new_tokens: int, device: str) -> str:
    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        generated_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)

    trimmed = [
        out[len(inp):]
        for inp, out in zip(inputs.input_ids, generated_ids)
    ]
    return processor.batch_decode(
        trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(model, processor, image_path: str, cfg: dict) -> str:
    content = [
        {"type": "image", "image": image_path},
        {"type": "text", "text": REPORT_PROMPT},
    ]
    messages = [{"role": "user", "content": content}]
    return _infer(model, processor, messages, cfg["max_new_tokens"], cfg["device"])


def run_grounding(model, processor, image_path: str, finding: str, cfg: dict) -> str:
    prompt = GROUNDING_PROMPT_TEMPLATE.format(finding=finding)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image_path},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    return _infer(model, processor, messages, cfg["grounding_max_tokens"], cfg["device"])
