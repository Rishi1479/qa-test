"""
Requirement Extraction Tool
----------------------------
Deliberately NOT an LLM call. Turns parsed document text into a list of
structured Requirement objects using pattern matching. Keeping this
deterministic means: (a) it's free and instant, (b) it's testable with
plain unit tests, (c) the LLM agents downstream get a clean, consistent
input shape regardless of how a given document happens to be worded.

Two extraction strategies, tried in order:
1. "FR-N / NFR-N / CR-N: Title" style -- captures Description /
   Validation Conditions / Role-Based Conditions / Example Input /
   Example Output / Edge Case as sub-fields when present, and folds
   them into ``description`` so later agents see the full context.
2. Generic fallback: numbered/bulleted top-level sentences become
   REQ-001, REQ-002, ... when no requirement-ID pattern is found.
"""
from __future__ import annotations
import re
from app.schemas.schemas import Requirement

# ---- Section-boundary detector (e.g. "## 4. Non-Functional Requirements")
# Matches markdown-style headings or plain numbered section titles that signal
# a new document section. Hitting one of these flushes the current requirement
# so trailing text never bleeds from one section into the last requirement's
# sub-field.
_SECTION_HEADING = re.compile(
    r"^\s*(?:#{1,4}\s+)?\d+\.\s+\S",
)

# ---- Requirement-header detector -----------------------------------------
# Broadened from the original FR-only regex to also match NFR-N and CR-N
# prefixes.  Separator relaxed to accept ":", " -", " –", or " —".
_REQ_HEADER = re.compile(
    r"^\s*(?:#{1,6}\s+)?(?:[*\-•●]\s*)?(?:\*\*)?((FR|NFR|CR)-\d+)(?:\*\*)?"
    r"\s*[:–—]\s*(.+)$"
)
# Also accept "FR-N - Title" (space-dash-space) which the strict regex above
# won't match because the dash is in the bullet-strip prefix group.
_REQ_HEADER_ALT = re.compile(
    r"^\s*(?:#{1,6}\s+)?(?:[*\-•●]\s*)?(?:\*\*)?((FR|NFR|CR)-\d+)(?:\*\*)?"
    r"\s+-\s+(.+)$"
)

_SUBFIELD = re.compile(
    r"^\s*(?:[○\-*•●]\s*)?(?:\*\*)?"
    r"(Description|Validation Conditions|Role-Based Conditions|"
    r"Example Input|Example Output|Edge Case)"
    r"(?:\*\*)?\s*:?\s*(.*)$",
    re.IGNORECASE,
)

# Map requirement-ID prefix to Requirement.type
_PREFIX_TYPE = {
    "FR": "Functional",
    "NFR": "Non-Functional",
    "CR": "Constraint",
}


def _extract_fr_style(text: str) -> list[Requirement]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    reqs: list[Requirement] = []
    current: dict | None = None
    current_field = None

    def flush():
        if current is None:
            return
        desc_bits = []
        for field in ("Description", "Validation Conditions", "Role-Based Conditions",
                      "Example Input", "Example Output", "Edge Case"):
            if current.get(field):
                desc_bits.append(f"{field}: {current[field].strip()}")
        raw = "\n".join(desc_bits)
        reqs.append(Requirement(
            req_id=current["id"],
            title=current["title"].strip(" *"),
            description=current.get("Description", "").strip() or current["title"].strip(),
            raw_text=raw or current["title"],
            type=current.get("type", "Functional"),
        ))

    for line in lines:
        # --- Section heading ends the current requirement cleanly ---
        if _SECTION_HEADING.match(line):
            flush()
            current = None
            current_field = None
            continue

        # --- New requirement header ---
        m = _REQ_HEADER.match(line) or _REQ_HEADER_ALT.match(line)
        if m:
            flush()
            req_id = m.group(1)
            prefix = m.group(2)
            title = m.group(3)
            current = {
                "id": req_id,
                "title": title,
                "type": _PREFIX_TYPE.get(prefix, "Functional"),
            }
            current_field = None
            continue

        if current is None:
            continue

        sm = _SUBFIELD.match(line)
        if sm:
            current_field = sm.group(1)
            # normalize key casing e.g. "Role-Based Conditions"
            key = {
                "description": "Description",
                "validation conditions": "Validation Conditions",
                "role-based conditions": "Role-Based Conditions",
                "example input": "Example Input",
                "example output": "Example Output",
                "edge case": "Edge Case",
            }[current_field.lower()]
            current_field = key
            current[current_field] = sm.group(2)
            continue
            
        if line.strip():
            if current_field is None:
                current_field = "Description"
            current[current_field] = current.get(current_field, "") + " " + line.strip()

    flush()
    return reqs


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _extract_generic(text: str) -> list[Requirement]:
    """Fallback for documents with no FR-N headers: one requirement per
    "shall/must/should" sentence, per the assignment's own worked example."""
    reqs: list[Requirement] = []
    candidates = [
        ln.strip("-*• \t")
        for ln in text.splitlines()
        if re.search(r"\b(shall|must|should)\b", ln, re.IGNORECASE) and len(ln.strip()) > 15
    ]
    for i, sentence in enumerate(candidates, start=1):
        reqs.append(Requirement(
            req_id=f"REQ-{i:03d}",
            title=sentence[:60].strip(),
            description=sentence,
            raw_text=sentence,
        ))
    return reqs


def extract_requirements(text: str) -> list[Requirement]:
    reqs = _extract_fr_style(text)
    if reqs:
        return reqs
    return _extract_generic(text)
