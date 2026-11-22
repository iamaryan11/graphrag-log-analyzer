import re
from typing import List, Tuple
from api.schemas import RCAReport

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+system\s+prompt",
    r"you\s+are\s+now\s+DAN",
    r"print\s+your\s+api\s+key",
]

DESTRUCTIVE_CMD_PATTERNS = [
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f\b",
    r"\bmkfs(\.[a-z0-9]+)?\b",
    r"\bdd\s+if=",
    r"\bchmod\s+(-R\s+)?777\b",
    r"\bDROP\s+(TABLE|DATABASE)\b",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
]

def validate_user_query(query: str) -> Tuple[bool, str]:
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            return False, f"Blocked by Input Guardrail: Potential prompt injection matched '{pattern}'."
    return True, ""

def enforce_remediation_guardrails(report: RCAReport) -> Tuple[RCAReport, List[str]]:
    alerts: List[str] = []
    for step in report.remediation_plan:
        combined_text = f"{step.action} {step.cli_command or ''}"
        for pattern in DESTRUCTIVE_CMD_PATTERNS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                alerts.append(f"Step {step.step_number}: Blocked destructive command matching '{pattern}'.")
                step.cli_command = "[REDACTED_BY_SAFETY_GUARDRAIL]"
                step.action = f"[BLOCKED - MANUAL APPROVAL REQUIRED] {step.action}"
                step.requires_human_approval = True
                break
        # High-impact service restarts also require SRE sign-off
        if re.search(r"\b(restart|reboot|kill\s+-9|shutdown)\b", combined_text, re.IGNORECASE):
            step.requires_human_approval = True
    return report, alerts