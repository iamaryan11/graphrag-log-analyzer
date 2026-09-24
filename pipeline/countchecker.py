import json

with open("unified_pinecone_vectors.json", "r") as f:
    data = json.load(f)

hdfs_count = sum(1 for item in data if item["metadata"]["dataset"] == "HDFS")
openstack_count = sum(1 for item in data if item["metadata"]["dataset"] == "OpenStack")

print(f"HDFS Vectors: {hdfs_count}")
print(f"OpenStack Vectors: {openstack_count}")
print(f"Total Combined Vectors: {len(data)}")