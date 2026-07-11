from __future__ import annotations

import json
import time

from openai import OpenAI

from app.core.config import GITHUB_TOKEN, MODEL_NAME
from app.core.database import DB_SCHEMA
from app.core.models import EquipmentStatusModel

if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN not set in .env")

client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=GITHUB_TOKEN,
)

# gpt-4o-mini: 8k total tokens. At ~4 chars/token:
# Input budget  ≈ 4k tokens ≈ 16,000 chars (leaving 4k for output)
_MAX_PROMPT_CHARS  = 14_000   # conservative input ceiling
_MAX_OUTPUT_TOKENS = 2_000    # sufficient for tool calls + short prose
_DOC_CONTEXT_CHARS = 1_500    # per-turn RAG budget

_NON_INSTRUMENT_ACTIONS = {
    "generate_plot",
    "analyse_data",
    "query_database",
    "list_samples",
    "extract_and_check_feasibility",
}

_BASE_SYSTEM_PROMPT = """\
You are MAESTRO, an agentic orchestrator for a self-driving scientific laboratory.

RULES:
- Instrument actions → call plan_workflow ONCE with ALL steps; await user approval.
- Non-instrument actions (analysis, plots, queries, document questions) → execute immediately.
- Paper reproduction → call extract_and_check_feasibility first.

CAPABILITY CHECK (before any workflow):
  1. Verify registered instruments can control the requested parameters.
  2. Verify registered instruments can measure the requested objective.
  3. Query resources table for consumable stock before experiments.
  4. If lab cannot execute the request, explain what is missing.

DATABASE:
  Resources:  SELECT * FROM resources
  Protocols:  SELECT protocol_id, name, optimiser_used, results_summary FROM protocols ORDER BY created_at DESC
  Results:    SELECT condition_name, condition_value, objective_name, objective_value, parameters FROM evaluations ORDER BY timestamp DESC LIMIT 20

OPTIMISE_CONDITION — required fields:
  label, condition_label, condition_value, condition_unit,
  free_params [{name, min, max, unit}], objective_metric,
  optimiser_name: "gp_bo"|"random"|"optuna"|"honegumi"|"deap",
  n_calls, n_initial_points

  DISTINCTION: condition_label/value = FIXED external variable.
  free_params = variables the optimiser SEARCHES OVER. They are separate.

SYNTHESISE: label, instrument, params {dict}
CHARACTERISE: label, sample_ref, conditions {dict}, measures
SAMPLE IDs: S-001, S-002, ... persisted across session.
STYLE: Precise, concise, honest about uncertainty.
"""


def _total_chars(messages: list) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages)


def trim_messages_to_budget(
    messages:    list,
    max_chars:   int = _MAX_PROMPT_CHARS,
    keep_last_n: int = 8,
) -> list:
    if not messages:
        return messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs  = [m for m in messages if m.get("role") != "system"]
    recent      = other_msgs[-keep_last_n:] if len(other_msgs) > keep_last_n else other_msgs
    older       = other_msgs[:-keep_last_n] if len(other_msgs) > keep_last_n else []
    kept        = system_msgs + recent
    budget      = max_chars - _total_chars(kept)
    for msg in reversed(older):
        cost = len(str(msg.get("content", "")))
        if budget - cost > 0:
            kept.insert(len(system_msgs), msg)
            budget -= cost
    sys_part   = [m for m in kept if m.get("role") == "system"]
    other_part = [m for m in kept if m.get("role") != "system"]
    try:
        other_part.sort(key=lambda m: messages.index(m))
    except ValueError:
        pass
    return sys_part + other_part


