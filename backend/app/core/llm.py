"""
LLM interface for MAESTRO.

Context strategy:
  Always injected: base rules, instrument registry, lab identity,
  document title list (with type), optimisation library, database schema.

  Retrieved on demand (when documents are loaded):
  Relevant passages are retrieved for every user message when documents
  are present — no keyword gate. The LLM decides what to do with the context.
  If no relevant passages are found, nothing is injected.
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

_NON_INSTRUMENT_ACTIONS = {
    "generate_plot",
    "analyse_data",
    "query_database",
    "list_samples",
    "extract_and_check_feasibility",
}

_BASE_SYSTEM_PROMPT = """\
You are MAESTRO, an agentic orchestrator for a self-driving scientific laboratory.
Help scientists design, execute, and analyse experimental campaigns across any scientific domain.

RULES:
- Instrument actions (synthesise, characterise, optimise_condition) → call plan_workflow ONCE with ALL steps; await user approval before execution.
- CRITICAL: Always combine all steps into a SINGLE plan_workflow call. Never call plan_workflow multiple times for the same user request.
- Non-instrument actions (analysis, plotting, database queries, document questions) → execute immediately without a plan.
- Paper/case study reproduction → call extract_and_check_feasibility, then the extracted campaign will be presented as a workflow plan.

