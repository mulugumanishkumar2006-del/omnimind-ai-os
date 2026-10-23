import re
import html
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from backend.app.models.database_models import SecurityThreatLogDB
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# =====================================================================
# Configurable Rule Definitions: PII & Credential Patterns
# =====================================================================
PII_RULES = [
    {
        "name": "Email Address",
        "pattern": r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
        "category": "pii_personal",
        "severity": "medium",
        "explanation": "Detected an email address which may leak user personally identifiable information.",
        "action": "Mask or redact email addresses prior to external LLM routing or public display.",
        "placeholder": "[EMAIL_REDACTED]"
    },
    {
        "name": "Phone Number",
        "pattern": r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "category": "pii_personal",
        "severity": "medium",
        "explanation": "Detected a standard phone number which constitutes personal identifiable data.",
        "action": "Redact contact phone numbers before persistence or downstream sharing.",
        "placeholder": "[PHONE_REDACTED]"
    },
    {
        "name": "Social Security Number",
        "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
        "category": "pii_sensitive",
        "severity": "critical",
        "explanation": "Detected a US Social Security Number format (SSN), representing high-risk sensitive data.",
        "action": "Immediately block exposure and redact completely.",
        "placeholder": "[SSN_REDACTED]"
    },
    {
        "name": "Credit Card",
        "pattern": r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12}|(?:2131|1800|35\d{3})\d{11}|(?:\d[ -]*?){13,16})\b",
        "category": "pii_financial",
        "severity": "critical",
        "explanation": "Detected possible payment card numbers (PCI-DSS compliance violation risk).",
        "action": "Block transmission and replace with masked card placeholder.",
        "placeholder": "[CREDIT_CARD_REDACTED]"
    },
    {
        "name": "OpenAI API Key",
        "pattern": r"\bsk-(?:proj-|ant-)?[a-zA-Z0-9_-]{20,}\b",
        "category": "credential_leak",
        "severity": "critical",
        "explanation": "Detected an OpenAI/Anthropic secret API key.",
        "action": "Revoke exposed key immediately and redact from logs and prompts.",
        "placeholder": "[API_KEY_REDACTED]"
    },
    {
        "name": "GitHub Access Token",
        "pattern": r"\b(?:ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{40,})\b",
        "category": "credential_leak",
        "severity": "critical",
        "explanation": "Detected a GitHub Personal Access Token (PAT).",
        "action": "Rotate the GitHub token and purge from revision logs.",
        "placeholder": "[GITHUB_TOKEN_REDACTED]"
    },
    {
        "name": "AWS Access Key",
        "pattern": r"\bAKIA[0-9A-Z]{16}\b",
        "category": "credential_leak",
        "severity": "critical",
        "explanation": "Detected an AWS Access Key ID.",
        "action": "Disable key in AWS IAM and verify CloudTrail audit logs.",
        "placeholder": "[AWS_KEY_REDACTED]"
    },
    {
        "name": "Private Key",
        "pattern": r"-----BEGIN (?:[A-Z0-9_-]+\s+)?PRIVATE KEY-----",
        "category": "credential_leak",
        "severity": "critical",
        "explanation": "Detected an unencrypted cryptographic private key block.",
        "action": "Revoke certificate/keypair immediately.",
        "placeholder": "[PRIVATE_KEY_REDACTED]"
    },
    {
        "name": "Slack Token",
        "pattern": r"\bxox[baprs]-[0-9a-zA-Z-]{10,}\b",
        "category": "credential_leak",
        "severity": "high",
        "explanation": "Detected a Slack bot/user API token.",
        "action": "Rotate Slack OAuth token in Slack App configuration.",
        "placeholder": "[SLACK_TOKEN_REDACTED]"
    },
    {
        "name": "API Key / Secret",
        "pattern": r"(?:key|secret|password|token)\s*[:=]\s*['\"][a-zA-Z0-9_\-\.]{16,}['\"]",
        "category": "credential_leak",
        "severity": "high",
        "explanation": "Detected a hardcoded assignment of a secret, password, or authentication token.",
        "action": "Use environment variables or a secrets manager instead of hardcoding.",
        "placeholder": "[SECRET_REDACTED]"
    }
]

# Legacy dictionary mapping for backwards compatibility with existing callers
PII_PATTERNS = {rule["name"]: rule["pattern"] for rule in PII_RULES}