def build_dynamic_system_prompt() -> str:
    from app.core.tool_registry import TOOL_REGISTRY
    from app.core.lab_config import get_lab_settings
    from app.core.documents import DOCUMENTS

    settings = get_lab_settings()

    extension = ""
    if settings.system_prompt_extension.strip():
        extension = f"\nLAB CONTEXT:\n{settings.system_prompt_extension.strip()[:600]}"

    opt_context = ""
    enabled_libs = [lib for lib in settings.optimisation_library if lib.enabled]
    if enabled_libs:
        names = ", ".join(lib.name for lib in enabled_libs)
        opt_context = f"\nOPTIMISERS: {names}"

    doc_registry = ""
    if DOCUMENTS:
        lines = ["\nKNOWLEDGE LIBRARY:"]
        for doc in DOCUMENTS.values():
            meta = []
            if doc.year:
                meta.append(str(doc.year))
            if doc.authors:
                meta.append(doc.authors[0] + (" et al." if len(doc.authors) > 1 else ""))
            meta_str = f" ({', '.join(meta)})" if meta else ""
            lines.append(f"  [{doc.document_id[:8]}] {doc.title or doc.filename}{meta_str}")
        doc_registry = "\n".join(lines)

    return (
        _BASE_SYSTEM_PROMPT
        + extension
        + opt_context
        + doc_registry
        + "\nINSTRUMENTS:\n"
        + TOOL_REGISTRY.to_llm_context()
        + "\nDB SCHEMA:\n"
        + DB_SCHEMA
    )


def _should_retrieve_docs(session, query: str) -> bool:
    from app.core.documents import DOCUMENTS
    if not DOCUMENTS:
        return False
    # Skip retrieval for clearly non-document queries
    non_doc_keywords = {
        "list samples", "show samples", "query database", "run the",
        "execute", "start campaign", "generate plot", "analyse",
        "how many", "what is the best", "reset",
    }
    q_lower = query.lower()
    if any(kw in q_lower for kw in non_doc_keywords):
        return False
    return True


def _retrieve_doc_context(session, query: str) -> str:
    from app.core.documents import DOCUMENTS, retrieve_relevant_passages

    if not _should_retrieve_docs(session, query):
        return ""

    chunks = []
    budget = _DOC_CONTEXT_CHARS

    if session.active_document_id and session.active_document_id in DOCUMENTS:
        active_doc = DOCUMENTS[session.active_document_id]
        try:
            passages = retrieve_relevant_passages(
                session.active_document_id,
                query=query,
                top_k=3,
                max_chars=budget,
            )
            if passages:
                chunks.append(
                    f"[{active_doc.title or active_doc.filename}]\n"
                    + "\n".join(passages)
                )
        except Exception:
            pass

    return ("DOCUMENT CONTEXT:\n" + "\n".join(chunks)) if chunks else ""


def _ensure_tool_calls_answered(messages: list) -> list:
    result    = list(messages)
    responded = {
        m["tool_call_id"]
        for m in result
        if m.get("role") == "tool" and m.get("tool_call_id")
    }
    injections = []
    for i, msg in enumerate(result):
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []):
            tc_id   = tc.get("id")
            tc_name = tc.get("function", {}).get("name", "unknown")
            if tc_id and tc_id not in responded:
                injections.append((i + 1, {
                    "role":         "tool",
                    "tool_call_id": tc_id,
                    "name":         tc_name,
                    "content":      json.dumps({
                        "status":  "completed",
                        "message": f"Tool '{tc_name}' executed.",
                    }),
                }))
                responded.add(tc_id)
    for insert_idx, tool_msg in reversed(injections):
        result.insert(insert_idx, tool_msg)
    return result


def call_llm(messages: list, tools=None, tool_choice: str = "auto"):
    safe_messages = trim_messages_to_budget(messages)
    kwargs: dict = {
        "model":       MODEL_NAME,
        "messages":    safe_messages,
        "max_tokens":  _MAX_OUTPUT_TOKENS,
        "temperature": 0.2,
    }
    if tools is not None:
        kwargs["tools"]       = tools
        kwargs["tool_choice"] = tool_choice

    last_exc = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last_exc


