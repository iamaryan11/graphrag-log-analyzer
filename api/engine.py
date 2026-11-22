import json
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from neo4j import GraphDatabase
from pinecone import Pinecone
from api.schemas import RCAReport

load_dotenv()

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "lograg-incident-index"))
neo4j_driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
)

MULTI_HOP_CYPHER = """
UNWIND $trace_keys AS tk
MATCH (t:Trace {id: tk})<-[:ASSOCIATED_WITH]-(e:Event)<-[:EMITTED]-(s:Service)
OPTIONAL MATCH (t)<-[:ASSOCIATED_WITH]-(rel_e:Event)<-[:EMITTED]-(rel_s:Service)
WHERE rel_e <> e
RETURN DISTINCT
       t.id AS trace_key,
       s.name AS primary_service,
       s.domain AS domain,
       e.severity AS severity,
       e.template AS log_template,
       e.root_cause AS root_cause,
       e.resolution AS resolution,
       collect(DISTINCT {
           service: rel_s.name,
           event_template: rel_e.template,
           severity: rel_e.severity
       }) AS cascading_events
LIMIT 10
"""

def retrieve_and_synthesize(query: str, top_k: int = 3) -> tuple[RCAReport, list[str]]:
    # 1. Embed query
    emb_resp = gemini_client.models.embed_content(
        model="gemini-embedding-001",
        contents=query,
        config=types.EmbedContentConfig(output_dimensionality=768),
    )
    query_vector = emb_resp.embeddings[0].values

    # 2. Vector search in Pinecone
    search_res = index.query(vector=query_vector, top_k=top_k, include_metadata=True)
    raw_keys = [m["metadata"].get("trace_key") for m in search_res["matches"] if m.get("metadata")]
    trace_keys = list(dict.fromkeys([k for k in raw_keys if k]))  # Deduplicate!

    # 3. Multi-hop traversal in Neo4j
    with neo4j_driver.session() as session:
        records = session.run(MULTI_HOP_CYPHER, trace_keys=trace_keys).data()

    context_json = json.dumps(records, indent=2) if records else "No matching graph topology found."

    # 4. Structured RCA synthesis via Gemini
    prompt = (
        "You are a Senior Site Reliability Engineer. Analyze the incident query strictly using the "
        "retrieved Hybrid GraphRAG subgraph context below. Do not fabricate services not present in context.\n\n"
        f"SUBGRAPH CONTEXT:\n{context_json}\n\nINCIDENT QUERY:\n{query}"
    )

    llm_resp = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RCAReport,
            temperature=0.2,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

    report = RCAReport.model_validate_json(llm_resp.text)
    return report, trace_keys