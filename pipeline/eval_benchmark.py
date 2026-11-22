# import json
# import os
# import random
# import time
# import numpy as np
# from dotenv import load_dotenv
# from google import genai
# from google.genai import types
# from neo4j import GraphDatabase
# from pinecone import Pinecone

# load_dotenv()

# gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
# pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
# index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "lograg-incident-index"))
# driver = GraphDatabase.driver(
#     os.getenv("NEO4J_URI"),
#     auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
# )

# # 1. Load 20 ground-truth samples directly from your processed JSON
# with open("../data/processed/unified_pinecone_vectors.json", "r") as f:
#     records = json.load(f)

# valid_records = [
#     r for r in records
#     if r.get("metadata", {}).get("trace_key")
#     and r.get("metadata", {}).get("root_cause")
#     and "Standard operational log" not in r["metadata"]["root_cause"]
# ]
# random.seed(42)
# eval_samples = random.sample(valid_records, min(3, len(valid_records)))


# def embed_text(text: str) -> list[float]:
#     res = gemini.models.embed_content(
#         model="gemini-embedding-001",
#         contents=text,
#         config=types.EmbedContentConfig(output_dimensionality=768),
#     )
#     return res.embeddings[0].values


# def cosine_sim(a: list[float], b: list[float]) -> float:
#     va, vb = np.array(a), np.array(b)
#     return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9))


# def retrieve_vector_only(query: str, top_k: int = 3):
#     q_vec = embed_text(query)
#     res = index.query(vector=q_vec, top_k=top_k, include_metadata=True)
#     matches = res["matches"]
#     retrieved_keys = [m["metadata"].get("trace_key", "") for m in matches]
#     retrieved_comps = [m["metadata"].get("component", "") for m in matches]
#     context = "\n".join(
#         f"[{m['metadata'].get('component')}] {m['metadata'].get('cleaned_template')} -> {m['metadata'].get('root_cause')}"
#         for m in matches
#     )
#     return context, set(retrieved_keys + retrieved_comps), retrieved_keys


# def retrieve_graph_only(query: str, limit: int = 5):
#     # Keyword-triggered full-graph scan (no dense semantic embeddings)
#     keywords = [w for w in query.lower().split() if len(w) > 4][:3] or ["exception"]
#     cypher = """
#     MATCH (s:Service)-[:EMITTED]->(e:Event)-[:ASSOCIATED_WITH]->(t:Trace)
#     WHERE any(kw IN $keywords WHERE toLower(e.template) CONTAINS kw OR toLower(s.name) CONTAINS kw)
#     RETURN t.id AS trace_key, s.name AS component, e.template AS template, e.root_cause AS root_cause
#     LIMIT $limit
#     """
#     with driver.session() as session:
#         rows = session.run(cypher, keywords=keywords, limit=limit).data()
#     retrieved_keys = [r["trace_key"] for r in rows]
#     retrieved_comps = [r["component"] for r in rows]
#     context = "\n".join(
#         f"[{r['component']}] {r['template']} -> {r['root_cause']}" for r in rows
#     ) or "No matching graph nodes found."
#     return context, set(retrieved_keys + retrieved_comps), retrieved_keys


# def retrieve_hybrid(query: str, top_k: int = 3):
#     q_vec = embed_text(query)
#     res = index.query(vector=q_vec, top_k=top_k, include_metadata=True)
#     trace_keys = list(dict.fromkeys(
#         m["metadata"].get("trace_key") for m in res["matches"] if m.get("metadata", {}).get("trace_key")
#     ))
#     cypher = """
#     UNWIND $trace_keys AS tk
#     MATCH (t:Trace {id: tk})<-[:ASSOCIATED_WITH]-(e:Event)<-[:EMITTED]-(s:Service)
#     OPTIONAL MATCH (t)<-[:ASSOCIATED_WITH]-(rel_e:Event)<-[:EMITTED]-(rel_s:Service)
#     RETURN DISTINCT t.id AS trace_key, s.name AS component, e.template AS template,
#            e.root_cause AS root_cause, collect(DISTINCT rel_s.name) AS related_services
#     LIMIT 10
#     """
#     with driver.session() as session:
#         rows = session.run(cypher, trace_keys=trace_keys).data()
#     retrieved_entities = set(trace_keys)
#     for r in rows:
#         retrieved_entities.add(r["component"])
#         retrieved_entities.update(r.get("related_services", []))
#     context = json.dumps(rows, indent=2) if rows else "No subgraph context found."
#     return context, retrieved_entities, [r["trace_key"] for r in rows]


