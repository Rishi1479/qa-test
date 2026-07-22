"""
Export Tool
--------------
Converts the already-final JSON into Markdown / CSV. No AI calls here --
by the time we're exporting, all content has been generated and
validated; this is pure formatting, so it's fast, deterministic, and
free to re-run for any export format on demand.
"""
from __future__ import annotations
import csv
import io


def to_markdown(payload: dict) -> str:
    lines = [f"# Test Engineering Report - Job {payload['job_id']}", ""]
    cov = payload.get("coverage", {})
    lines.append(f"**Coverage:** {cov.get('covered_requirements', 0)}/"
                 f"{cov.get('total_requirements', 0)} requirements "
                 f"({cov.get('coverage_percent', 0)}%)")
    lines.append("")

    lines.append("## Requirements")
    for r in payload.get("requirements", []):
        flag = " ⚠️ needs clarification" if r.get("is_ambiguous") else ""
        lines.append(f"- **{r['req_id']}**: {r['title']}{flag}")
    lines.append("")

    lines.append("## Test Cases")
    for t in payload.get("test_cases", []):
        lines.append(f"### {t['test_id']} — {t['title']} ({t['type']}, {t['priority']} priority)")
        lines.append(f"- Requirement: {t['req_id']}")
        if t.get("preconditions"):
            lines.append(f"- Preconditions: {'; '.join(t['preconditions'])}")
        if t.get("steps"):
            lines.append("- Steps:")
            for i, s in enumerate(t["steps"], 1):
                lines.append(f"  {i}. {s}")
        if t.get("test_data"):
            lines.append(f"- Test data: {'; '.join(t['test_data'])}")
        lines.append(f"- Expected result: {t.get('expected_result', '')}")
        if t.get("postconditions"):
            lines.append(f"- Postconditions: {'; '.join(t['postconditions'])}")
        lines.append("")

    lines.append("## Acceptance Criteria")
    for ac in payload.get("acceptance_criteria", []):
        lines.append(f"- **{ac['req_id']}** — Given {ac['given']}, When {ac['when']}, "
                     f"Then {ac['then']}")
    lines.append("")

    lines.append("## Traceability")
    lines.append("| Requirement | Scenarios | Test Cases | Covered |")
    lines.append("|---|---|---|---|")
    for tr in payload.get("traceability", []):
        lines.append(f"| {tr['req_id']} | {len(tr['scenario_ids'])} | "
                     f"{len(tr['test_ids'])} | {'✅' if tr['covered'] else '❌'} |")

    return "\n".join(lines)


def to_csv(payload: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["test_id", "req_id", "title", "type", "priority",
                      "preconditions", "steps", "test_data", "expected_result", "postconditions"])
    for t in payload.get("test_cases", []):
        writer.writerow([
            t["test_id"], t["req_id"], t["title"], t["type"], t["priority"],
            "; ".join(t.get("preconditions", [])),
            " | ".join(t.get("steps", [])),
            "; ".join(t.get("test_data", [])),
            t.get("expected_result", ""),
            "; ".join(t.get("postconditions", [])),
        ])
    return buf.getvalue()
