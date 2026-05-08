import os
import json
import boto3
import pdfplumber
from dotenv import load_dotenv
from requests_aws4auth import AWS4Auth
from opensearchpy import OpenSearch, RequestsHttpConnection

load_dotenv()

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST").strip()
INDEX = "luna-docs"
VECTOR_DIM = 1024
AWS_REGION = "eu-west-1"

# ----------------------------
# AWS AUTH
# ----------------------------
session = boto3.Session()
credentials = session.get_credentials()

awsauth = AWS4Auth(
    credentials.access_key,
    credentials.secret_key,
    AWS_REGION,
    "es",
    session_token=credentials.token
)

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

# ----------------------------
# OpenSearch client
# ----------------------------
client = OpenSearch(
    hosts=[{"host": OPENSEARCH_HOST, "port": 443}],
    http_auth=awsauth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection,
)

# ----------------------------
# DELETE OLD INDEX
# ----------------------------
def delete_index():
    try:
        if client.indices.exists(INDEX):
            print("Deleting old index...")
            client.indices.delete(index=INDEX)
    except Exception as e:
        print("Delete index error:", e)

# ----------------------------
# CREATE INDEX
# ----------------------------
def create_index():
    client.indices.create(
        index=INDEX,
        body={
            "settings": {
                "index": {
                    "knn": True
                }
            },
            "mappings": {
                "properties": {
                    "text": {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": VECTOR_DIM
                    },
                    "source": {"type": "keyword"},
                    "chunk_id": {"type": "integer"}
                }
            }
        }
    )

# ----------------------------
# EMBEDDING (TITAN)
# ----------------------------
def get_embedding(text):
    body = {"inputText": text[:8000]}

    response = bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json"
    )

    return json.loads(response["body"].read())["embedding"]

# ----------------------------
# PDF
# ----------------------------
def extract_text(path):
    text = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text.append(t)
    return "\n".join(text)

# ----------------------------
# CHUNK
# ----------------------------
def chunk(text, size=500):
    words = text.split()
    return [" ".join(words[i:i+size]) for i in range(0, len(words), size)]

# ----------------------------
# INGEST
# ----------------------------
def seed(folder="./rag_docs"):
    delete_index()
    create_index()

    for file in os.listdir(folder):
        if not file.endswith(".pdf"):
            continue

        path = os.path.join(folder, file)
        print("Processing:", file)

        text = extract_text(path)
        if not text.strip():
            continue

        chunks = chunk(text)

        for i, c in enumerate(chunks):
            embedding = get_embedding(c)

            client.index(
                index=INDEX,
                body={
                    "text": c,
                    "embedding": embedding,
                    "source": file,
                    "chunk_id": i
                }
            )

    print("✅ Opensearch Seeding Complete")

if __name__ == "__main__":
    seed("./rag_docs")