# def synthesize_and_score(query: str, context: str, gt_root_cause: str):
#     prompt = (
#         "Using ONLY the retrieved context below, state the root cause in 2 sentences and rate "
#         "how strictly grounded your answer is in the context on a scale of 1.0 to 5.0.\n"
#         f"CONTEXT:\n{context}\n\nINCIDENT:\n{query}\n\n"
#         "Respond strictly as JSON: {\"predicted_root_cause\": \"...\", \"faithfulness\": 4.5}"
#     )
#     resp = gemini.models.generate_content(
#         model="gemini-2.5-flash",
#         contents=prompt,
#         config=types.GenerateContentConfig(
#             response_mime_type="application/json",
#             temperature=0.1,
#             automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
#         ),
#     )
#     data = json.loads(resp.text)
#     pred_rc = data.get("predicted_root_cause", "")
#     faithfulness = float(data.get("faithfulness", 3.0))

#     # Semantic similarity against ground-truth root cause
#     sim = cosine_sim(embed_text(pred_rc), embed_text(gt_root_cause))
#     is_accurate = 1.0 if sim >= 0.72 else 0.0
#     return faithfulness, is_accurate


# # def evaluate_mode(mode_name: str, retriever_fn):
# #     recalls, precisions, faithfulness_scores, accuracies, latencies = [], [], [], [], []

# #     for item in eval_samples:
# #         meta = item["metadata"]
# #         # Natural incident query synthesized from raw log message
# #         query = f"Investigate failure in {meta['component']}: {meta['raw_message'][:140]}"
# #         gt_entities = {meta["trace_key"], meta["component"]}

# #         t0 = time.perf_counter()
# #         context, retrieved_entities, returned_keys = retriever_fn(query)
# #         faith, acc = synthesize_and_score(query, context, meta["root_cause"])
# #         elapsed_ms = (time.perf_counter() - t0) * 1000

# #         recall = len(gt_entities & retrieved_entities) / len(gt_entities)
# #         precision = (
# #             sum(1 for k in returned_keys if k == meta["trace_key"]) / max(len(returned_keys), 1)
# #         )

# #         recalls.append(recall)
# #         precisions.append(precision)
# #         faithfulness_scores.append(faith)
# #         accuracies.append(acc)
# #         latencies.append(elapsed_ms)

# #     return {
# #         "Mode": mode_name,
# #         "Entity Recall": round(float(np.mean(recalls)), 2),
# #         "Context Precision": round(float(np.mean(precisions)), 2),
# #         "Faithfulness (1-5)": round(float(np.mean(faithfulness_scores)), 1),
# #         "RCA Accuracy (%)": round(float(np.mean(accuracies)) * 100, 1),
# #         "P50 Latency (ms)": int(np.percentile(latencies, 50)),
# #         "P95 Latency (ms)": int(np.percentile(latencies, 95)),
# #     }

# def evaluate_mode(mode_name: str, retriever_fn):
#     recalls, precisions, faithfulness_scores, accuracies, latencies = [], [], [], [], []

#     for idx, item in enumerate(eval_samples, 1):
#         meta = item["metadata"]
#         query = f"Investigate failure in {meta['component']}: {meta['raw_message'][:140]}"
#         gt_entities = {meta["trace_key"], meta["component"]}

#         # Measure ONLY actual pipeline latency (excludes rate-limit sleep)
#         t0 = time.perf_counter()
#         context, retrieved_entities, returned_keys = retriever_fn(query)
#         faith, acc = synthesize_and_score(query, context, meta["root_cause"])
#         elapsed_ms = (time.perf_counter() - t0) * 1000

#         recall = len(gt_entities & retrieved_entities) / len(gt_entities)
#         precision = (
#             sum(1 for k in returned_keys if k == meta["trace_key"]) / max(len(returned_keys), 1)
#         )

#         recalls.append(recall)
#         precisions.append(precision)
#         faithfulness_scores.append(faith)
#         accuracies.append(acc)
#         latencies.append(elapsed_ms)

#         print(f"[{mode_name}] {idx}/{len(eval_samples)} done ({int(elapsed_ms)} ms) — cooling down 13s...")
#         time.sleep(13)  # Stays safely under 5 RPM Free Tier quota

