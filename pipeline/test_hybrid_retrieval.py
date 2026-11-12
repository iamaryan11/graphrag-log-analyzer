import os
import json
from google import genai
from google.genai import types
from pinecone import Pinecone
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# Environment Credentials
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# Initialize Clients
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
            "score": match["score"],
            "trace_key": meta.get("trace_key"),
            "symptom_text": meta.get("text_to_embed"),
            "dataset": meta.get("dataset")
        })
    return extracted_traces


def step2_graph_traversal(trace_key: str):
    """Queries Neo4j topology graph using the trace_key extracted from Pinecone."""
    print(f"[2/3] Querying Neo4j topology for trace_key: '{trace_key}'...")
    
    cypher_query = """
    MATCH (t:Trace {id: $trace_key})<-[:ASSOCIATED_WITH]-(e:Event)<-[:EMITTED]-(s:Service)
    RETURN s.name AS service_name,
           s.domain AS system_domain,
           e.template AS log_template,
           e.root_cause AS root_cause,
           e.resolution AS resolution,
           e.remediation_type AS remediation_type,
           t.id AS trace_key
    """
    
    with neo4j_driver.session() as session:
        result = session.run(cypher_query, trace_key=trace_key)
        record = result.single()
        
        if record:
            return {
                "service": record["service_name"],
                "domain": record["system_domain"],
                "template": record["log_template"],
                "root_cause": record["root_cause"],
                "resolution": record["resolution"],
                "remediation_type": record["remediation_type"]
            }
        return None


def step3_synthesize_incident_report(user_query: str, vector_matches: list, graph_contexts: list):
    """Passes merged Hybrid Context to Gemini LLM for incident response generation."""
    print(f"[3/3] Synthesizing incident report with Gemini LLM...")
    
    prompt = f"""
    You are an expert SRE Incident Response AI Assistant. Analyze the following incident query using context retrieved from our hybrid Vector + Graph database system.

    INCIDENT QUERY:
    "{user_query}"

    RETRIEVED VECTOR SIMILARITY CONTEXT (Pinecone):
    {json.dumps(vector_matches, indent=2)}

    RETRIEVED SYSTEM TOPOLOGY & GRAPH CONTEXT (Neo4j):
    {json.dumps(graph_contexts, indent=2)}

    Provide a concise SRE Incident Report containing:
    1. Incident Summary & Root Cause Analysis
    2. Affected Microservice Topology
    3. Step-by-Step Remediation Plan
    """

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text


def execute_hybrid_test(test_query: str):
    print("=" * 60)
    print(f"TESTING HYBRID GRAPHRAG RETRIEVAL PIPELINE")
    print(f"Query: '{test_query}'")
    print("=" * 60)

    # 1. Vector Search
    vector_results = step1_vector_search(test_query, top_k=2)
    if not vector_results:
        print("No matches found in Pinecone.")
        return

    # 2. Graph Traversal per top vector result
    graph_results = []
    for match in vector_results:
        trace_key = match.get("trace_key")
        if trace_key:
            g_data = step2_graph_traversal(trace_key)
            if g_data:
                graph_results.append(g_data)

    # 3. LLM Report Generation
    report = step3_synthesize_incident_report(test_query, vector_results, graph_results)
    
    print("\n" + "=" * 60)
    print("FINAL SYNTHESIZED INCIDENT REPORT")
    print("=" * 60)
    print(report)


if __name__ == "__main__":
    # Test with a benchmark error scenario
    sample_incident = "Block verification failure and connection timeout in storage service"
    execute_hybrid_test(sample_incident)
    
    neo4j_driver.close()