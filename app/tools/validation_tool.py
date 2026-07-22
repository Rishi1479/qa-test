"""
Requirement Validation Tool
-----------------------------
Deterministic pre-flight checks that run BEFORE any LLM agent sees the
requirements, and an output-side validator that runs AFTER the JSON
Formatter agent. Two separate functions, one file, one responsibility
("is this data well-formed / complete"), reused at both ends of the
pipeline.
"""
from __future__ import annotations
from app.schemas.schemas import Requirement

_VAGUE_WORDS = {"secure", "fast", "user-friendly", "appropriate", "reasonable", "good", "easy"}


def validate_requirements(requirements: list[Requirement]) -> list[Requirement]:
    """Flags vague and duplicate requirements in place; returns the same list."""
    seen_titles: dict[str, str] = {}
    for req in requirements:
        desc_lower = req.description.lower()
        words = set(w.strip(".,") for w in desc_lower.split())
        vague_hit = words & _VAGUE_WORDS
        has_number_or_condition = any(ch.isdigit() for ch in req.description) or " if " in desc_lower
        if vague_hit and not has_number_or_condition:
            req.is_ambiguous = True
            req.ambiguity_reason = f"Vague, unquantified term(s): {', '.join(sorted(vague_hit))}"

        norm_title = req.title.strip().lower()
        if norm_title in seen_titles:
            req.is_duplicate_of = seen_titles[norm_title]
        else:
            seen_titles[norm_title] = req.req_id
    return requirements


def validate_output(payload: dict) -> tuple[dict, list[str]]:
    """
    Checks the final formatted JSON for structural problems and
    auto-fixes what it safely can (missing ids get generated,
    duplicate ids get suffixed). Returns (possibly-fixed payload, notes).
    """
    notes: list[str] = []
    seen_ids: set[str] = set()

    for section in ("test_cases",):
        items = payload.get(section, [])
        for i, item in enumerate(items):
            tid = item.get("test_id") or ""
            if not tid:
                tid = f"AUTO-TC-{i:04d}"
                item["test_id"] = tid
                notes.append(f"Generated missing test_id for item {i} in {section}")
            if tid in seen_ids:
                new_id = f"{tid}-DUP{i}"
                item["test_id"] = new_id
                notes.append(f"Duplicate test_id '{tid}' renamed to '{new_id}'")
                tid = new_id
            seen_ids.add(tid)
            for field in ("expected_result",):
                if not item.get(field):
                    item[field] = "NOT SPECIFIED - needs manual review"
                    notes.append(f"Empty '{field}' on {tid}, flagged for manual review")

    if "coverage" in payload:
        cov = payload["coverage"]
        total = cov.get("total_requirements", 0)
        covered = cov.get("covered_requirements", 0)
        if total and covered > total:
            notes.append("Coverage mismatch: covered > total, clamped")
            cov["covered_requirements"] = total

    return payload, notes
