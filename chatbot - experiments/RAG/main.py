import os
import re
import json
import boto3
import uuid
from dotenv import load_dotenv
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
from PyPDF2 import PdfReader

# -----------------------------
# ENV
# -----------------------------
load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST")
INDEX_NAME = os.getenv("INDEX_NAME")

# -----------------------------
# AWS
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
# Index setup
# -----------------------------
def setup_opensearch():
    if opensearch.indices.exists(index=INDEX_NAME):
        print("ℹ️ Index already exists")
        return

    mapping = {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                "text": {"type": "text"},
                "source": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 1024
                }
            }
        }
    }

    opensearch.indices.create(index=INDEX_NAME, body=mapping)
    print("✅ Index created")

# -----------------------------
# PDF extraction
# -----------------------------
def extract_text(pdf_path):
    reader = PdfReader(pdf_path)
    return "\n".join([page.extract_text() or "" for page in reader.pages])

# -----------------------------
# Chunking
# -----------------------------
def chunk_text(text, chunk_size=500, overlap=100):
    chunks = []
    step = chunk_size - overlap

    for i in range(0, len(text), step):
        chunks.append(text[i:i + chunk_size])

    return chunks

# -----------------------------
# Embedding
# -----------------------------
def get_embedding(text):
    if not text or len(text.strip()) < 10:
        return None

    try:
        body = {
            "inputText": text[:8000],
            "dimensions": 1024,
            "normalize": True
        }

        response = bedrock.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )

        embedding = json.loads(response["body"].read()).get("embedding")

        if isinstance(embedding, list) and len(embedding) == 1024:
            return embedding

        return None

    except Exception as e:
        print("❌ Embedding error:", e)
        return None

# -----------------------------
# Store chunks
# -----------------------------
def store_chunks(chunks, source_file):

    for i, chunk in enumerate(chunks):
        print(f"Processing chunk {i+1}/{len(chunks)}")

        embedding = get_embedding(chunk)

        if not embedding:
            continue

        doc = {
            "text": chunk,
            "source": source_file,
            "embedding": embedding.copy()
        }

        try:
            opensearch.index(
                index=INDEX_NAME,
                id=str(uuid.uuid4()),
                body=doc
            )
        except Exception as e:
            print("❌ Insert failed:", e)

# -----------------------------
# Clean text
# -----------------------------
def clean_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r'-\n', '', text)
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.encode("ascii", "ignore").decode().strip()

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":

    setup_opensearch()

    pdf_folder = "./pdfs"

    for file in os.listdir(pdf_folder):
        if file.endswith(".pdf"):
            print(f"📄 Processing: {file}")

            path = os.path.join(pdf_folder, file)

            text = extract_text(path)
            text = clean_text(text)
            chunks = chunk_text(text)

            chunks = [c.strip() for c in chunks if len(c.strip()) > 20]

            store_chunks(chunks, file)

    print("✅ Done")