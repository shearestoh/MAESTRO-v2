"""
LLM interface for MAESTRO.

Architecture: lean always-injected context + on-demand retrieval via tools.

Always injected (small, ~2KB):
  - Base rules and tool instructions
  - Registered instrument registry (names, parameters, outputs)
  - Lab identity and safety rules
  - Document title list (not full summaries)
  - Current session state (evaluations count, active campaign)

Retrieved on demand via tools:
  - Document content → retrieve_relevant_passages() called by extract_and_check_feasibility
  - Resource inventory → query_database("SELECT * FROM resources")
  - Protocols → query_database("SELECT * FROM protocols")
  - Results → query_database("SELECT * FROM evaluations ...")
  - Sample registry → list_samples tool
"""
from __future__ import annotations

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

_MAX_PROMPT_CHARS  = 24_000
_MAX_OUTPUT_TOKENS = 4_000

_INSTRUMENT_ACTIONS = {
    "synthesise",
    "characterise",
    "run_extracted_campaign",
}

_NON_INSTRUMENT_ACTIONS = {
    "generate_plot",
    "analyse_data",
    "query_database",
    "list_samples",
    "extract_and_check_feasibility",
}

_SYSTEM_PROMPT_CONTENT = ""


def _total_chars(messages: list) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages)


def trim_messages_to_budget(
    messages:    list,
    max_chars:   int = _MAX_PROMPT_CHARS,
    keep_last_n: int = 12,
) -> list:
    if not messages:
        return messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs  = [m for m in messages if m.get("role") != "system"]
    recent = other_msgs[-keep_last_n:] if len(other_msgs) > keep_last_n else other_msgs
    older  = other_msgs[:-keep_last_n] if len(other_msgs) > keep_last_n else []
    kept   = system_msgs + recent
    budget = max_chars - _total_chars(kept)
    for msg in reversed(older):
        msg_len = len(str(msg.get("content", "")))
        if budget - msg_len > 0:
            kept.insert(len(system_msgs), msg)
            budget -= msg_len
    sys_part   = [m for m in kept if m.get("role") == "system"]
    other_part = [m for m in kept if m.get("role") != "system"]
    try:
        other_part.sort(key=lambda m: messages.index(m))
    except ValueError:
        pass
    return sys_part + other_part


_BASE_SYSTEM_PROMPT = """\
You are MAESTRO, an agentic orchestrator for a self-driving scientific laboratory.
Help scientists design, execute, and analyse experimental campaigns across any scientific domain.

RULES:
- Instrument actions (synthesise, characterise, optimise_condition) → call plan_workflow ONCE with ALL steps; await user approval before execution.
- CRITICAL: Always combine all steps into a SINGLE plan_workflow call. Never call plan_workflow multiple times for the same user request.
- Non-instrument actions (analysis, plotting, database queries, document questions) → execute immediately without a plan.
- Paper reproduction → call extract_and_check_feasibility, then present as a workflow plan.

CAPABILITY AWARENESS — CHECK BEFORE PROPOSING ANY WORKFLOW:
  Before proposing a workflow, verify the registered instruments can execute the task:
  1. PARAMETERS: Does any instrument control the requested parameters? Match user terminology to instrument parameter names and descriptions. Ask a clarifying question if ambiguous.
  2. OUTPUTS: Does any instrument measure the requested objective? If not, state clearly what is missing.
  3. RESOURCES: Query the resources table to check consumable stock before running experiments that consume materials.
  4. HISTORY: Query the protocols table to find relevant past experiments before starting new ones.
  If the lab CANNOT execute the request, explain which instruments are registered and what is missing.

DATABASE RETRIEVAL — USE THESE QUERIES:
  Resource inventory:  SELECT * FROM resources
  Protocols/history:   SELECT protocol_id, name, description, optimiser_used, results_summary, created_at FROM protocols ORDER BY created_at DESC
  Past results:        SELECT condition_name, condition_value, objective_name, objective_value, parameters FROM evaluations ORDER BY timestamp DESC LIMIT 20
  Sample notebook:     Use the list_samples tool

MULTI-STEP WORKFLOWS — CRITICAL:
  Put ALL steps in a SINGLE plan_workflow call. Each step MUST include a "label" field.
  Example for "optimise <objective> at <condA> and <condB> using two optimisers":
    plan_workflow(summary="...", steps=[
      {"kind": "optimise_condition", "label": "Optimise <objective> at <condA> [gp_bo]",
       "condition_label": "<name>", "condition_value": <A>, "condition_unit": "<unit>",
       "free_params": [{"name": "<p>", "min": <lo>, "max": <hi>, "unit": "<u>"}],
       "objective_metric": "<out>", "optimiser_name": "gp_bo", "n_calls": <n>, "n_initial_points": <k>},
      ... (repeat for each condition × optimiser combination)
    ])

OPTIMISE_CONDITION — ALL FIELDS REQUIRED:
  label, condition_label, condition_value, condition_unit,
  free_params [{name, min, max, unit}], objective_metric,
  optimiser_name: "gp_bo" | "random" | "optuna" | "honegumi" | "deap",
  n_calls, n_initial_points

SYNTHESISE: label, instrument, params {dict}
CHARACTERISE: label, sample_ref, conditions {dict}, measures

RESULTS STORE (for generate_plot / analyse_data):
  results_store[i] keys: condition_label, condition_value, optimiser_name,
  param_names, X (param vectors), y (objective values), best_params, best_objective, failed_samples
  Always use loops — never hardcode variable names from the task.
  Always call print() for every computed value in analyse_data.

SAMPLE IDs: S-001, S-002, ... persisted across the session.
OPTIMISERS: specify optimiser_name per step. Default: "gp_bo".
SAFETY: Respect limits in equipment manuals and lab context.
STYLE: Precise, concise, honest about uncertainty. Scientific collaborator.
"""


