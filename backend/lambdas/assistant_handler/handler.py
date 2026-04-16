"""
Assistant Handler — LUNA Virtual AI Assistant (FR-5.x)

POST /assistant/query
  Accepts a natural-language query from the clinician.
  query_type:
    "patient"    → answers questions about a specific patient's history (FR-5.1)
    "population" → aggregates population-level analytics (FR-5.2)

  Pipeline:
    1. Retrieve relevant context from OpenSearch (RAG, FR-5.3)
    2. Build an LLM prompt with patient data + retrieved documents
    3. Invoke LLM (SageMaker endpoint if set, else Amazon Bedrock Claude)
    4. Parse citations from retrieved documents
    5. Save conversation to ChatHistoryTable
    6. Return response + evidence citations (FR-5.3)

GET /patients/{patientId}/chat
  Returns the conversation history for a patient (FR-5.4).
"""

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

dynamodb = boto3.resource("dynamodb")
bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
sagemaker_runtime = boto3.client("sagemaker-runtime")

patients_table = dynamodb.Table(os.environ["PATIENTS_TABLE"])
results_table = dynamodb.Table(os.environ["DIAGNOSTIC_RESULTS_TABLE"])
chat_history_table = dynamodb.Table(os.environ["CHAT_HISTORY_TABLE"])
audit_log_table = dynamodb.Table(os.environ["AUDIT_LOG_TABLE"])

OPENSEARCH_ENDPOINT = os.environ["OPENSEARCH_ENDPOINT"]
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", "luna-docs")
LLM_SAGEMAKER_ENDPOINT = os.environ.get("LLM_SAGEMAKER_ENDPOINT", "")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5")

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Content-Type": "application/json",
}


def lambda_handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}
    user_id = (event.get("requestContext", {}).get("authorizer") or {}).get("userId", "unknown")

    if method == "POST" and path.endswith("/query"):
        return _handle_query(event, user_id)
    if method == "GET" and path.endswith("/chat"):
        return _get_chat_history(path_params.get("patientId", ""), user_id)

    return _resp(404, {"error": "Not found"})


# ── Query handler ─────────────────────────────────────────────────────────

def _handle_query(event: dict, user_id: str):
    body = _parse_body(event)
    query_text = (body.get("query") or "").strip()
    query_type = body.get("queryType", "patient")   # "patient" | "population"
    patient_id = body.get("patientId", "")

    if not query_text:
        return _resp(400, {"error": "query is required"})

    # ── Build context ────────────────────────────────────────────────────
    context_parts = []
    citations = []

    # 1. OpenSearch RAG: retrieve relevant medical literature (FR-5.3)
    rag_docs = _search_opensearch(query_text, top_k=5)
    if rag_docs:
        context_parts.append("## Relevant Medical Literature\n" + "\n".join(
            f"[{i+1}] {d['title']}: {d['excerpt']}"
            for i, d in enumerate(rag_docs)
        ))
        citations = [
            {"index": i + 1, "title": d["title"], "source": d.get("source", ""), "excerpt": d["excerpt"]}
            for i, d in enumerate(rag_docs)
        ]

    # 2. Patient-specific context
    if query_type == "patient" and patient_id:
        patient_context = _build_patient_context(patient_id)
        if patient_context:
            context_parts.append(patient_context)

    # 3. Population analytics context
    if query_type == "population":
        population_context = _build_population_context(query_text)
        if population_context:
            context_parts.append(population_context)

    # ── Call LLM ─────────────────────────────────────────────────────────
    context_text = "\n\n".join(context_parts)
    system_prompt = (
        "You are LUNA, a clinical decision support AI assistant specialised in lung cancer "
        "screening and pulmonary nodule management. You help doctors retrieve patient "
        "information and answer clinical questions. Always cite your sources using the "
        "[N] reference format. Be concise, accurate, and flag any uncertainty explicitly. "
        "Never provide a definitive diagnosis — always recommend clinical judgement."
    )
    response_text = _call_llm(system_prompt, context_text, query_text)

    # ── Save to chat history ──────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    chat_history_table.put_item(Item={
        "patientId": patient_id or "population",
        "timestamp": now,
        "userId": user_id,
        "query": query_text,
        "response": response_text,
        "citations": citations,
        "queryType": query_type,
    })

    _write_audit(user_id, "QUERY_ASSISTANT", "ChatQuery", patient_id or "population")

    return _resp(200, {
        "response": response_text,
        "citations": citations,
        "queryType": query_type,
        "timestamp": now,
    })


