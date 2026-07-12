# backend/app/core/llm.py
# ── FULL FILE ─────────────────────────────────────────────────────────────────

from __future__ import annotations

import hashlib
import json
import re
import threading
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

_MAX_PROMPT_CHARS  = 14_000
_MAX_OUTPUT_TOKENS = 2_000
_DOC_CONTEXT_CHARS = 1_500

_NON_INSTRUMENT_ACTIONS = {
    "generate_plot",
    "analyse_data",
    "query_database",
    "list_samples",
    "extract_and_check_feasibility",
}

_BASE_SYSTEM_PROMPT = """\
You are MAESTRO, an agentic orchestrator for a self-driving scientific laboratory.

TOOL CALLING RULES:
1. Physical instrument tasks (synthesise, characterise, optimise_condition) → call plan_workflow
   with ALL steps in one call. The user reviews and approves before execution begins.
2. Data/analysis tasks → call query_database, generate_plot, analyse_data, or list_samples
   DIRECTLY. Do NOT wrap these inside plan_workflow. They execute immediately without approval.
3. Paper reproduction → call extract_and_check_feasibility first, then plan_workflow.
4. Conversational questions about the lab, results, papers, or settings → answer in text.
   Only call query_database if you need live data not already in the lab state message.
5. NEVER wrap query_database, generate_plot, analyse_data, or list_samples inside plan_workflow.

KNOWLEDGE ROUTING — always check the KNOWLEDGE STORES section in the lab state message first:
  - Questions about papers/literature → check PAPERS list, use document context
  - Questions about equipment manuals/limits → check MANUALS list
  - Questions about past experiments/protocols → query_database: SELECT * FROM protocols
  - Questions about consumables/stock → query_database: SELECT * FROM resources
  - Questions about results/measurements → check RESULTS SUMMARY or query evaluations table
  - Questions about optimisers → check OPTIMISERS list

CAPABILITY CHECK (before proposing any instrument workflow):
  1. Verify registered instruments can control the requested parameters.
  2. Verify registered instruments can measure the requested objective.
  3. Query resources table for consumable stock before experiments.
  4. If the lab cannot execute the request, explain what is missing.

DATABASE TABLES:
  evaluations: condition_name, condition_value, parameters (JSON), objective_name, objective_value, timestamp
  resources:   resource_id, name, unit, current_stock, min_stock, consumption_rules (JSON)
  protocols:   protocol_id, name, description, optimiser_used, results_summary, notes, workflow_plan

OPTIMISE_CONDITION step — required fields:
  condition_label, condition_value, condition_unit,
  free_params [{name, min, max, unit}], objective_metric,
  optimiser_name: "gp_bo" | "random" | "optuna" | "honegumi" | "deap",
  n_calls, n_initial_points

  DISTINCTION: condition_label/value = FIXED external variable (e.g. power_W=150).
  free_params = variables the optimiser SEARCHES OVER (e.g. active_material, porosity).
  These are separate concepts — never confuse them.

SAMPLE IDs: S-001, S-002, ... persisted across session.
STYLE: Precise, concise, honest about uncertainty.
"""

# ── System prompt caching ─────────────────────────────────────────────────────
# Rebuilding the full prompt on every call is wasteful. Cache by a fingerprint
# of the registry + documents + lab settings. Invalidated automatically when
# instruments, documents, or lab name change.

_prompt_cache:      dict[str, str] = {}
_prompt_cache_lock: threading.Lock = threading.Lock()