# =====================================================================
# Configurable Rule Definitions: Jailbreak, Prompt Injection & Command Abuse
# =====================================================================
JAILBREAK_RULES = [
    {
        "name": "ignore previous instructions",
        "pattern": r"ignore\s+(?:all\s+)?previous\s+instructions",
        "category": "prompt_injection",
        "severity": "high",
        "explanation": "Direct attempt to override or discard system instructions."
    },
    {
        "name": "system prompt",
        "pattern": r"(?:system\s+prompt|print\s+(?:your\s+)?system\s+prompt|reveal\s+(?:the\s+)?system\s+prompt)",
        "category": "prompt_injection",
        "severity": "medium",
        "explanation": "Attempt to extract or tamper with hidden system prompts."
    },
    {
        "name": "bypass safety",
        "pattern": r"(?:bypass|disable|turn\s+off)\s+(?:safety|content\s+filters?|guardrails?)",
        "category": "prompt_injection",
        "severity": "high",
        "explanation": "Explicit request to disable model safety guardrails."
    },
    {
        "name": "dan mode",
        "pattern": r"\b(?:dan\s+mode|do\s+anything\s+now)\b",
        "category": "jailbreak_persona",
        "severity": "high",
        "explanation": "Known 'Do Anything Now' jailbreak framing attempting unrestricted mode."
    },
    {
        "name": "do anything now",
        "pattern": r"\bdo\s+anything\s+now\b",
        "category": "jailbreak_persona",
        "severity": "high",
        "explanation": "Jailbreak persona prompting to ignore boundaries."
    },
    {
        "name": "you are now unfiltered",
        "pattern": r"you\s+are\s+now\s+(?:unfiltered|unrestricted|free\s+from\s+rules)",
        "category": "jailbreak_persona",
        "severity": "high",
        "explanation": "Roleplay instruction to assume an unfiltered persona."
    },
    {
        "name": "operating system developer override",
        "pattern": r"operating\s+system\s+developer\s+override",
        "category": "prompt_injection",
        "severity": "high",
        "explanation": "Social engineering attempt claiming simulated administrative override."
    },
    {
        "name": "give me the root password",
        "pattern": r"give\s+me\s+(?:the\s+)?root\s+password",
        "category": "credential_access",
        "severity": "high",
        "explanation": "Prohibited attempt to harvest system administrator passwords."
    },
    {
        "name": "sudo rm -rf",
        "pattern": r"(?:sudo\s+)?rm\s+-rf\s+(?:/|\*|~|/\w+)",
        "category": "command_injection",
        "severity": "critical",
        "explanation": "Dangerous filesystem destruction command detected."
    },
    {
        "name": "delimiter injection",
        "pattern": r"(?:<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|\[INST\]|<<SYS>>)",
        "category": "delimiter_injection",
        "severity": "high",
        "explanation": "Attempt to inject chat template special tokens to forge turn boundaries."
    },
    {
        "name": "reverse shell command",
        "pattern": r"(?:(?:bash|sh)\s+-i\s+>&|/bin/(?:bash|sh)\s+-i|nc\s+(?:-[a-zA-Z]+\s+)*-e\s+/bin/)",
        "category": "command_injection",
        "severity": "critical",
        "explanation": "Interactive reverse shell command payload detected."
    },
    {
        "name": "encoded powershell execution",
        "pattern": r"powershell(?:\.exe)?\s+(?:-[a-zA-Z]+\s+)*(?:-enc|-encodedcommand)\s+[a-zA-Z0-9+/=]{10,}",
        "category": "command_injection",
        "severity": "critical",
        "explanation": "Obfuscated PowerShell base64 execution payload detected."
    },
    {
        "name": "sql injection signature",
        "pattern": r"(?:\bunion\s+(?:all\s+)?select\b|'\s*or\s*'1'\s*=\s*'1|'\s*;\s*drop\s+table\b)",
        "category": "sql_injection",
        "severity": "high",
        "explanation": "Structured SQL injection pattern detected."
    }
]

# Legacy keywords list for backwards compatibility
JAILBREAK_KEYWORDS = [rule["name"] for rule in JAILBREAK_RULES]


def scrub_sensitive_data(text: str) -> str:
    """Scrub PII and API keys from text, replacing sensitive sequences with redaction tags."""
    if not text:
        return ""
    scrubbed = text
    for rule in PII_RULES:
        placeholder = rule.get("placeholder", f"[{rule['name'].upper()}_REDACTED]")
        scrubbed = re.sub(rule["pattern"], placeholder, scrubbed, flags=re.IGNORECASE)
    return scrubbed


