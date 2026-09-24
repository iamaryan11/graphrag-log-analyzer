# graphrag-log-analyzer

> **Context-Aware AI Log Analyser and DevOps Incident Responder using Hybrid GraphRAG**

An enterprise-grade SRE incident response pipeline that combines **Semantic Vector Search (Pinecone)** and **Structural Graph Topology (Neo4j)** to analyze log failures, map failure blast radiuses, and deliver automated SRE runbook root causes and remediation steps.

---

## 📌 Architecture Overview

Standard RAG pipelines often miss structural dependencies across distributed microservices. This system implements a **Hybrid GraphRAG** architecture:

* **Semantic Vector Pillar (Pinecone):** Captures high-dimensional error pattern similarities using Google GenAI embeddings (`gemini-embedding-001`, truncated to 768 dimensions) to map raw log symptoms to SRE runbook solutions.
* **Structural Graph Pillar (Neo4j):** Models microservice topology (`Service -> Event -> Trace`) to provide root-cause attribution and downstream failure impact (blast radius analysis).

---

## 📁 Repository Structure

```text
graphrag-log-analyzer/
├── data/
│   ├── raw/                         # Loghub benchmark CSV files (HDFS_2k, OpenStack_2k)
│   └── processed/                   # Preprocessed unified JSON (unified_pinecone_vectors.json)
│
├── pipeline/
│   ├── process_csv.py               # Parsing, regex masking & SRE runbook enrichment
│   ├── seed_neo4j.py                # Neo4j graph topology seeding script
│   └── upsert_pinecone.py           # Google GenAI embedding generation & Pinecone ingestion
│
├── config/
│   └── .env.example                 # Environment variables template
│
├── .gitignore                       # Prevents committing API keys & virtual envs
├── requirements.txt                 # Project dependencies
└── README.md                        # Project documentation


Component,Technology / Model
Vector Database,"Pinecone (Serverless, Cosine Metric, 768-dim)"
Graph Database,Neo4j Desktop (bolt://localhost:7687)
Embedding Model,Google GenAI gemini-embedding-001 (Matryoshka 768-dim)
Datasets,"Loghub Benchmark (HDFS_2k, OpenStack_2k)"
Language & SDKs,"Python 3.10+, google-genai, pinecone, neo4j, python-dotenv"

🚀 Quickstart & Setup
1. Clone the Repository & Set Up Virtual Environment
Bash
git clone [https://github.com/your-username/graphrag-log-analyzer.git](https://github.com/your-username/graphrag-log-analyzer.git)
cd graphrag-log-analyzer

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate
2. Install Dependencies
Bash
pip install -r requirements.txt
3. Environment Configuration
Copy the template .env.example to create your local .env file:

Bash
cp config/.env.example .env
Open .env and fill in your credentials:

Code snippet
GEMINI_API_KEY=your_google_ai_studio_api_key
PINECONE_API_KEY=your_pinecone_api_key
PINECONE_INDEX_NAME=lograg-incident-index
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password
🔄 Execution Pipeline
Execute the processing and ingestion steps in the following order:

Step 1: Data Preprocessing & Enrichment
Parses raw Loghub CSVs, strips transient runtime noise (Date, Time, Pid), applies regex template masking, and injects SRE runbook metadata.

Bash
python3 pipeline/process_csv.py
Step 2: Seed Graph Topology (Neo4j)
Populates local Neo4j instance with (:Service)-[:EMITTED]->(:Event)-[:ASSOCIATED_WITH]->(:Trace) star topology.

Bash
python3 pipeline/seed_neo4j.py
Step 3: Ingest Vector Embeddings (Pinecone)
Generates 768-dimensional embeddings via gemini-embedding-001 and batch-upserts vectors along with metadata into Pinecone.

Bash
python3 pipeline/upsert_pinecone.py
📄 License
This project is developed for academic evaluation and open-source software experimentation.