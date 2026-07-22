"""
Requirement Search Tool
-------------------------
A reusable lookup tool over the current job's extracted requirements.
This is the one exposed to LLM agents as an actual callable "tool" (via
LangChain's @tool + bind_tools), so an agent can, mid-reasoning, ask
"has anything already covered password rules?" instead of the pipeline
just dumping the entire requirement list into every prompt.

Implementation is deliberately simple (rapidfuzz keyword scoring) rather
than a vector store: the corpus is a handful to a few dozen requirements
per document, so a fuzzy keyword match is more transparent, cheaper, and
just as effective as embeddings at this scale. Swapping in a vector
search tool (e.g. Chroma/FAISS) would be a drop-in replacement if
documents grew to hundreds of requirements -- see docs/approach.md.
"""
from __future__ import annotations
from langchain_core.tools import tool
from rapidfuzz import fuzz
from app.schemas.schemas import Requirement

_CURRENT_REQUIREMENTS: list[Requirement] = []


def set_search_context(requirements: list[Requirement]) -> None:
    """Called once per job before the graph runs, so the tool below has
    something to search without threading state through every LLM call."""
    global _CURRENT_REQUIREMENTS
    _CURRENT_REQUIREMENTS = requirements


@tool
def search_requirements(query: str, top_k: int = 3) -> str:
    """Search the current document's requirements for the ones most
    related to `query`. Use this to check for overlap, duplicates, or
    related business rules before generating new scenarios/test cases."""
    scored = [
        (fuzz.token_set_ratio(query, f"{r.title} {r.description}"), r)
        for r in _CURRENT_REQUIREMENTS
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    if not top:
        return "No requirements indexed yet."
    return "\n".join(f"[{r.req_id}] {r.title} (match {score}%): {r.description}" for score, r in top)
