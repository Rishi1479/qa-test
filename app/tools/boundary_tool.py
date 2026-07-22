"""
Boundary Extraction Tool
--------------------------
Exposed to the Boundary & Negative agent as an LLM tool. Pulls explicit
numeric constraints (min/max length, ranges, comparisons) out of a
requirement's text deterministically via regex, so the LLM doesn't have
to "eyeball" arithmetic (LLMs are unreliable at generating correct n-1
/ n+1 boundary values from prose; a regex + arithmetic tool is not).
The agent calls this first, then reasons over the *returned* boundary
values to write test cases.
"""
from __future__ import annotations
import re
from langchain_core.tools import tool

_RANGE = re.compile(r"(\d+)\s*(?:-|to|–)\s*(\d+)")
_AT_LEAST = re.compile(r"(?:at least|minimum of|>=|≥)\s*(\d+)")
_AT_MOST = re.compile(r"(?:at most|maximum of|<=|≤)\s*(\d+)")
_UNDER = re.compile(r"(?:under|less than|<)\s*(\d+(?:\.\d+)?)")
_OVER = re.compile(r"(?:over|more than|greater than|>)\s*(\d+(?:\.\d+)?)")


@tool
def extract_boundary_values(requirement_text: str) -> str:
    """Extract numeric constraints (ranges, minimums, maximums) from a
    requirement's text and return the boundary test values to use
    (value-1, value, value+1 style) for each constraint found."""
    findings = []

    for lo, hi in _RANGE.findall(requirement_text):
        lo, hi = int(lo), int(hi)
        findings.append(f"range {lo}-{hi}: boundary values -> {lo-1}(invalid), {lo}(valid-min), "
                         f"{lo+1}(valid), {hi-1}(valid), {hi}(valid-max), {hi+1}(invalid)")
    for val in _AT_LEAST.findall(requirement_text):
        v = int(val)
        findings.append(f"minimum {v}: boundary values -> {v-1}(invalid), {v}(valid), {v+1}(valid)")
    for val in _AT_MOST.findall(requirement_text):
        v = int(val)
        findings.append(f"maximum {v}: boundary values -> {v-1}(valid), {v}(valid), {v+1}(invalid)")
    for val in _UNDER.findall(requirement_text):
        v = float(val)
        findings.append(f"upper limit < {v}: boundary values -> just below {v}(valid), "
                         f"{v}(invalid), just above {v}(invalid)")
    for val in _OVER.findall(requirement_text):
        v = float(val)
        findings.append(f"lower limit > {v}: boundary values -> just above {v}(valid), "
                         f"{v}(invalid), just below {v}(invalid)")

    if not findings:
        return "No explicit numeric constraints found in this requirement."
    return "\n".join(findings)