def _registry_fingerprint() -> str:
    from app.core.tool_registry import TOOL_REGISTRY
    from app.core.lab_config import get_lab_settings
    from app.core.documents import DOCUMENTS

    settings = get_lab_settings()
    parts = [
        ",".join(sorted(t.tool_id for t in TOOL_REGISTRY.list_all())),
        ",".join(sorted(DOCUMENTS.keys())),
        settings.lab_name,
        settings.system_prompt_extension[:64],
        ",".join(lib.name for lib in settings.optimisation_library if lib.enabled),
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def build_dynamic_system_prompt() -> str:
    fingerprint = _registry_fingerprint()
    with _prompt_cache_lock:
        if fingerprint in _prompt_cache:
            return _prompt_cache[fingerprint]

    from app.core.tool_registry import TOOL_REGISTRY
    from app.core.lab_config import get_lab_settings
    from app.core.documents import DOCUMENTS

    settings = get_lab_settings()

    extension = (
        f"\nLAB CONTEXT:\n{settings.system_prompt_extension.strip()[:600]}"
        if settings.system_prompt_extension.strip()
        else ""
    )

    enabled_libs = [lib for lib in settings.optimisation_library if lib.enabled]
    opt_context  = (
        f"\nAVAILABLE OPTIMISERS: {', '.join(lib.name for lib in enabled_libs)}"
        if enabled_libs else ""
    )

    doc_lines: list[str] = []
    if DOCUMENTS:
        doc_lines.append("\nKNOWLEDGE LIBRARY (documents loaded and searchable):")
        for doc in DOCUMENTS.values():
            meta = []
            if doc.year:
                meta.append(str(doc.year))
            if doc.authors:
                meta.append(doc.authors[0] + (" et al." if len(doc.authors) > 1 else ""))
            meta_str = f" ({', '.join(meta)})" if meta else ""
            doc_lines.append(f"  [{doc.document_id[:8]}] {doc.title or doc.filename}{meta_str}")

    prompt = (
        _BASE_SYSTEM_PROMPT
        + extension
        + opt_context
        + "\n".join(doc_lines)
        + "\nINSTRUMENTS:\n"
        + TOOL_REGISTRY.to_llm_context()
        + "\nDB SCHEMA:\n"
        + DB_SCHEMA
    )

    with _prompt_cache_lock:
        if len(_prompt_cache) >= 4:
            oldest = next(iter(_prompt_cache))
            del _prompt_cache[oldest]
        _prompt_cache[fingerprint] = prompt

    return prompt


# ── Message trimming ──────────────────────────────────────────────────────────

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


# ── RAG retrieval ─────────────────────────────────────────────────────────────

_PURELY_OPERATIONAL = re.compile(
    r'^\s*(reset|abort|stop|cancel|run|execute|approve|confirm|yes|no|ok|okay'
    r'|proceed|go ahead|sounds good|do it|start)\s*[.!]?\s*$',
    re.IGNORECASE,
)


def _should_retrieve_docs(session, query: str) -> bool:
    from app.core.documents import DOCUMENTS
    if not DOCUMENTS:
        return False
    return not bool(_PURELY_OPERATIONAL.match(query.strip()))


def _retrieve_doc_context(session, query: str) -> str:
    from app.core.documents import DOCUMENTS, retrieve_relevant_passages

    if not _should_retrieve_docs(session, query):
        return ""

    chunks: list[str] = []
    budget = _DOC_CONTEXT_CHARS

    if session.active_document_id and session.active_document_id in DOCUMENTS:
        active_doc = DOCUMENTS[session.active_document_id]

        structure_query = re.search(
            r'\b(section|chapter|figure|table|abstract|introduction|conclusion|'
            r'summary|content|structure|available|list)\b',
            query, re.IGNORECASE,
        )
        toc_block = ""
        if structure_query and active_doc.sections:
            toc_lines = [f"Document: {active_doc.title or active_doc.filename}"]
            toc_lines.append(f"Sections ({len(active_doc.sections)}):")
            for i, s in enumerate(active_doc.sections):
                indent  = "  " * min(s.level - 1, 2)
                preview = s.content[:80].replace("\n", " ") if s.content else ""
                toc_lines.append(f"  {indent}{i+1}. {s.heading} — {preview}...")
            if active_doc.figures:
                toc_lines.append(f"Figures: {len(active_doc.figures)}")
            if active_doc.tables:
                toc_lines.append(f"Tables: {len(active_doc.tables)}")
            toc_block = "\n".join(toc_lines)

        try:
            passages = retrieve_relevant_passages(
                session.active_document_id,
                query=query,
                top_k=3,
                max_chars=budget - len(toc_block),
            )
            content_parts: list[str] = []
            if toc_block:
                content_parts.append(toc_block)
            if passages:
                content_parts.append("\n".join(passages))
            if content_parts:
                chunks.append(
                    f"[{active_doc.title or active_doc.filename} — active]\n"
                    + "\n\n".join(content_parts)
                )
        except Exception:
            pass

    return ("DOCUMENT CONTEXT:\n" + "\n".join(chunks)) if chunks else ""


# ── Tool call integrity ───────────────────────────────────────────────────────

def _sweep_unanswered_tool_calls(messages: list) -> None:
    """
    Inject synthetic tool responses for any tool_call_id that has no matching
    tool response message. Mutates the list in place.
    Prevents HTTP 400 from the OpenAI API on subsequent turns.
    """
    responded = {
        m["tool_call_id"]
        for m in messages
        if m.get("role") == "tool" and m.get("tool_call_id")
    }
    injections: list[tuple[int, dict]] = []
    for i, msg in enumerate(messages):
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
        messages.insert(insert_idx, tool_msg)


# ── Lab context message (per-turn state snapshot) ─────────────────────────────

def build_lab_context_message(session) -> dict:
    from app.core.tool_registry import TOOL_REGISTRY
    from app.core.documents import DOCUMENTS
    from app.core.lab_config import get_lab_settings
    from datetime import datetime

    now      = datetime.now()
    results  = session.agent_state.results_store
    n_evals  = sum(len(r.get("X", [])) for r in results)
    n_instrs = len(TOOL_REGISTRY.list_all())
    settings = get_lab_settings()

    # ── Inline results summary ────────────────────────────────────────────────
    # Gives the agent immediate awareness of best results without a DB round-trip.
    results_summary = ""
    if results:
        best_entries = [
            f"  {r.get('condition_label')}={r.get('condition_value')} "
            f"[{r.get('optimiser_name', '?')}]: "
            f"best={r['best_objective']:.4f}, n={len(r.get('X', []))}"
            for r in results
            if r.get("best_objective") is not None
        ]
        if best_entries:
            results_summary = "\nRESULTS SUMMARY:\n" + "\n".join(best_entries)

    # ── Knowledge stores manifest ─────────────────────────────────────────────
    knowledge_lines = ["\nKNOWLEDGE STORES:"]

    papers  = [d for d in settings.document_library if d.doc_type == "paper"]
    manuals = [d for d in settings.document_library if d.doc_type == "manual"]

    if papers:
        knowledge_lines.append(f"  PAPERS ({len(papers)}):")
        for d in papers:
            knowledge_lines.append(f"    [{d.document_id[:8]}] \"{d.title or d.filename}\"")
    else:
        knowledge_lines.append("  PAPERS: none uploaded")

    if manuals:
        knowledge_lines.append(f"  MANUALS ({len(manuals)}):")
        for d in manuals:
            knowledge_lines.append(f"    [{d.document_id[:8]}] \"{d.title or d.filename}\"")
    else:
        knowledge_lines.append("  MANUALS: none uploaded")

    knowledge_lines.append(
        "  PROTOCOLS: query with SELECT * FROM protocols ORDER BY created_at DESC"
    )
    knowledge_lines.append(
        "  RESOURCES: query with SELECT * FROM resources"
    )
    opt_names = [lib.name for lib in settings.optimisation_library if lib.enabled]
    knowledge_lines.append(
        f"  OPTIMISERS ({len(opt_names)}): " + ", ".join(opt_names)
    )
    knowledge_lines.append(
        f"  EVALUATIONS ({n_evals} recorded): "
        "query with SELECT * FROM evaluations ORDER BY timestamp DESC LIMIT 20"
    )

    knowledge_manifest = "\n".join(knowledge_lines)

    # ── Active document ───────────────────────────────────────────────────────
    doc_text = ""
    if session.active_document_id and session.active_document_id in DOCUMENTS:
        doc = DOCUMENTS[session.active_document_id]
        toc = ""
        if doc.sections:
            toc = " | Sections: " + ", ".join(s.heading for s in doc.sections[:6])
        doc_text = (
            f"\nACTIVE DOCUMENT: \"{doc.title or doc.filename}\""
            f" ({len(doc.sections)} sections, {len(doc.figures)} figs){toc}"
        )

    # ── Campaign ──────────────────────────────────────────────────────────────
    campaign_text = ""
    if session.extracted_campaign:
        c = session.extracted_campaign
        campaign_text = (
            f"\nACTIVE CAMPAIGN: \"{c.title}\" "
            f"(obj: {c.objective_metric}, "
            f"params: {[p['name'] for p in c.parameter_space]})"
        )

    return {
        "role": "system",
        "content": (
            f"[LAB STATE] {now.strftime('%H:%M')} | "
            f"Evals: {n_evals} | "
            f"Instruments: {n_instrs}"
            f"{campaign_text}{doc_text}"
            f"{results_summary}"
            f"{knowledge_manifest}"
        ),
    }


# ── Main LLM planning call ────────────────────────────────────────────────────

def llm_plan(session) -> dict:
    dynamic_system = build_dynamic_system_prompt()

    # Sweep any unanswered tool calls BEFORE building the message list.
    _sweep_unanswered_tool_calls(session.agent_state.messages)

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


# ── LLM call with retry ───────────────────────────────────────────────────────

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


# ── Tool schema ───────────────────────────────────────────────────────────────

def build_tools_schema() -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": "plan_workflow",
                "description": (
                    "Propose a multi-step workflow for PHYSICAL INSTRUMENT tasks only "
                    "(synthesise, characterise, optimise_condition). "
                    "All steps in one call. Shown to user for approval before execution. "
                    "Do NOT use this for query_database, generate_plot, analyse_data, or list_samples."
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
                                    "kind":             {"type": "string", "enum": ["synthesise", "characterise", "optimise_condition"]},
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
                                    "free_params": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "min":  {"type": "number"},
                                                "max":  {"type": "number"},
                                                "unit": {"type": "string"},
                                            },
                                        },
                                    },
                                    "objective_metric": {"type": "string"},
                                    "optimiser_name":   {"type": "string"},
                                    "n_calls":          {"type": "integer"},
                                    "n_initial_points": {"type": "integer"},
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
                "description": (
                    "Extract an experimental campaign from an uploaded paper and check "
                    "whether the lab can reproduce it. Call this before plan_workflow "
                    "when the user asks to reproduce a paper result."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "case_name": {
                            "type": "string",
                            "description": "The case study, figure, or experiment to extract",
                        },
                    },
                    "required": ["case_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_samples",
                "description": "List all samples currently in the lab sample inventory.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_plot",
                "description": (
                    "Generate a matplotlib figure from experimental data. "
                    "Write pure matplotlib code — no imports, no plt.savefig(), plt.show(), "
                    "or plt.tight_layout() (these are handled automatically). "
                    "Available variables: results_store (list of dicts), sample_registry (list of dicts). "
                    "results_store[i] keys: condition_label, condition_value, optimiser_name, "
                    "param_names, X (list of param vectors), y (list of objective values), "
                    "best_params, best_objective, failed_samples. "
                    "Always inspect results_store structure dynamically at runtime. "
                    "If results_store is empty, display a 'No data yet' message using ax.text()."
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
                    "Run statistical analysis using numpy/scipy. "
                    "Every computed value MUST be printed — use print() for all results. "
                    "Available variables: results_store, sample_registry."
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
                "description": (
                    "Run a read-only SQL SELECT query against the lab database. "
                    "Tables: evaluations (results), resources (consumables), protocols (saved experiments). "
                    "Use this to answer questions about past results, stock levels, or saved protocols."
                ),
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