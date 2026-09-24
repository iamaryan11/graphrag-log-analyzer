import pandas as pd
import json
import re
import os
from typing import Dict, List, Any

MASK_PATTERNS = {
    "ip_port": (r"/\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+", "<IP_PORT>"),
    "ip": (r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "<IP>"),
    "uuid": (r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", "<UUID>"),
    "block_id": (r"blk_-?\d+", "<BLOCK_ID>"),
    "request_id": (r"req-[a-f0-9-]+", "<REQUEST_ID>"),
    "resource_id": (r"(instance|volume|img|net|tenant|user)-[a-f0-9]+", "<RESOURCE_ID>"),
    "hex": (r"0x[a-fA-F0-9]+", "<HEX>"),
    "digits": (r"\b\d+\b", "<NUM>")
}


RUNBOOK_KNOWLEDGE_BASE = {
    # ==========================================
    # HDFS SUBSYSTEM RUNBOOKS
    # ==========================================
    "got exception while serving": {
        "root_cause": "DataNode network socket read timeout or disk I/O bottleneck during block transfer.",
        "resolution": "Inspect DataNode network socket timeout parameters, verify disk read latency on host, and restart DataXceiver thread if hung.",
        "remediation_type": "CHECK_INFRASTRUCTURE"
    },
    "packetresponder": {
        "root_cause": "DataNode block replication pipeline disruption or downstream socket termination.",
        "resolution": "Check DataNode process health, verify network MTU settings across cluster nodes, and flush stale socket connections.",
        "remediation_type": "RESTART_SERVICE"
    },
    "verification succeeded": {
        "root_cause": "Routine HDFS block checksum audit completed successfully.",
        "resolution": "No action required. Block integrity verified across storage nodes.",
        "remediation_type": "NO_ACTION"
    },
    "receiving block": {
        "root_cause": "Standard HDFS write pipeline initialization for incoming data block.",
        "resolution": "Monitor active write streams and verify target DataNode disk quota.",
        "remediation_type": "MONITOR"
    },
    "received block": {
        "root_cause": "HDFS block replication write completed and acknowledged.",
        "resolution": "No action required. NameSystem block map updated.",
        "remediation_type": "NO_ACTION"
    },
    "addstoredblock": {
        "root_cause": "NameNode received block report update from storage DataNode.",
        "resolution": "Verify NameNode heap memory usage and monitor metadata synchronization rate.",
        "remediation_type": "MONITOR"
    },
    "allocateblock": {
        "root_cause": "NameNode allocating new storage block for client write operation.",
        "resolution": "Monitor NameNode lease manager and verify client write pipeline throughput.",
        "remediation_type": "MONITOR"
    },
    "delete: blk": {
        "root_cause": "HDFS garbage collection or stale block invalidation requested by NameNode.",
        "resolution": "Verify invalidation queue length and confirm underlying disk space release.",
        "remediation_type": "MAINTENANCE"
    },

    # ==========================================
    # OPENSTACK SUBSYSTEM RUNBOOKS
    # ==========================================
    "failed to attach": {
        "root_cause": "Cinder volume lock timeout or iSCSI target attachment failure.",
        "resolution": "Force detach stale volume lease using OpenStack CLI and restart cinder-volume service.",
        "remediation_type": "RESTART_SERVICE"
    },
    "instance failed to spawn": {
        "root_cause": "Nova compute node hypervisor resource exhaustion (RAM/vCPU limits reached).",
        "resolution": "Migrate pending instances to secondary compute host and clear hypervisor cache.",
        "remediation_type": "SCALE_UP"
    },
    "connection pool": {
        "root_cause": "Database connection limit reached under high Nova/Neutron API request volume.",
        "resolution": "Increase max_connections in nova.conf and scale connection pooler daemon.",
        "remediation_type": "CONFIG_CHANGE"
    },
    "amqp": {
        "root_cause": "RabbitMQ message broker disconnection between Nova API and Compute workers.",
        "resolution": "Check RabbitMQ cluster status, verify port 5672 firewall rules, and restart rabbitmq-server.",
        "remediation_type": "RESTART_SERVICE"
    },
    "http exception": {
        "root_cause": "Keystone authentication token expiry or unauthorized API request path.",
        "resolution": "Verify API service endpoints, inspect Keystone token expiration TTL, and check credentials.",
        "remediation_type": "CHECK_CREDENTIALS"
    },
    "nova.compute.manager": {
        "root_cause": "Nova compute driver state synchronization warning during instance lifecycle event.",
        "resolution": "Inspect nova-compute log for hypervisor driver timeouts and verify libvirt daemon status.",
        "remediation_type": "CHECK_LOGS"
    },

    # ==========================================
    # FALLBACK FOR UNCLASSIFIED LOGS
    # ==========================================
    "DEFAULT": {
        "root_cause": "Standard operational log trace or unclassified infrastructure event.",
        "resolution": "Inspect real-time system metrics and verify dependent microservice health.",
        "remediation_type": "MANUAL_INVESTIGATION"
    }
}

def clean_and_mask_template(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        return "<EMPTY_LOG>"
    cleaned = text
    for _, (pattern, replacement) in MASK_PATTERNS.items():
        cleaned = re.sub(pattern, replacement, cleaned)
    return cleaned.strip()

def match_sre_runbook(template_str: str) -> Dict[str, str]:
    template_lower = template_str.lower()
    for keyword, info in RUNBOOK_KNOWLEDGE_BASE.items():
        if keyword in template_lower:
            return info
    return RUNBOOK_KNOWLEDGE_BASE["DEFAULT"]

def process_structured_csv(file_path: str, dataset_type: str, filter_anomalies: bool = True) -> List[Dict[str, Any]]:
    if not os.path.exists(file_path):
        print(f"Warning: File not found at {file_path}. Skipping...")
        return []

    df = pd.read_csv(file_path)
    df.columns = [col.strip().lower() for col in df.columns]
    
    col_map = {
        "lineid": "line_id",
        "logid": "line_id",
        "date": "date",
        "time": "time",
        "level": "level",
        "component": "component",
        "content": "raw_content",
        "eventtemplate": "event_template"
    }
    df.rename(columns=col_map, inplace=True)
    
    # Strip whitespace & uppercase log levels
    if "level" in df.columns:
        df["level"] = df["level"].astype(str).str.strip().str.upper()

    # Anomaly filtering with automatic fallback if sample contains only INFO logs
    if filter_anomalies and "level" in df.columns:
        filtered_df = df[df["level"].isin(["ERROR", "WARN", "WARNING", "FATAL", "CRITICAL"])].copy()
        if len(filtered_df) == 0:
            print(f"Notice: No ERROR/WARN logs in {file_path}. Processing sample lines regardless of level for testing.")
            df = df.head(100).copy() # Takes first 100 sample lines
        else:
            df = filtered_df

    records = []
    for idx, row in df.iterrows():
        raw_content = str(row.get("raw_content", ""))
        event_template = str(row.get("event_template", raw_content))
        
        cleaned_template = clean_and_mask_template(event_template)
        runbook = match_sre_runbook(cleaned_template)
        
        log_level = str(row.get("level", "INFO"))
        component = str(row.get("component", "unknown-service"))
        line_id = str(row.get("line_id", idx))
        
        trace_key = "UNKNOWN_TRACE"
        if dataset_type == "HDFS":
            blk_match = re.search(r"blk_-?\d+", raw_content)
            if blk_match:
                trace_key = blk_match.group(0)
        elif dataset_type == "OpenStack":
            req_match = re.search(r"req-[a-f0-9-]+", raw_content)
            if req_match:
                trace_key = req_match.group(0)

        text_to_embed = (
            f"Domain: {dataset_type} | Component: {component} | Severity: {log_level} | "
            f"Error Pattern: {cleaned_template} | Root Cause: {runbook['root_cause']} | "
            f"Resolution: {runbook['resolution']}"
        )
        
        vector_id = f"{dataset_type.lower()}-{line_id}-{hash(cleaned_template) & 0xffffffff:x}"
        
        records.append({
            "id": vector_id,
            "text_to_embed": text_to_embed,
            "metadata": {
                "dataset": dataset_type,
                "component": component,
                "severity": log_level,
                "trace_key": trace_key,
                "cleaned_template": cleaned_template,
                "raw_message": raw_content,
                "root_cause": runbook["root_cause"],
                "resolution": runbook["resolution"],
                "remediation_type": runbook["remediation_type"]
            }
        })

    return records

if __name__ == "__main__":
    hdfs_file = "../data/raw/HDFS_2k.log_structured.csv"
    openstack_file = "../data/raw/OpenStack_2k.log_structured.csv"
    output_json = "../data/processed/unified_pinecone_vectors.json"

    print("Processing HDFS structured logs...")
    hdfs_docs = process_structured_csv(hdfs_file, dataset_type="HDFS", filter_anomalies=True)
    
    print("Processing OpenStack structured logs...")
    openstack_docs = process_structured_csv(openstack_file, dataset_type="OpenStack", filter_anomalies=True)
    
    unified_dataset = hdfs_docs + openstack_docs
    
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(unified_dataset, f, indent=2)
        
    print(f"\nProcessing Complete!")
    print(f"HDFS Vector Count: {len(hdfs_docs)}")
    print(f"OpenStack Vector Count: {len(openstack_docs)}")
    print(f"Total Combined Output Saved to: {output_json}")