def build_tools_schema() -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": "plan_workflow",
                "description": (
                    "Propose a multi-step workflow for lab instrument tasks. "
                    "All steps in one call. Shown to user for approval before execution."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind":             {"type": "string", "enum": ["synthesise","characterise","optimise_condition","list_samples","query_database","generate_plot","analyse_data"]},
                                    "label":            {"type": "string"},
                                    "instrument":       {"type": "string"},
                                    "params":           {"type": "object"},
                                    "produces":         {"type": "string"},
                                    "sample_ref":       {"type": "string"},
                                    "conditions":       {"type": "object"},
                                    "measures":         {"type": "string"},
                                    "condition_label":  {"type": "string"},
                                    "condition_value":  {"type": "number"},
                                    "condition_unit":   {"type": "string"},
                                    "free_params":      {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "min": {"type": "number"}, "max": {"type": "number"}, "unit": {"type": "string"}}}},
                                    "objective_metric": {"type": "string"},
                                    "optimiser_name":   {"type": "string"},
                                    "n_calls":          {"type": "integer"},
                                    "n_initial_points": {"type": "integer"},
                                    "plot_code":        {"type": "string"},
                                    "analysis_code":    {"type": "string"},
                                    "sql":              {"type": "string"},
                                    "description":      {"type": "string"},
                                },
                                "required": ["kind", "label"],
                            },
                        },
                    },
                    "required": ["summary", "steps"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "extract_and_check_feasibility",
                "description": "Extract an experimental campaign from an uploaded paper and check lab feasibility.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "case_name": {"type": "string", "description": "The case study, figure, or experiment to extract"},
                    },
                    "required": ["case_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_samples",
                "description": "List all samples in the lab sample inventory.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_plot",
                "description": (
                    "Generate a matplotlib figure from experimental data.\n"
                    "Write pure matplotlib code — no imports, no plt.savefig().\n"
                    "Available: results_store (list of dicts), sample_registry (list of dicts).\n"
                    "results_store[i] keys: condition_label, condition_value, optimiser_name, param_names, X, y, best_params, best_objective, failed_samples."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "plot_code":   {"type": "string"},
                    },
                    "required": ["description", "plot_code"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyse_data",
                "description": (
                    "Run statistical analysis using numpy/scipy. Every value MUST be printed.\n"
                    "Available: results_store, sample_registry."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description":   {"type": "string"},
                        "analysis_code": {"type": "string"},
                    },
                    "required": ["description", "analysis_code"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_database",
                "description": "Run a read-only SQL SELECT query. Tables: evaluations, resources, protocols.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql":         {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["sql", "description"],
                },
            },
        },
    ]


def build_lab_context_message(session) -> dict:
    from app.core.tool_registry import TOOL_REGISTRY
    from datetime import datetime

    now      = datetime.now()
    n_evals  = sum(len(r.get("X", [])) for r in session.agent_state.results_store)
    n_instrs = len(TOOL_REGISTRY.list_all())

    campaign_text = ""
    if session.extracted_campaign:
        c = session.extracted_campaign
        campaign_text = (
            f" | CAMPAIGN: '{c.title}' "
            f"(obj: {c.objective_metric}, "
            f"params: {[p['name'] for p in c.parameter_space]})"
        )

    doc_text = ""
    if session.active_document_id:
        from app.core.documents import DOCUMENTS
        doc = DOCUMENTS.get(session.active_document_id)
        if doc:
            toc = ""
            if doc.sections:
                toc = " | Sections: " + ", ".join(
                    s.heading for s in doc.sections[:6]
                )
            doc_text = (
                f"\nDOC: {doc.title or doc.filename}"
                f" ({len(doc.sections)} sections, {len(doc.figures)} figs){toc}"
            )

    return {
        "role": "system",
        "content": (
            f"[STATE] {now.strftime('%H:%M')} | "
            f"Evals: {n_evals} | "
            f"Instruments: {n_instrs}"
            f"{campaign_text}{doc_text}"
        ),
    }


def llm_plan(session) -> dict:
    dynamic_system = build_dynamic_system_prompt()

    messages = list(session.agent_state.messages)

    if messages and messages[0].get("role") == "system":
        messages[0] = {"role": "system", "content": dynamic_system}
    else:
        messages.insert(0, {"role": "system", "content": dynamic_system})

    last_user_msg = next(
        (m.get("content", "") for m in reversed(session.agent_state.messages)
         if m.get("role") == "user"),
        "",
    )
    if last_user_msg:
        doc_context = _retrieve_doc_context(session, query=last_user_msg)
        if doc_context:
            messages.append({"role": "system", "content": doc_context})

    messages.append(build_lab_context_message(session))
    messages = _ensure_tool_calls_answered(messages)

    msg = call_llm(messages, tools=build_tools_schema())

    entry: dict = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        entry["tool_calls"] = [
            {
                "id":   tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]

    session.agent_state.messages.append(entry)
    session.agent_state.last_llm_message      = entry
    session.agent_state.last_tools_used       = (
        [tc.function.name for tc in msg.tool_calls] if msg.tool_calls else []
    )
    session.agent_state.awaiting_confirmation = bool(msg.tool_calls)
    session.agent_state.pending_tool_calls    = entry.get("tool_calls", [])
    return entry