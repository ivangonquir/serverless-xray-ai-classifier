"""
SageMaker Inference Script.
"""

import io
import json
import os

import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image

CLASSES = ["NORMAL", "PNEUMONIA"]

TRANSFORM = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def model_fn(model_dir):
    model = models.resnet50(weights=None)
    model.fc = nn.Linear(model.fc.in_features, 2)
    weights_path = os.path.join(model_dir, "model_best.pth")
    if not os.path.exists(weights_path):
        weights_path = os.path.join(model_dir, "model.pth")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.load_state_dict(torch.load(weights_path, map_location=device))
    model.to(device)
    model.eval()
    return model


def input_fn(request_body, content_type):
    if content_type not in ("image/jpeg", "image/png", "application/octet-stream"):
        raise ValueError(f"Unsupported content type: {content_type}")
    image = Image.open(io.BytesIO(request_body)).convert("RGB")
    return TRANSFORM(image).unsqueeze(0)


def predict_fn(input_tensor, model):
    device = next(model.parameters()).device
    input_tensor = input_tensor.to(device)
    with torch.no_grad():
        logits = model(input_tensor)
        probs = torch.softmax(logits, dim=1).squeeze().tolist()
    return probs


def output_fn(probs, accept):
    pneumonia_prob = round(probs[1] * 100, 2)
    label = "MALIGNANT" if probs[1] > probs[0] else "BENIGN"
    prediction = {
        "malignancyScore": pneumonia_prob,
        "nodulesDetected": [],
        "label": label,
        "confidence": round(max(probs) * 100, 2),
        "probabilities": {
            CLASSES[0]: round(probs[0] * 100, 2),
            CLASSES[1]: pneumonia_prob,
        },
    }
    return json.dumps(prediction), "application/json"