# ── Chat history ──────────────────────────────────────────────────────────

def _get_chat_history(patient_id: str, user_id: str):
    if not patient_id:
        return _resp(400, {"error": "patientId is required"})

    resp = chat_history_table.query(
        KeyConditionExpression=Key("patientId").eq(patient_id),
        ScanIndexForward=False,  # newest first
        Limit=50,
    )
    messages = resp.get("Items", [])

    _write_audit(user_id, "VIEW_CHAT_HISTORY", "ChatHistory", patient_id)
    return _resp(200, {
        "patientId": patient_id,
        "messages": messages,
    })


# ── OpenSearch RAG retrieval ──────────────────────────────────────────────

def _search_opensearch(query_text: str, top_k: int = 5) -> list[dict]:
    """
    Sends a multi-match query to the OpenSearch luna-docs index.
    The ML team populates this index with MIMIC-CXR reports, PubMed papers,
    and Fleischner Society guidelines.

    Returns a list of dicts: [{title, excerpt, source}]
    """
    if not OPENSEARCH_ENDPOINT:
        return []

    search_body = json.dumps({
        "query": {
            "multi_match": {
                "query": query_text,
                "fields": ["title^2", "content", "abstract"],
                "type": "best_fields",
                "fuzziness": "AUTO",
            }
        },
        "size": top_k,
        "_source": ["title", "content", "abstract", "source", "doi"],
    }).encode("utf-8")

    url = f"https://{OPENSEARCH_ENDPOINT}/{OPENSEARCH_INDEX}/_search"

    try:
        session = boto3.session.Session()
        credentials = session.get_credentials().get_frozen_credentials()
        region = os.environ.get("AWS_REGION", "us-east-1")

        request = AWSRequest(method="POST", url=url, data=search_body,
                             headers={"Content-Type": "application/json"})
        SigV4Auth(credentials, "es", region).add_auth(request)

        req = urllib.request.Request(
            url,
            data=search_body,
            headers=dict(request.headers),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())

        docs = []
        for hit in result.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            content = src.get("content") or src.get("abstract") or ""
            docs.append({
                "title": src.get("title", "Untitled"),
                "excerpt": content[:300] + "..." if len(content) > 300 else content,
                "source": src.get("source") or src.get("doi", ""),
            })
        return docs
    except Exception as exc:
        print(f"OpenSearch query failed: {exc}")
        return []


# ── Patient context ───────────────────────────────────────────────────────

def _build_patient_context(patient_id: str) -> str:
    """Assembles a text summary of the patient record and latest result."""
    try:
        patient_resp = patients_table.get_item(Key={"patientId": patient_id})
        patient = patient_resp.get("Item")
        if not patient:
            return ""

        lines = [
            f"## Patient Record (ID: {patient_id})",
            f"Name: {patient.get('name', 'N/A')}",
            f"Age: {patient.get('age', 'N/A')}",
            f"Smoking history: {patient.get('smokingHistory', 'N/A')} "
            f"({patient.get('packYears', 0)} pack-years)",
            f"Family history of lung cancer: {patient.get('familyHistory', False)}",
            f"Current LUNA Risk Score: {patient.get('lastLunaRiskScore', 'Not yet assessed')}",
            f"Current status: {patient.get('status', 'Unknown')}",
        ]

        # Latest diagnostic result
        result_resp = results_table.query(
            IndexName="PatientIdIndex",
            KeyConditionExpression=Key("patientId").eq(patient_id),
            ScanIndexForward=False,
            Limit=1,
        )
        results = result_resp.get("Items", [])
        if results:
            r = results[0]
            lines.append(f"\n## Most Recent Diagnostic Result ({r.get('createdAt', '')})")
            lines.append(f"LUNA Risk Score: {r.get('lunaRiskScore', 'N/A')}")
            lines.append(f"Nodules detected: {len(r.get('nodulesDetected', []))}")
            if r.get("clinicalSummary"):
                lines.append(f"Summary: {r['clinicalSummary']}")

        return "\n".join(lines)
    except Exception as exc:
        print(f"Failed to build patient context: {exc}")
        return ""


# ── Population analytics ──────────────────────────────────────────────────