def build_dynamic_system_prompt() -> str:
    from app.core.tool_registry import TOOL_REGISTRY
    from app.core.lab_config import get_lab_settings
    from app.core.documents import DOCUMENTS

    settings = get_lab_settings()

    # Lab context extension (user-defined, kept small)
    extension = ""
    if settings.system_prompt_extension.strip():
        extension = f"\n\nLAB CONTEXT:\n{settings.system_prompt_extension.strip()}"

    # Optimisation library — names and capabilities only (not full descriptions)
    opt_context = ""
    if settings.optimisation_library:
        enabled = [lib for lib in settings.optimisation_library if lib.enabled]
        if enabled:
            lines = ["\nAVAILABLE OPTIMISATION LIBRARIES:"]
            for lib in enabled:
                caps = ", ".join(lib.capabilities[:3]) if lib.capabilities else "general"
                lines.append(f"  {lib.name} [{caps}]")
            opt_context = "\n".join(lines)

    # Document registry — titles only, not summaries
    # Full content is retrieved on demand via retrieve_relevant_passages()
    doc_registry = ""
    if DOCUMENTS:
        lines = ["\nKNOWLEDGE LIBRARY (query these documents for details):"]
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
        + "\n\nREGISTERED INSTRUMENTS:\n"
        + TOOL_REGISTRY.to_llm_context()
        + "\nDATABASE SCHEMA:\n"
        + DB_SCHEMA
    )


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
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message


