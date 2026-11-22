import time
from fastapi import FastAPI, HTTPException
from api.schemas import DiagnoseRequest, DiagnoseResponse
from api.guardrails import validate_user_query, enforce_remediation_guardrails
from api.engine import retrieve_and_synthesize, index, neo4j_driver

app = FastAPI(
    title="Context-Aware AI Log Analyzer & Incident Responder",
    description="Hybrid GraphRAG (Pinecone + Neo4j + Gemini) SRE Diagnostic API",
    version="1.0.0",
)

@app.get("/health")
def health_check():
    stats = index.describe_index_stats()
    with neo4j_driver.session() as session:
        node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    return {
        "status": "ok",
        "pinecone_vectors": stats.get("total_vector_count", 0),
        "neo4j_nodes": node_count,
    }

@app.post("/api/v1/diagnose", response_model=DiagnoseResponse)
def diagnose_incident(request: DiagnoseRequest):
    start = time.perf_counter()

    is_valid, reason = validate_user_query(request.query)
    if not is_valid:
        raise HTTPException(status_code=400, detail=reason)

    raw_report, trace_keys = retrieve_and_synthesize(request.query, request.top_k)

    safe_report, alerts = enforce_remediation_guardrails(raw_report)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    return DiagnoseResponse(
        status="flagged" if alerts else "verified",
        latency_ms=latency_ms,
        guardrail_alerts=alerts,
        retrieved_traces=trace_keys,
        rca_report=safe_report,
    )