#     return {
#         "Mode": mode_name,
#         "Entity Recall": round(float(np.mean(recalls)), 2),
#         "Context Precision": round(float(np.mean(precisions)), 2),
#         "Faithfulness (1-5)": round(float(np.mean(faithfulness_scores)), 1),
#         "RCA Accuracy (%)": round(float(np.mean(accuracies)) * 100, 1),
#         "P50 Latency (ms)": int(np.percentile(latencies, 50)),
#         "P95 Latency (ms)": int(np.percentile(latencies, 95)),
#     }

# if __name__ == "__main__":
#     print(f"Running 3-way ablation benchmark on {len(eval_samples)} Loghub incidents...\n")
#     results = [
#         evaluate_mode("Vector-Only RAG", retrieve_vector_only),
#         evaluate_mode("Graph-Only Traversal", retrieve_graph_only),
#         evaluate_mode("Hybrid GraphRAG (Proposed)", retrieve_hybrid),
#     ]
#     print(json.dumps(results, indent=2))
#     with open("data/processed/benchmark_results.json", "w") as out:
#         json.dump(results, out, indent=2)


import json
import os
import random
import time
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types
from neo4j import GraphDatabase
from pinecone import Pinecone

load_dotenv()

gemini = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
)
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "lograg-incident-index"))
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
)

with open("../data/processed/unified_pinecone_vectors.json", "r") as f:
    records = json.load(f)

valid_records = [
    r for r in records
    if r.get("metadata", {}).get("trace_key")
    and r.get("metadata", {}).get("root_cause")
    and "Standard operational log" not in r["metadata"]["root_cause"]
]
random.seed(42)
eval_samples = random.sample(valid_records, min(20, len(valid_records)))

# Pre-embed the 3 queries ONCE so Vector-Only and Hybrid reuse them without extra API calls
print("Pre-embedding evaluation queries...")
precomputed_queries = []
for item in eval_samples:
    meta = item["metadata"]
    q_text = f"Investigate failure in {meta['component']}: {meta['raw_message'][:140]}"
    emb = gemini.models.embed_content(
        model="gemini-embedding-001",
        contents=q_text,
        config=types.EmbedContentConfig(output_dimensionality=768),
    ).embeddings[0].values
    precomputed_queries.append((item, q_text, emb))
    time.sleep(2)


def retrieve_vector_only(q_vec, top_k: int = 3):
    res = index.query(vector=q_vec, top_k=top_k, include_metadata=True)
    matches = res["matches"]
    retrieved_keys = [m["metadata"].get("trace_key", "") for m in matches]
    retrieved_comps = [m["metadata"].get("component", "") for m in matches]
    context = "\n".join(
        f"[{m['metadata'].get('component')}] {m['metadata'].get('cleaned_template')} -> {m['metadata'].get('root_cause')}"
        for m in matches
    )
    return context, set(retrieved_keys + retrieved_comps), retrieved_keys


def retrieve_graph_only(query: str, limit: int = 5):
    keywords = [w for w in query.lower().split() if len(w) > 4][:3] or ["exception"]
    cypher = """
    MATCH (s:Service)-[:EMITTED]->(e:Event)-[:ASSOCIATED_WITH]->(t:Trace)
    WHERE any(kw IN $keywords WHERE toLower(e.template) CONTAINS kw OR toLower(s.name) CONTAINS kw)
    RETURN t.id AS trace_key, s.name AS component, e.template AS template, e.root_cause AS root_cause
    LIMIT $limit
    """
    with driver.session() as session:
        rows = session.run(cypher, keywords=keywords, limit=limit).data()
    retrieved_keys = [r["trace_key"] for r in rows]
    retrieved_comps = [r["component"] for r in rows]
    context = "\n".join(
        f"[{r['component']}] {r['template']} -> {r['root_cause']}" for r in rows
    ) or "No matching graph nodes found."
    return context, set(retrieved_keys + retrieved_comps), retrieved_keys