def build_tools_schema() -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": "plan_workflow",
                "description": (
                    "Propose a workflow plan for any task that involves using instruments. "
                    "All steps in a single call. Plan is shown to user for approval."
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
                                    "kind": {
                                        "type": "string",
                                        "enum": [
                                            "synthesise", "characterise",
                                            "optimise_condition", "list_samples",
                                            "query_database", "generate_plot",
                                            "analyse_data",
                                        ],
                                    },
                                    "label":            {"type": "string", "description": "REQUIRED. Short human-readable label."},
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
                                    "optimiser_name": {
                                        "type": "string",
                                        "description": "gp_bo | random | optuna | honegumi | deap",
                                    },
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
                "description": "Extract an experimental campaign from an uploaded paper and check feasibility.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "case_name": {"type": "string", "description": "The specific case study to extract"},
                    },
                    "required": ["case_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_samples",
                "description": "List all samples in the lab sample inventory (synthesised and characterised samples).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_plot",
                "description": (
                    "Generate a matplotlib figure from experimental data. "
                    "Write pure matplotlib code — no imports, no plt.savefig().\n"
                    "CRITICAL: NEVER hardcode variable names from the task. ALWAYS use loops over results_store.\n"
                    "Available: results_store (list of dicts with keys: condition_label, condition_value, "
                    "optimiser_name, param_names, X, y, best_params, best_objective, failed_samples), "
                    "sample_registry (list of sample dicts).\n"
                    "CORRECT: for r in results_store: label = f\"{r['condition_label']}={r['condition_value']}\"\n"
                    "WRONG: best_obj_90w = ...  # hardcoded — will crash"
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
                    "Run statistical analysis using numpy/scipy. Print ALL results with print().\n"
                    "CRITICAL: Every computed value MUST be printed — silent code produces blank output.\n"
                    "Available: results_store (list of dicts with keys: condition_label, condition_value, "
                    "optimiser_name, param_names, X, y, best_params, best_objective, failed_samples), "
                    "sample_registry.\n"
                    "CORRECT: for r in results_store: print(f\"{r['condition_label']}={r['condition_value']}: best={r.get('best_objective')}\")\n"
                    "WRONG: best = results_store[0]['best_objective']  # computed but not printed"
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
                    "Run a read-only SQL SELECT query. Use for:\n"
                    "  - Experimental results: SELECT * FROM evaluations\n"
                    "  - Resource/consumable inventory: SELECT * FROM resources\n"
                    "  - Past protocols/history: SELECT * FROM protocols\n"
                    "Only SELECT statements are permitted."
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


def build_lab_context_message(session) -> dict:
    from app.core.tool_registry import TOOL_REGISTRY
    from app.core.documents import get_document
    from datetime import datetime
    import re

    now       = datetime.now()
    hour      = now.hour
    time_str  = now.strftime("%A, %d %B %Y %H:%M:%S")
    is_office = 9 <= hour < 17
    office_note = "office hours" if is_office else "outside office hours"

    total_evals  = sum(len(r.get("X", [])) for r in session.agent_state.results_store)
    tool_summary = f"{len(TOOL_REGISTRY.list_all())} instruments registered"

    campaign_text = ""
    if session.extracted_campaign:
        c = session.extracted_campaign
        campaign_text = (
            f" | ACTIVE CAMPAIGN: '{c.title}' "
            f"(objective: {c.objective_metric}, "
            f"params: {[p['name'] for p in c.parameter_space]})"
        )

    # Active document context — section TOC only when a document is loaded
    doc_context_text = ""
    if session.active_document_id:
        try:
            doc = get_document(session.active_document_id)
            meta_lines = []
            if doc.authors:
                meta_lines.append(f"Authors: {', '.join(doc.authors[:3])}")
            if doc.year:
                meta_lines.append(f"Year: {doc.year}")
            if doc.doi:
                meta_lines.append(f"DOI: {doc.doi}")

            section_toc = ""
            if doc.sections:
                toc_lines = [f"\nSections ({len(doc.sections)}):"]
                for i, s in enumerate(doc.sections[:20]):
                    indent  = "  " * min(s.level - 1, 2)
                    toc_lines.append(f"  {indent}{i + 1}. {s.heading}")
                section_toc = "\n".join(toc_lines)

            doc_context_text = (
                f"\nACTIVE DOCUMENT: {doc.title or doc.filename}"
                + ("\n" + "\n".join(meta_lines) if meta_lines else "")
                + f"\n{len(doc.sections)} sections | {len(doc.figures)} figures | {len(doc.tables)} tables"
                + section_toc
            )
        except Exception:
            doc_context_text = "\nDocument loaded but metadata unavailable."

    return {
        "role": "system",
        "content": (
            f"[LAB STATE] "
            f"Time: {time_str} ({office_note}) | "
            f"Evaluations: {total_evals} | "
            f"Lab: {tool_summary}"
            f"{campaign_text}"
            f"{doc_context_text}"
        ),
    }


def _repair_tool_call_chain(messages: list) -> list:
    import json as _json
    responded_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id:
                responded_ids.add(tc_id)
    injections: list[tuple[int, dict]] = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []):
            tc_id   = tc.get("id")
            tc_name = tc.get("function", {}).get("name", "unknown_tool")
            if tc_id and tc_id not in responded_ids:
                injections.append((i + 1, {
                    "role":         "tool",
                    "tool_call_id": tc_id,
                    "name":         tc_name,
                    "content":      _json.dumps({
                        "status":  "completed",
                        "message": f"Tool '{tc_name}' executed.",
                    }),
                }))
                responded_ids.add(tc_id)
    for insert_idx, tool_msg in reversed(injections):
        messages.insert(insert_idx, tool_msg)
    return messages


def llm_plan(session) -> dict:
    dynamic_system = build_dynamic_system_prompt()
    messages       = list(session.agent_state.messages)

    if messages and messages[0].get("role") == "system":
        messages[0] = {"role": "system", "content": dynamic_system}
    else:
        messages.insert(0, {"role": "system", "content": dynamic_system})

    augmented    = messages + [build_lab_context_message(session)]
    augmented    = _repair_tool_call_chain(augmented)
    tools_schema = build_tools_schema()

    last_user_msg = ""
    for m in reversed(session.agent_state.messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "").lower()
            break

    doc_keywords = {
        "figure", "table", "paper", "author", "published", "year",
        "case study", "section", "abstract", "introduction", "results",
        "conclusion", "method", "study", "research", "show me", "what is",
        "explain", "summarise", "summarize", "describe", "tell me about",
        "who", "when", "reference", "citation", "finding", "discuss",
        "manual", "instrument", "equipment", "safety", "hazard", "limit",
        "doi", "journal", "volume", "issue",
    }
    is_doc_query = (
        session.active_document_id is not None
        and any(kw in last_user_msg for kw in doc_keywords)
    )

    if is_doc_query:
        session.equipment_status = EquipmentStatusModel(knowledge=True)

    msg = call_llm(augmented, tools=tools_schema)

    if is_doc_query:
        session.equipment_status = EquipmentStatusModel()

    entry: dict = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        entry["tool_calls"] = [
            {
                "id":   tc.id,
                "type": "function",
                "function": {
                    "name":      tc.function.name,
                    "arguments": tc.function.arguments,
                },
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