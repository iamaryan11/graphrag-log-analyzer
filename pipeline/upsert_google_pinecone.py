import json
import os
from google import genai
from google.genai import types
from pinecone import Pinecone, ServerlessSpec
from dotenv import load_dotenv


load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)

INDEX_NAME = "lograg-incident-index"


existing_indexes = [idx.name for idx in pc.list_indexes()]
if INDEX_NAME not in existing_indexes:
    print(f"Creating Pinecone index: '{INDEX_NAME}'...")
    pc.create_index(
        name=INDEX_NAME,
        dimension=768,  
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1")
    )

index = pc.Index(INDEX_NAME)


with open("../data/processed/unified_pinecone_vectors.json", "r") as f:
    records = json.load(f)

print(f"Loaded {len(records)} preprocessed records.")


BATCH_SIZE = 50
vectors_to_upsert = []

for i, record in enumerate(records):
    text_content = record["text_to_embed"]


    response = gemini_client.models.embed_content(
        model="gemini-embedding-001",
        contents=text_content,
        config=types.EmbedContentConfig(output_dimensionality=768)
    )
    embedding_vector = response.embeddings[0].values


    metadata_payload = record.get("metadata", {})
    metadata_payload["text_to_embed"] = text_content

    payload = {
        "id": record["id"],
        "values": embedding_vector,
        "metadata": metadata_payload
    }
    vectors_to_upsert.append(payload)


    if len(vectors_to_upsert) >= BATCH_SIZE or i == len(records) - 1:
        index.upsert(vectors=vectors_to_upsert)
        print(f"Successfully upserted batch up to record {i + 1}/{len(records)}.")
        vectors_to_upsert = []

print("Vector ingestion completed successfully!")