CAPABILITY AWARENESS — ALWAYS CHECK BEFORE PROPOSING ANY WORKFLOW:
  Before proposing any workflow (from user request, paper, or database), verify the registered instruments can execute it:
  1. PARAMETERS: Does any registered instrument control the requested parameters? If not, state what is missing.
  2. OUTPUTS: Does any registered instrument measure the requested objective? If not, state what is missing.
  3. RESOURCES: Query the resources table to check consumable stock before experiments that consume materials.
  4. HISTORY: Query the protocols table to find relevant past experiments before starting new ones.
  5. MANUALS: If equipment manuals are in the Knowledge Library (shown in RETRIEVED DOCUMENT CONTEXT), check safety limits and operating ranges before proposing parameter values.
  If the lab CANNOT execute the request with registered instruments, explain clearly what is missing and what would need to be added. NEVER propose a workflow for parameters or objectives that no registered instrument handles.

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
SAFETY: Respect limits stated in equipment manuals (shown in RETRIEVED DOCUMENT CONTEXT when available).
STYLE: Precise, concise, honest about uncertainty. Scientific collaborator.
"""


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
    recent      = other_msgs[-keep_last_n:] if len(other_msgs) > keep_last_n else other_msgs
    older       = other_msgs[:-keep_last_n] if len(other_msgs) > keep_last_n else []
    kept        = system_msgs + recent
    budget      = max_chars - _total_chars(kept)
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


def build_dynamic_system_prompt() -> str:
    from app.core.tool_registry import TOOL_REGISTRY
    from app.core.lab_config import get_lab_settings, get_document_library
    from app.core.documents import DOCUMENTS

    settings = get_lab_settings()

    extension = ""
    if settings.system_prompt_extension.strip():
        extension = f"\n\nLAB CONTEXT:\n{settings.system_prompt_extension.strip()}"

    opt_context = ""
    if settings.optimisation_library:
        enabled = [lib for lib in settings.optimisation_library if lib.enabled]
        if enabled:
            lines = ["\nAVAILABLE OPTIMISATION LIBRARIES:"]
            for lib in enabled:
                caps = ", ".join(lib.capabilities[:3]) if lib.capabilities else "general"
                lines.append(f"  {lib.name} [{caps}]")
            opt_context = "\n".join(lines)

    # Document registry — titles, type, and basic metadata
    # Full content retrieved on demand via _retrieve_doc_context()
    doc_registry = ""
    if DOCUMENTS:
        library_entries = {e.document_id: e for e in get_document_library()}
        lines = ["\nKNOWLEDGE LIBRARY:"]
        for doc in DOCUMENTS.values():
            meta = []
            if doc.year:
                meta.append(str(doc.year))
            if doc.authors:
                meta.append(doc.authors[0] + (" et al." if len(doc.authors) > 1 else ""))
            meta_str = f" ({', '.join(meta)})" if meta else ""
            entry    = library_entries.get(doc.document_id)
            doc_type = f" [{entry.doc_type}]" if entry else " [paper]"
            lines.append(f"  [{doc.document_id[:8]}] {doc.title or doc.filename}{meta_str}{doc_type}")
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


def _retrieve_doc_context(session, query: str, max_chars: int = 3500) -> str:
    """
    Retrieve relevant passages from all loaded documents for the given query.
    No keyword gate — called whenever documents are present.
    Returns empty string if nothing relevant is found.
    """
    from app.core.documents import DOCUMENTS, retrieve_relevant_passages

    if not DOCUMENTS:
        return ""

    # Prioritise the active document, then search others
    doc_ids = []
    if session.active_document_id and session.active_document_id in DOCUMENTS:
        doc_ids.append(session.active_document_id)
    for doc_id in DOCUMENTS:
        if doc_id not in doc_ids:
            doc_ids.append(doc_id)

    # Cap at 3 documents to stay within context budget
    doc_ids = doc_ids[:3]
    budget_per_doc = max_chars // len(doc_ids)
    chunks = []

    for doc_id in doc_ids:
        doc = DOCUMENTS[doc_id]
        try:
            passages = retrieve_relevant_passages(
                doc_id, query=query, top_k=3, max_chars=budget_per_doc
            )
            if passages:
                chunks.append(
                    f"\n--- {doc.title or doc.filename} ---\n" + "\n\n".join(passages)
                )
        except Exception:
            pass

    if not chunks:
        return ""

    return "RETRIEVED DOCUMENT CONTEXT:\n" + "\n".join(chunks)


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
                    "Propose a multi-step workflow plan for tasks that involve using lab instruments. "
                    "All steps go in a single call. The plan is shown to the user for approval before execution. "
                    "Only call this when the registered instruments can handle the requested parameters and objectives."
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
                "description": (
                    "Extract a structured experimental campaign from an uploaded scientific paper "
                    "and check whether the registered lab instruments can reproduce it. "
                    "Use this when the user wants to reproduce, replicate, or adapt a result from a paper."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "case_name": {
                            "type": "string",
                            "description": "The specific case study, figure, or experiment to extract from the paper",
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
                "description": "List all samples currently in the lab sample inventory (synthesised and characterised).",
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
                    "Available variables:\n"
                    "  results_store: list of dicts, each with keys:\n"
                    "    condition_label (str), condition_value (float), optimiser_name (str),\n"
                    "    param_names (list[str]), X (list[list[float]]), y (list[float]),\n"
                    "    best_params (dict), best_objective (float|None), failed_samples (int)\n"
                    "  sample_registry: list of sample dicts\n"
                    "RULES:\n"
                    "  - Always inspect results_store structure before plotting — never assume shape.\n"
                    "  - Use loops over results_store, never hardcode condition or parameter names.\n"
                    "  - Handle empty results_store gracefully (show a 'No data' message).\n"
                    "  - Choose the most informative plot type for the data available."
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
                    "Run statistical analysis using numpy/scipy. Every computed value MUST be printed.\n"
                    "Available: results_store (same structure as generate_plot), sample_registry.\n"
                    "Always inspect the data structure before computing — never assume field names."
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
                    "Run a read-only SQL SELECT query against the lab database. Use for:\n"
                    "  - Experimental results: SELECT * FROM evaluations\n"
                    "  - Consumable inventory: SELECT * FROM resources\n"
                    "  - Past protocols and history: SELECT * FROM protocols\n"
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
    from datetime import datetime

    now         = datetime.now()
    time_str    = now.strftime("%A, %d %B %Y %H:%M:%S")
    office_note = "office hours" if 9 <= now.hour < 17 else "outside office hours"
    total_evals = sum(len(r.get("X", [])) for r in session.agent_state.results_store)

    campaign_text = ""
    if session.extracted_campaign:
        c = session.extracted_campaign
        campaign_text = (
            f" | ACTIVE CAMPAIGN: '{c.title}' "
            f"(objective: {c.objective_metric}, "
            f"params: {[p['name'] for p in c.parameter_space]})"
        )

    doc_context_text = ""
    if session.active_document_id:
        from app.core.documents import DOCUMENTS
        doc = DOCUMENTS.get(session.active_document_id)
        if doc:
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
                for i, s in enumerate(doc.sections[:15]):
                    indent = "  " * min(s.level - 1, 2)
                    toc_lines.append(f"  {indent}{i + 1}. {s.heading}")
                section_toc = "\n".join(toc_lines)
            doc_context_text = (
                f"\nACTIVE DOCUMENT: {doc.title or doc.filename}"
                + ("\n" + "\n".join(meta_lines) if meta_lines else "")
                + f"\n{len(doc.sections)} sections | {len(doc.figures)} figures | {len(doc.tables)} tables"
                + section_toc
            )

    return {
        "role": "system",
        "content": (
            f"[LAB STATE] Time: {time_str} ({office_note}) | "
            f"Evaluations: {total_evals} | "
            f"{len(TOOL_REGISTRY.list_all())} instruments registered"
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

    # Replace or prepend the system message
    if messages and messages[0].get("role") == "system":
        messages[0] = {"role": "system", "content": dynamic_system}
    else:
        messages.insert(0, {"role": "system", "content": dynamic_system})

    # Get the last user message for RAG retrieval
    last_user_msg = next(
        (m.get("content", "") for m in reversed(session.agent_state.messages)
         if m.get("role") == "user"),
        "",
    )

    # Retrieve relevant document context whenever documents are loaded.
    # No keyword gate — the LLM decides what to do with the context.
    # Equipment status is set to show the knowledge indicator in the UI.
    if last_user_msg:
        from app.core.documents import DOCUMENTS
        if DOCUMENTS:
            session.equipment_status = EquipmentStatusModel(knowledge=True)
            doc_context = _retrieve_doc_context(session, query=last_user_msg, max_chars=3500)
            if doc_context:
                messages.append({"role": "system", "content": doc_context})
            session.equipment_status = EquipmentStatusModel()

    augmented    = messages + [build_lab_context_message(session)]
    augmented    = _repair_tool_call_chain(augmented)
    tools_schema = build_tools_schema()

    msg = call_llm(augmented, tools=tools_schema)

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