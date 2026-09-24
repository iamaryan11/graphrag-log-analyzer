import json
import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

URI = NEO4J_URI
AUTH = ("neo4j", NEO4J_PASSWORD)  

def seed_graph_database(json_file_path: str):
    with open(json_file_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    driver = GraphDatabase.driver(URI, auth=AUTH)

    cypher_query = """
    UNWIND $batch AS row
    
    // 1. Merge Service Node
    MERGE (s:Service {name: row.metadata.component, domain: row.metadata.dataset})
    
    // 2. Merge Event Node
    MERGE (e:Event {template: row.metadata.cleaned_template})
    ON CREATE SET e.severity = row.metadata.severity,
                  e.root_cause = row.metadata.root_cause,
                  e.resolution = row.metadata.resolution,
                  e.remediation_type = row.metadata.remediation_type
                  
    // 3. Merge Trace Node (Block ID or Request ID)
    MERGE (t:Trace {id: row.metadata.trace_key, domain: row.metadata.dataset})
    
    // 4. Create Relationships
    MERGE (s)-[:EMITTED]->(e)
    MERGE (e)-[:ASSOCIATED_WITH]->(t)
    """

    with driver.session() as session:
        print("Seeding Neo4j nodes and relationships...")
        session.run(cypher_query, batch=records)
        print("Ingestion complete!")

    driver.close()

if __name__ == "__main__":
    seed_graph_database("../data/processed/unified_pinecone_vectors.json")