def _build_population_context(query_text: str) -> str:
    """
    Scans the patients table to provide aggregate statistics for
    population-level NL queries (FR-5.2).
    e.g. "Show me all patients over 60 with Stage 1 nodules"
    """
    try:
        resp = patients_table.scan(
            ProjectionExpression="patientId, #nm, age, #st, lastLunaRiskScore, smokingHistory",
            ExpressionAttributeNames={"#nm": "name", "#st": "status"},
        )
        patients = resp.get("Items", [])
        while "LastEvaluatedKey" in resp:
            resp = patients_table.scan(
                ProjectionExpression="patientId, #nm, age, #st, lastLunaRiskScore, smokingHistory",
                ExpressionAttributeNames={"#nm": "name", "#st": "status"},
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            patients.extend(resp.get("Items", []))

        total = len(patients)
        high_risk = sum(
            1 for p in patients
            if float(p.get("lastLunaRiskScore") or 0) >= 70
        )
        pending = sum(1 for p in patients if p.get("status") == "PENDING_ANALYSIS")
        current_smokers = sum(
            1 for p in patients if p.get("smokingHistory") == "current"
        )

        lines = [
            "## Hospital Population Summary",
            f"Total patients: {total}",
            f"High-risk patients (score ≥70): {high_risk}",
            f"Pending analysis: {pending}",
            f"Current smokers: {current_smokers}",
            "",
            "## Patient List (top 20 by risk)",
        ]

        patients.sort(key=lambda p: float(p.get("lastLunaRiskScore") or 0), reverse=True)
        for p in patients[:20]:
            lines.append(
                f"- {p.get('name', 'N/A')} (ID: {p['patientId']}) | "
                f"Age: {p.get('age', 'N/A')} | "
                f"Risk: {p.get('lastLunaRiskScore', 'N/A')} | "
                f"Status: {p.get('status', 'N/A')}"
            )

        return "\n".join(lines)
    except Exception as exc:
        print(f"Failed to build population context: {exc}")
        return ""


# ── LLM call ──────────────────────────────────────────────────────────────

def _call_llm(system_prompt: str, context: str, query: str) -> str:
    """
    Calls the LLM.  Priority:
      1. If LLM_SAGEMAKER_ENDPOINT is set → use the ML team's deployed LLM
      2. Otherwise → use Amazon Bedrock Claude (Haiku by default)
    """
    if LLM_SAGEMAKER_ENDPOINT:
        return _call_sagemaker_llm(system_prompt, context, query)
    return _call_bedrock(system_prompt, context, query)


def _call_sagemaker_llm(system_prompt: str, context: str, query: str) -> str:
    """Invokes a custom LLM deployed on SageMaker by the ML team."""
    payload = json.dumps({
        "system": system_prompt,
        "context": context,
        "query": query,
        "max_tokens": 1024,
    }).encode("utf-8")
    try:
        resp = sagemaker_runtime.invoke_endpoint(
            EndpointName=LLM_SAGEMAKER_ENDPOINT,
            ContentType="application/json",
            Body=payload,
        )
        result = json.loads(resp["Body"].read())
        return result.get("response") or result.get("generated_text") or str(result)
    except Exception as exc:
        print(f"SageMaker LLM call failed: {exc}. Falling back to Bedrock.")
        return _call_bedrock(system_prompt, context, query)


def _call_bedrock(system_prompt: str, context: str, query: str) -> str:
    """Invokes Amazon Bedrock Claude as the LLM fallback."""
    user_message = f"{context}\n\n---\n\nQuestion: {query}" if context else query

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    })

    try:
        resp = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        result = json.loads(resp["body"].read())
        return result["content"][0]["text"]
    except Exception as exc:
        print(f"Bedrock call failed: {exc}")
        return (
            "I'm unable to process your query at this time. "
            "Please try again or contact technical support."
        )


# ── Helpers ───────────────────────────────────────────────────────────────

def _write_audit(user_id: str, action: str, resource_type: str, resource_id: str):
    try:
        now = datetime.now(timezone.utc).isoformat()
        audit_log_table.put_item(Item={
            "logId": str(uuid.uuid4()),
            "timestamp": now,
            "userId": user_id,
            "action": action,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "statusCode": 200,
        })
    except Exception:
        pass


def _parse_body(event: dict) -> dict:
    try:
        return json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": CORS,
        "body": json.dumps(body, default=str),
    }
