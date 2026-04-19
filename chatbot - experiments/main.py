import os
import re
import boto3
import json
from dotenv import load_dotenv
from library import load_history, save_message

# Load environment variables
load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
MODEL_ID = os.getenv("BEDROCK_MODEL_ID")

# -----------------------------
# 1. Bedrock client
# -----------------------------
bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=AWS_REGION
)

# -----------------------------
# 2. System prompt
# -----------------------------
SYSTEM_PROMPT = """
You are LUNA, a clinical decision support assistant for lung cancer screening.

Rules:
- Only use patient history if explicitly relevant to the question.
- If no context is available, clearly state limitations.
- Do not hallucinate medical facts.
- Be concise and structured.
- Use bullet points when possible.
"""

# -----------------------------
# 3. Detect if history is needed
# -----------------------------
def wants_history(user_input):
    keywords = [
        "history", "previous", "last", "earlier",
        "before", "trend", "change", "over time",
        "again", "recap", "summary", "evaluation",
        "patient", "this case"
    ]
    return any(k in user_input.lower() for k in keywords)

# -----------------------------
# 4. Build messages correctly
# -----------------------------
def build_messages(user_input, patient_id):
    use_history = wants_history(user_input)

    messages = []

    # ONLY retrieve from DynamoDB if needed
    if use_history and patient_id:
        history = load_history(patient_id, limit=6)  # last 3 exchanges from DynamoDB
        messages.append({
            "role": "user",
            "content": [{
                "type": "text",
                "text": f"Patient historical conversation:\n{json.dumps(history)}"
            }]
        })

    # Always include current input
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": user_input}]
    })

    return messages

# -----------------------------
# 5. Call Bedrock Claude
# -----------------------------
def call_bedrock_claude(user_input, patient_id):
    messages = build_messages(user_input, patient_id)

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 800,
        "temperature": 0.2,
        "system": SYSTEM_PROMPT,
        "messages": messages
    }

    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body)
    )

    result = json.loads(response["body"].read())

    return result["content"][0]["text"]

# -----------------------------
# 6. Chat loop
# -----------------------------
def chat():
    print("LUNA Chatbot (type 'exit' to stop)\n")

    patient_id = input("Enter Patient ID: ")
    patient_id = re.sub(r"\D", "", patient_id)

    while True:
        user_input = input("You: ")

        if user_input.lower() == "exit":
            break

        response = call_bedrock_claude(user_input, patient_id)

        print("\nLUNA:", response, "\n")

        # store in DynamoDB
        save_message(patient_id, "user", user_input)
        save_message(patient_id, "assistant", response)

# -----------------------------
# 7. Run
# -----------------------------
if __name__ == "__main__":
    chat()