def sanitize_output(text: str) -> Dict[str, Any]:
    """Sanitize model or user output to protect against downstream XSS and unsafe script rendering."""
    if not text:
        return {"original_text": "", "sanitized_text": "", "contains_xss_or_unsafe": False}

    # Detect presence of HTML script tags, onerror/onload attributes, or iframe injections
    xss_patterns = [
        r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>",
        r"javascript\s*:",
        r"\bon\w+\s*=",
        r"<\s*iframe",
        r"<\s*embed",
        r"<\s*object"
    ]
    
    is_unsafe = any(bool(re.search(pat, text, re.IGNORECASE)) for pat in xss_patterns)
    
    # Strip dangerous tags or escape HTML
    cleaned = text
    if is_unsafe:
        cleaned = html.escape(text)

    return {
        "original_text": text,
        "sanitized_text": cleaned,
        "contains_xss_or_unsafe": is_unsafe
    }


def scan_text(input_text: str, db: Optional[Session] = None) -> Dict[str, Any]:
    """Scan the text input for security threats, jailbreaks, PII leaks, and return structured findings."""
    threats_detected: List[str] = []
    findings: List[Dict[str, Any]] = []

    if not input_text or not input_text.strip():
        return {
            "is_safe": True,
            "threats": [],
            "findings": [],
            "safety_score": 100.0,
            "risk_level": "none",
            "scrubbed_preview": ""
        }

    # Size validation
    max_chars = getattr(settings, "MAX_INPUT_CHAR_LENGTH", 50000)
    if len(input_text) > max_chars:
        err_msg = f"Oversized input: {len(input_text)} characters exceeds maximum limit of {max_chars}"
        threats_detected.append(err_msg)
        findings.append({
            "category": "payload_size",
            "severity": "high",
            "matched_pattern": "max_input_length_exceeded",
            "explanation": err_msg,
            "recommended_action": "Reject oversized input to prevent resource exhaustion or buffer abuse.",
            "snippet": input_text[:100] + "..."
        })

    # 1. PII and Credential Scan
    for rule in PII_RULES:
        matches = list(re.finditer(rule["pattern"], input_text, re.IGNORECASE))
        if matches:
            threat_name = f"PII Leak Risk: Detected potential {rule['name']}"
            threats_detected.append(threat_name)
            
            # Mask snippet for safety
            first_match = matches[0].group(0)
            masked_snippet = first_match[:3] + "..." + first_match[-2:] if len(first_match) > 6 else "***"
            
            findings.append({
                "category": rule["category"],
                "severity": rule["severity"],
                "matched_pattern": rule["name"],
                "explanation": rule["explanation"],
                "recommended_action": rule["action"],
                "snippet": masked_snippet
            })

    # 2. Jailbreak, Injection & Command Abuse Scan
    for rule in JAILBREAK_RULES:
        matches = list(re.finditer(rule["pattern"], input_text, re.IGNORECASE))
        if matches:
            threat_name = f"Injection/Jailbreak Attempt: Match on keyword pattern '{rule['name']}'"
            threats_detected.append(threat_name)
            
            first_match = matches[0].group(0)
            findings.append({
                "category": rule["category"],
                "severity": rule["severity"],
                "matched_pattern": rule["name"],
                "explanation": rule["explanation"],
                "recommended_action": "Block prompt execution, sanitize template delimiters, and log security alert.",
                "snippet": first_match[:80]
            })

    # Calculate overall risk metrics
    severity_weights = {
        "critical": 40.0,
        "high": 30.0,
        "medium": 15.0,
        "low": 5.0
    }
    
    total_penalty = sum(severity_weights.get(f["severity"], 20.0) for f in findings)
    safety_score = max(0.0, 100.0 - total_penalty)

    if any(f["severity"] == "critical" for f in findings):
        risk_level = "critical"
    elif any(f["severity"] == "high" for f in findings):
        risk_level = "high"
    elif any(f["severity"] == "medium" for f in findings):
        risk_level = "medium"
    elif any(f["severity"] == "low" for f in findings):
        risk_level = "low"
    else:
        risk_level = "none"

    is_safe = len(threats_detected) == 0
    scrubbed_preview = scrub_sensitive_data(input_text[:1000])

    # Log threat to DB if anything detected and DB session provided
    # PRIVACY SAFEGUARD: Store scrubbed input in DB so raw credentials are never leaked to logs
    if len(threats_detected) > 0 and db is not None:
        try:
            safe_logged_text = scrubbed_preview[:500]
            log_entry = SecurityThreatLogDB(
                scan_type="input_validation",
                input_text=safe_logged_text,
                threats_detected=threats_detected,
                safety_score=safety_score,
                risk_level=risk_level
            )
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
        except Exception as db_err:
            logger.error("Failed to persist security threat log: %s", str(db_err))
            db.rollback()

    return {
        "is_safe": is_safe,
        "threats": threats_detected,
        "findings": findings,
        "safety_score": safety_score,
        "risk_level": risk_level,
        "scrubbed_preview": scrubbed_preview
    }
