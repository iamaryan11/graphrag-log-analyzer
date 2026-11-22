from typing import List, Optional
from pydantic import BaseModel, Field

class DiagnoseRequest(BaseModel):
    query: str = Field(..., min_length=5, max_length=1000, description="Incident log or SRE symptom description")
    top_k: int = Field(default=3, ge=1, le=10, description="Number of vector matches to anchor graph traversal")

class CascadingEvent(BaseModel):
    service: str
    event_template: str
    severity: str

class RemediationStep(BaseModel):
    step_number: int
    action: str
    cli_command: Optional[str] = Field(default=None, description="Optional diagnostic or remediation shell command")
    requires_human_approval: bool = False

class RCAReport(BaseModel):
    incident_summary: str
    root_cause: str
    domain: str
    affected_services: List[str]
    blast_radius: int
    remediation_plan: List[RemediationStep]
    confidence_score: float = Field(..., ge=0.0, le=1.0)

class DiagnoseResponse(BaseModel):
    status: str
    latency_ms: float
    guardrail_alerts: List[str]
    retrieved_traces: List[str]
    rca_report: RCAReport