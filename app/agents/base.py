"""
Abstract BaseAgent and shared helpers.

Every agent in this package inherits from BaseAgent, which:
  - Enforces a single-method contract (`run`) — Interface Segregation.
  - Provides `__call__` so any instance is directly usable as a LangGraph
    node callable without extra wiring — Liskov Substitution.
  - Centralises shared, stateless utilities (_timed, _parse_json) that were
    previously copy-pasted across nodes — DRY + Single Responsibility.

Adding a new agent = create a new file, subclass BaseAgent, implement run().
Nothing else in the codebase needs to change — Open/Closed Principle.
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager

from app.agents.state import GraphState


class BaseAgent(ABC):
    """
    Contract every agent node must satisfy.

    LangGraph expects a callable ``node(state: dict) -> dict``.
    ``__call__`` delegates to ``run`` so any ``BaseAgent`` subclass
    instance satisfies that contract without extra adapters.
    """

    @abstractmethod
    def run(self, state: GraphState) -> dict:
        """
        Execute the agent's single responsibility.

        Args:
            state: The shared LangGraph GraphState (read-only by convention;
                   return a *partial* dict of keys to update, never mutate state
                   directly).

        Returns:
            A partial dict whose keys will be merged into GraphState by
            LangGraph's reducer.
        """

    def __call__(self, state: GraphState) -> dict:
        """Delegate to ``run`` — makes every agent instance a valid LangGraph node."""
        return self.run(state)


# ---------------------------------------------------------------------------
# Shared stateless helpers — owned here so no agent file needs to re-implement
# ---------------------------------------------------------------------------

@contextmanager
def timed(node_name: str, state_updates: dict):
    """
    Context manager that appends ``{node, duration_seconds}`` to the
    ``node_timings`` list inside *state_updates* after the block exits.

    Usage::

        updates: dict = {}
        with timed("my_node", updates):
            ...  # do work
        # updates["node_timings"] now has one entry
    """
    start = time.time()
    yield
    state_updates.setdefault("node_timings", []).append(
        {"node": node_name, "duration_seconds": round(time.time() - start, 3)}
    )


def parse_json(text: str, default):
    """
    Defensively parse an LLM response that *may* contain a JSON payload
    wrapped in markdown fences (```json … ```) or returned as raw JSON.

    Falls back to ``default`` on any parse failure so a single agent's
    formatting slip never crashes the whole graph.

    Args:
        text:    Raw string returned by the LLM.
        default: Value to return if parsing fails (typically ``{}`` or ``[]``).

    Returns:
        Parsed Python object, or ``default``.
    """
    if not isinstance(text, str):
        return default
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return default
