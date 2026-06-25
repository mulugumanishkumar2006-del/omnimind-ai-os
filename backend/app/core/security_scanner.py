import re
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from backend.app.models.database_models import SecurityThreatLogDB

# Regex rules for scanning sensitive patterns
PII_PATTERNS = {
    "Email Address": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "Credit Card": r"\b(?:\d[ -]*?){13,16}\b",
    "Social Security Number": r"\b\d{3}-\d{2}-\d{4}\b",
    "API Key / Secret": r"(?:key|secret|password|token)\s*[:=]\s*['\"][a-zA-Z0-9_\-\.]{16,}['\"]"
}

# Regex rules for scanning jailbreaks or injection patterns
JAILBREAK_KEYWORDS = [
    r"ignore previous instructions",
    r"system prompt",
    r"bypass safety",
    r"dan mode",
    r"do anything now",
    r"you are now unfiltered",
    r"operating system developer override",
    r"give me the root password",
    r"sudo rm -rf"
]

def scan_text(input_text: str, db: Session) -> Dict[str, Any]:
    """Scan the text input for security threats and log results."""
    threats_detected: List[str] = []
    
    # 1. PII Scan
    for name, pattern in PII_PATTERNS.items():
        if re.search(pattern, input_text):
            threats_detected.append(f"PII Leak Risk: Detected potential {name}")
            
    # 2. Jailbreak / Injection Scan
    for keyword in JAILBREAK_KEYWORDS:
        if re.search(keyword, input_text, re.IGNORECASE):
            threats_detected.append(f"Injection/Jailbreak Attempt: Match on keyword pattern '{keyword}'")
            
    # Calculate safety metrics
    total_threats = len(threats_detected)
    safety_score = max(0.0, 100.0 - (total_threats * 30.0))
    
    if safety_score >= 90:
        risk_level = "none"
    elif safety_score >= 60:
        risk_level = "low"
    elif safety_score >= 40:
        risk_level = "medium"
    else:
        risk_level = "high"
        
    # Log threat to DB if anything detected
    if total_threats > 0:
        log_entry = SecurityThreatLogDB(
            scan_type="input_validation",
            input_text=input_text,
            threats_detected=threats_detected,
            safety_score=safety_score,
            risk_level=risk_level
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        
    return {
        "is_safe": total_threats == 0,
        "threats": threats_detected,
        "safety_score": safety_score,
        "risk_level": risk_level
    }

def scrub_sensitive_data(text: str) -> str:
    """Scrub PII from text, replacing it with placeholders."""
    scrubbed = text
    for name, pattern in PII_PATTERNS.items():
        scrubbed = re.sub(pattern, f"[{name.upper()}_REDACTED]", scrubbed)
    return scrubbed
