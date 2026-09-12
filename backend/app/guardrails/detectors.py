"""Pattern-based detectors for unsafe or manipulative input.

Why patterns rather than a model
--------------------------------
An ML classifier (Presidio, Detoxify, or an LLM judge) would catch more, but
each carries a real cost: Presidio and Detoxify pull spaCy/Torch and roughly
triple the image size, while an LLM judge adds a model call - and its
latency and spend - to every single question. These detectors are cheap,
deterministic, dependency-free and explainable.

They are one layer, not the whole defence. The structural protections in
`prompt_builder` (nonce-delimited untrusted context, neutralised
scaffolding, structured history) are what actually contain a malicious
document; these detectors catch obvious hostile *input* early and cheaply.

Known limits, stated plainly: pattern matching is evadable by paraphrase and
will miss novel phrasings. It is a filter, not a guarantee.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Pattern

# --- Prompt injection / jailbreak ------------------------------------------
# Aimed at instruction-override attempts. Kept reasonably specific: broad
# patterns would reject legitimate questions, and a guardrail that blocks
# real work gets switched off.
_INJECTION_PATTERNS: List[Pattern] = [
    # Bounded gap between the verb and the noun rather than enumerating
    # qualifier combinations: "ignore all previous instructions",
    # "disregard your prior rules" and "forget the above directives" are the
    # same attack with different filler. Capped at three words so it cannot
    # match across unrelated clauses.
    re.compile(
        r"\b(?:ignore|disregard|forget|override)\s+(?:\w+\s+){0,3}?"
        r"(?:instructions?|rules?|prompts?|directives?|guidelines?)\b",
        re.I,
    ),
    re.compile(r"\b(reveal|show|print|repeat)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions?)\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+(a|an|no longer)\b", re.I),
    re.compile(r"\bpretend\s+(you\s+are|to\s+be)\b", re.I),
    re.compile(r"\bact\s+as\s+(if\s+you\s+are\s+)?(a|an)\s+\w+\s+(without|with\s+no)\s+(restrictions?|rules?|filters?)\b", re.I),
    re.compile(r"\b(developer|debug|god|admin)\s+mode\b", re.I),
    re.compile(r"\bDAN\b\s+mode", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"\bsystem\s*:\s*you\s+(are|must)\b", re.I),
    re.compile(r"\boverride\s+(your\s+)?(safety|security|previous)\b", re.I),
]

# --- PII --------------------------------------------------------------------
# Deliberately conservative: false positives here mean redacting something
# harmless, which is far cheaper than transmitting a real identifier.
_PII_PATTERNS = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
    "phone": re.compile(r"\b(?:\+\d{1,3}[\s-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}\b"),
    # US SSN shape; also matches similarly-formatted national ids.
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}

# --- Toxicity / harmful requests -------------------------------------------
# Intentionally narrow: this is a corporate knowledge assistant, not a
# general chatbot, so it targets requests for actively harmful instructions
# rather than attempting broad profanity filtering (which mostly generates
# false positives on legitimate documents).
_HARMFUL_PATTERNS: List[Pattern] = [
    re.compile(r"\bhow\s+to\s+(make|build|synthesi[sz]e)\s+(a\s+)?(bomb|explosive|weapon|poison|nerve\s+agent)\b", re.I),
    re.compile(r"\b(kill|murder|harm)\s+(someone|somebody|a\s+person|people)\b", re.I),
    re.compile(r"\bhow\s+to\s+(hack|breach|exploit)\s+(into\s+)?(a\s+)?(system|network|account|server)\b", re.I),
    re.compile(r"\b(child|minor)\s+(porn|sexual)\b", re.I),
]


@dataclass
class GuardrailFinding:
    """One detection. `detail` never contains the offending text itself, so
    findings are safe to log and trace."""

    category: str
    detail: str


@dataclass
class GuardrailResult:
    allowed: bool = True
    findings: List[GuardrailFinding] = field(default_factory=list)
    # Input with sensitive spans replaced; None when nothing was changed.
    sanitized_text: str | None = None

    @property
    def categories(self) -> List[str]:
        return sorted({finding.category for finding in self.findings})

    def add(self, category: str, detail: str) -> None:
        self.findings.append(GuardrailFinding(category=category, detail=detail))


def detect_prompt_injection(text: str) -> List[GuardrailFinding]:
    return [
        GuardrailFinding("prompt_injection", f"matched pattern #{index}")
        for index, pattern in enumerate(_INJECTION_PATTERNS)
        if pattern.search(text)
    ]


def detect_harmful_content(text: str) -> List[GuardrailFinding]:
    return [
        GuardrailFinding("harmful_content", f"matched pattern #{index}")
        for index, pattern in enumerate(_HARMFUL_PATTERNS)
        if pattern.search(text)
    ]


def detect_pii(text: str) -> List[GuardrailFinding]:
    findings: List[GuardrailFinding] = []
    for label, pattern in _PII_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            # Count only - never the matched value, which is the PII itself.
            findings.append(GuardrailFinding("pii", f"{label} x{len(matches)}"))
    return findings


def redact_pii(text: str) -> str:
    """Replace PII spans with a typed placeholder.

    Used on outbound text so an answer cannot echo an identifier that
    happened to sit in a document.
    """
    redacted = text
    for label, pattern in _PII_PATTERNS.items():
        redacted = pattern.sub(f"[redacted-{label}]", redacted)
    return redacted
