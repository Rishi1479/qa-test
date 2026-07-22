"""
LLM client factory.

LLM_PROVIDER=groq   -> ChatGroq (needs GROQ_API_KEY)
LLM_PROVIDER=gemini -> ChatGoogleGenerativeAI (needs GEMINI_API_KEY)
LLM_PROVIDER=mock   -> None (agents fall back to deterministic generation,
                        see agents/nodes.py). This is the default so the
                        whole pipeline -- upload, parse, 9 agents,
                        validation, export, Mongo/Supabase persistence --
                        is runnable and demoable with zero API keys. Real
                        model reasoning is a `.env` edit away.
"""
from __future__ import annotations
from functools import lru_cache
from app.config import settings


@lru_cache(maxsize=1)
def get_llm():
    if settings.LLM_PROVIDER == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=settings.GROQ_MODEL, api_key=settings.GROQ_API_KEY, temperature=0.2)

    if settings.LLM_PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=settings.GEMINI_MODEL,
                                       google_api_key=settings.GEMINI_API_KEY, temperature=0.2)

    return None  # mock mode


def run_tool_calling_agent(system_prompt: str, user_prompt: str, tools: list, max_tool_hops: int = 3) -> str:
    """
    Shared helper for the agents that reason WITH tools (Requirement
    Analyzer, Boundary & Negative, Coverage & Priority). Binds `tools`
    to the LLM, executes any tool calls it makes, feeds results back,
    and returns the final text content. Kept generic/reusable rather
    than duplicated per agent.
    """
    from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

    llm = get_llm()
    if llm is None:
        raise RuntimeError("run_tool_calling_agent called in mock mode; caller should branch earlier")

    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

    for _ in range(max_tool_hops):
        ai_msg = llm_with_tools.invoke(messages)
        messages.append(ai_msg)
        if not getattr(ai_msg, "tool_calls", None):
            return ai_msg.content
        for call in ai_msg.tool_calls:
            tool_fn = tool_map.get(call["name"])
            result = tool_fn.invoke(call["args"]) if tool_fn else f"Unknown tool {call['name']}"
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    final = llm_with_tools.invoke(messages)
    return final.content
