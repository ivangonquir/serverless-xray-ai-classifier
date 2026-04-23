import os
import re
import json
import boto3
from dotenv import load_dotenv
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

from library import load_history, save_message

# -----------------------------
# ENV
# -----------------------------
load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
MODEL_ID = os.getenv("BEDROCK_MODEL_ID")
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST")
INDEX_NAME = os.getenv("INDEX_NAME")

# -----------------------------
# AWS clients
# -----------------------------
session = boto3.Session()
credentials = session.get_credentials()

awsauth = AWS4Auth(
    credentials.access_key,
    credentials.secret_key,
    AWS_REGION,
    "es",
    session_token=credentials.token
)

bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=AWS_REGION
)

# -----------------------------
# OpenSearch
# -----------------------------
host = OPENSEARCH_HOST.replace("https://", "").replace("http://", "")

opensearch = OpenSearch(
    hosts=[{"host": host, "port": 443}],
    http_auth=awsauth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)

# -----------------------------
# Embeddings
# -----------------------------
def get_embedding(text):
    body = {"inputText": text[:8000]}

    response = bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json"
    )

    return json.loads(response["body"].read()).get("embedding")

# -----------------------------
# RAG retrieval
# -----------------------------
def retrieve_relevant_chunks(query, top_k=3):
    embedding = get_embedding(query)

    if not embedding:
        return []

    search_body = {
        "size": top_k,
        "query": {
            "knn": {
                "embedding": {
                    "vector": embedding,
                    "k": top_k
                }
            }
        }
    }

    try:
        response = opensearch.search(
            index=INDEX_NAME,
            body=search_body
        )

        hits = response["hits"]["hits"]

        return [
            h["_source"]["text"]
            for h in hits
            if h["_score"] > 0.3
        ]

    except Exception as e:
        print("❌ Retrieval error:", e)
        return []

# -----------------------------
# System prompt
# -----------------------------
SYSTEM_PROMPT = """
You are LUNA, a clinical decision support assistant.

Rules:
- Use retrieved context only if helpful
- Be concise
- Do not hallucinate
"""

# -----------------------------
# history logic
# -----------------------------
def wants_history(user_input):
    keywords = [
        "history", "previous", "trend", "last",
        "evaluation", "this case", "patient"
    ]
    return any(k in user_input.lower() for k in keywords)

# -----------------------------
# Build prompt
# -----------------------------
def build_messages(user_input, patient_id):
    messages = []

    # RAG context
    chunks = retrieve_relevant_chunks(user_input)

    if chunks:
        messages.append({
            "role": "user",
            "content": [{
                "type": "text",
                "text": "Relevant context:\n\n" + "\n\n".join(chunks)
            }]
        })

    # patient history
    if wants_history(user_input):
        history = load_history(patient_id, limit=6)

        messages.append({
            "role": "user",
            "content": [{
                "type": "text",
                "text": json.dumps(history)
            }]
        })

    # question
    messages.append({
        "role": "user",
        "content": [{
            "type": "text",
            "text": user_input
        }]
    })

    return messages

# -----------------------------
# LLM call
# -----------------------------
def call_bedrock(user_input, patient_id):
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

    return json.loads(response["body"].read())["content"][0]["text"]

# -----------------------------
# Chat loop
# -----------------------------
def chat():
    print("LUNA Chatbot")

    patient_id = input("Patient ID: ")
    patient_id = re.sub(r"\D", "", patient_id)

    while True:
        user_input = input("You: ")

        if user_input == "exit":
            break

        response = call_bedrock(user_input, patient_id)

        print("\nLUNA:", response, "\n")

        save_message(patient_id, "user", user_input)
        save_message(patient_id, "assistant", response)


if __name__ == "__main__":
    chat()