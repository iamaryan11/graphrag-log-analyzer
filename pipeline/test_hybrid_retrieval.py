import os
import json
from google import genai
from google.genai import types
from pinecone import Pinecone
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


gemini_client = genai.Client(api_key=GEMINI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
pinecone_index = pc.Index("lograg-incident-index")
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))


def step1_vector_search(query_text: str, top_k: int = 3):
    """Generates query embedding and retrieves top-k vectors + trace_keys from Pinecone."""
    print(f"\n[1/3] Generating query embedding via Gemini SDK...")
    emb_res = gemini_client.models.embed_content(
        model="gemini-embedding-001",
        contents=query_text,
        config=types.EmbedContentConfig(output_dimensionality=768)
    )
    query_vector = emb_res.embeddings[0].values

    print(f"[1/3] Executing vector similarity search in Pinecone...")
    pinecone_res = pinecone_index.query(
        vector=query_vector,
        top_k=top_k,
        include_metadata=True
    )

    matches = pinecone_res.get("matches", [])
    extracted_traces = []

    for match in matches:
        meta = match.get("metadata", {})
        extracted_traces.append({
            "vector_id": match["id"],
            "score": round(match["score"], 4),
            "trace_key": meta.get("trace_key"),
            "symptom_text": meta.get("text_to_embed"),
            "dataset": meta.get("dataset")
        })
    return extracted_traces


def step2_multihop_graph_traversal(trace_key: str):
    """
    Executes a 3-hop Cypher traversal in Neo4j:
      Hop 1: Trace -> Primary Event & Emitting Service
      Hop 2: Trace -> Co-occurring Events & Services (Cascading Failures)
      Hop 3: Event -> Total Affected Traces (Blast Radius)
    """
    print(f"[2/3] Executing multi-hop Neo4j traversal for trace_key: '{trace_key}'...")

    cypher_query = """
    MATCH (t:Trace {id: $trace_key})<-[:ASSOCIATED_WITH]-(e:Event)<-[:EMITTED]-(s:Service)

    // Hop 2: Discover co-occurring events & services in the same trace
    OPTIONAL MATCH (t)<-[:ASSOCIATED_WITH]-(co_event:Event)<-[:EMITTED]-(co_service:Service)
    WHERE co_event <> e

    // Hop 3: Measure global blast radius of this event template across all traces
    OPTIONAL MATCH (e)-[:ASSOCIATED_WITH]->(all_traces:Trace)

    WITH s, e, t,
         count(DISTINCT all_traces) AS trace_blast_radius,
         collect(DISTINCT {
             service: co_service.name,
             event_template: co_event.template,
             severity: co_event.severity,
             root_cause: co_event.root_cause
         }) AS raw_cascading

    RETURN s.name AS primary_service,
           s.domain AS system_domain,
           e.template AS log_template,
           e.severity AS severity,
           e.root_cause AS root_cause,
           e.resolution AS resolution,
           e.remediation_type AS remediation_type,
           t.id AS trace_key,
           trace_blast_radius,
           [item IN raw_cascading WHERE item.event_template IS NOT NULL][0..5] AS cascading_events
    LIMIT 3
    """

    hop_results = []
    with neo4j_driver.session() as session:
        records = session.run(cypher_query, trace_key=trace_key)
        for record in records:
            hop_results.append({
                "trace_key": record["trace_key"],
                "primary_service": record["primary_service"],
                "domain": record["system_domain"],
                "severity": record["severity"],
                "log_template": record["log_template"],
                "root_cause": record["root_cause"],
                "resolution": record["resolution"],
                "remediation_type": record["remediation_type"],
                "trace_blast_radius": record["trace_blast_radius"],
                "cascading_events": record["cascading_events"]
            })
    return hop_results


def step3_synthesize_incident_report(user_query: str, vector_matches: list, graph_contexts: list):
    """Passes merged Vector + Multi-Hop Graph Context to Gemini LLM."""
    print(f"\n[3/3] Synthesizing incident report with Gemini LLM...")

    prompt = f"""
    You are an expert SRE Incident Response AI Assistant. Analyze the incident query below using evidence retrieved from our Hybrid Vector + Multi-Hop Knowledge Graph system.

    INCIDENT QUERY:
    "{user_query}"

    RETRIEVED VECTOR SIMILARITY CONTEXT (Pinecone):
    {json.dumps(vector_matches, indent=2)}

    RETRIEVED MULTI-HOP SYSTEM TOPOLOGY & CASCADING GRAPH CONTEXT (Neo4j):
    {json.dumps(graph_contexts, indent=2)}

    Provide a concise, grounded SRE Incident Report containing:
    1. Incident Summary & Root Cause Analysis
    2. Affected Microservice Topology & Cascading Chain (explicitly cite co-occurring services/events and trace blast radius if present)
    3. Step-by-Step Remediation Plan
    """

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
    )
    return response.text


def execute_hybrid_test(test_query: str):
    print("=" * 65)
    print("TESTING MULTI-HOP HYBRID GRAPHRAG PIPELINE (UPGRADE 1)")
    print(f"Query: '{test_query}'")
    print("=" * 65)


    vector_results = step1_vector_search(test_query, top_k=3)
    if not vector_results:
        print("No matches found in Pinecone.")
        return


    graph_results = []
    for match in vector_results:
        trace_key = match.get("trace_key")
        if trace_key:
            hops = step2_multihop_graph_traversal(trace_key)
            graph_results.extend(hops)

    print("\n--- MULTI-HOP NEO4J SUBGRAPH PAYLOAD ---")
    print(json.dumps(graph_results, indent=2))

    report = step3_synthesize_incident_report(test_query, vector_results, graph_results)

    print("\n" + "=" * 65)
    print("FINAL SYNTHESIZED INCIDENT REPORT")
    print("=" * 65)
    print(report)


if __name__ == "__main__":
    sample_incident = "Instance failed to spawn and network vif plugging timed out"
    execute_hybrid_test(sample_incident)

    neo4j_driver.close()