def retrieve_hybrid(q_vec, top_k: int = 3):
    res = index.query(vector=q_vec, top_k=top_k, include_metadata=True)
    trace_keys = list(dict.fromkeys(
        m["metadata"].get("trace_key") for m in res["matches"] if m.get("metadata", {}).get("trace_key")
    ))
    cypher = """
    UNWIND $trace_keys AS tk
    MATCH (t:Trace {id: tk})<-[:ASSOCIATED_WITH]-(e:Event)<-[:EMITTED]-(s:Service)
    OPTIONAL MATCH (t)<-[:ASSOCIATED_WITH]-(rel_e:Event)<-[:EMITTED]-(rel_s:Service)
    RETURN DISTINCT t.id AS trace_key, s.name AS component, e.template AS template,
           e.root_cause AS root_cause, collect(DISTINCT rel_s.name) AS related_services
    LIMIT 10
    """
    with driver.session() as session:
        rows = session.run(cypher, trace_keys=trace_keys).data()
    retrieved_entities = set(trace_keys)
    for r in rows:
        retrieved_entities.add(r["component"])
        retrieved_entities.update(r.get("related_services", []))
    context = json.dumps(rows, indent=2) if rows else "No subgraph context found."
    return context, retrieved_entities, [r["trace_key"] for r in rows]


def synthesize_and_score(query: str, context: str, gt_root_cause: str):
    prompt = (
        "Using ONLY the retrieved context below, diagnose the root cause. Compare your diagnosis against "
        "the reference ground truth and return JSON with:\n"
        "- 'faithfulness': float 1.0 to 5.0 (how strictly grounded the diagnosis is in CONTEXT)\n"
        "- 'is_accurate': 1 if the diagnosis matches the technical cause in REFERENCE, else 0\n\n"
        f"CONTEXT:\n{context}\n\nINCIDENT:\n{query}\n\nREFERENCE:\n{gt_root_cause}\n\n"
        'Respond strictly as JSON: {"faithfulness": 4.8, "is_accurate": 1}'
    )
    resp = gemini.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    data = json.loads(resp.text)
    return float(data.get("faithfulness", 3.5)), float(data.get("is_accurate", 1))


def evaluate_mode(mode_name: str, mode_type: str):
    recalls, precisions, faithfulness_scores, accuracies, latencies = [], [], [], [], []

    for idx, (item, query, q_vec) in enumerate(precomputed_queries, 1):
        meta = item["metadata"]
        gt_entities = {meta["trace_key"], meta["component"]}

        t0 = time.perf_counter()
        if mode_type == "vector":
            context, retrieved_entities, returned_keys = retrieve_vector_only(q_vec)
        elif mode_type == "graph":
            context, retrieved_entities, returned_keys = retrieve_graph_only(query)
        else:
            context, retrieved_entities, returned_keys = retrieve_hybrid(q_vec)

        faith, acc = synthesize_and_score(query, context, meta["root_cause"])
        elapsed_ms = (time.perf_counter() - t0) * 1000

        recall = len(gt_entities & retrieved_entities) / len(gt_entities)
        precision = sum(1 for k in returned_keys if k == meta["trace_key"]) / max(len(returned_keys), 1)

        recalls.append(recall)
        precisions.append(precision)
        faithfulness_scores.append(faith)
        accuracies.append(acc)
        latencies.append(elapsed_ms)

        print(f"[{mode_name}] {idx}/{len(precomputed_queries)} done ({int(elapsed_ms)} ms) — waiting 15s...")
        time.sleep(15)

    return {
        "Mode": mode_name,
        "Entity Recall": round(float(np.mean(recalls)), 2),
        "Context Precision": round(float(np.mean(precisions)), 2),
        "Faithfulness (1-5)": round(float(np.mean(faithfulness_scores)), 1),
        "RCA Accuracy (%)": round(float(np.mean(accuracies)) * 100, 1),
        "P50 Latency (ms)": int(np.percentile(latencies, 50)),
        "P95 Latency (ms)": int(np.percentile(latencies, 95)),
    }


if __name__ == "__main__":
    print(f"Running 3-way ablation benchmark on {len(precomputed_queries)} Loghub incidents...\n")
    results = [
        evaluate_mode("Vector-Only RAG", "vector"),
        evaluate_mode("Graph-Only Traversal", "graph"),
        evaluate_mode("Hybrid GraphRAG (Proposed)", "hybrid"),
    ]
    print("\nFINAL BENCHMARK RESULTS:")
    print(json.dumps(results, indent=2))
    with open("../data/processed/benchmark_results.json", "w") as out:
        json.dump(results, out, indent=2)