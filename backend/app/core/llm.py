"""
LLM interface for MAESTRO.

System prompt is built dynamically from lab config, registered instruments,
available optimisation libraries, library documents (RAG), and the DB schema.

Model: gpt-4o-mini via GitHub Models (Azure inference endpoint).
Context window: 128K tokens. GitHub free-tier enforces ~8K input tokens per
request, so _MAX_PROMPT_CHARS is set conservatively to stay within that limit.
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

# GitHub Models free tier: ~8K input tokens per request (~4 chars/token).
# Reserve ~2K tokens for system prompt + dynamic context + response headroom.
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

WORKFLOW STEP KINDS:
- synthesise: prepare a physical sample using a synthesis instrument
- characterise: measure a prepared sample using a characterisation instrument
- optimise_condition: closed-loop optimisation campaign — specify optimiser_name per step
- generate_plot, analyse_data, query_database, list_samples: immediate, no approval needed

MULTI-STEP WORKFLOWS — CRITICAL:
  When the user requests multiple optimisation experiments, put ALL steps in a SINGLE
  plan_workflow call. Each step MUST include a "label" field.

  Example for "optimise <objective> at <condA> and <condB> using two optimisers":
    plan_workflow(
      summary="Optimise <objective> at <condA> and <condB> using GP-BO and Random Search",
      steps=[
        {
          "kind": "optimise_condition",
          "label": "Optimise <objective> at <condA> [gp_bo]",
          "condition_label": "<condition_name>",
          "condition_value": <condA_value>,
          "condition_unit": "<unit>",
          "free_params": [{"name": "<param1>", "min": <lo>, "max": <hi>, "unit": "<unit>"}],
          "objective_metric": "<output_name>",
          "optimiser_name": "gp_bo",
          "n_calls": <n>,
          "n_initial_points": <k>
        },
        {
          "kind": "optimise_condition",
          "label": "Optimise <objective> at <condA> [random]",
          "condition_label": "<condition_name>",
          "condition_value": <condA_value>,
          "condition_unit": "<unit>",
          "free_params": [{"name": "<param1>", "min": <lo>, "max": <hi>, "unit": "<unit>"}],
          "objective_metric": "<output_name>",
          "optimiser_name": "random",
          "n_calls": <n>,
          "n_initial_points": <k>
        }
      ]
    )
  Repeat for each additional condition. Never split into separate plan_workflow calls.

OPTIMISE_CONDITION — ALL FIELDS REQUIRED:
  label: short description — ALWAYS INCLUDE, e.g. "Optimise yield at temperature=200 [gp_bo]"
  condition_label: name of the fixed operating condition (e.g. "temperature_C", "flow_rate")
  condition_value: numeric value — NEVER 0 unless 0 is genuinely correct
  condition_unit: unit string (e.g. "°C", "mL/min", "W")
  free_params: [{name, min, max, unit}] — parameters the optimiser searches over
  objective_metric: output to maximise — must match a registered instrument output
  optimiser_name: key of the algorithm — MUST be specified per step:
    "gp_bo"    → scikit-optimize GP-BO (default, always available)
    "random"   → uniform random search (always available)
    "optuna"   → Optuna TPE (pip install optuna)
    "honegumi" → Ax Platform (pip install ax-platform honegumi)
    "deap"     → Evolutionary (pip install deap)
  n_calls: total evaluations (integer)
  n_initial_points: random evaluations before model fitting (integer; ignored for random/deap)

SYNTHESISE — REQUIRED FIELDS:
  label: e.g. "Synthesise sample with <param>=<value>"
  instrument: name of the synthesis instrument
  params: dict of parameter name → value

CHARACTERISE — REQUIRED FIELDS:
  label: e.g. "Characterise <sample_ref> at <condition>=<value>"
  sample_ref: sample ID (e.g. "S-001") or "{{sample_id}}" if referencing a preceding synthesise step
  conditions: dict of test conditions
  measures: the output metric name

RESULTS STORE STRUCTURE (for generate_plot and analyse_data):
  results_store is a list of dicts. Each dict has:
    condition_label (str), condition_value (float), optimiser_name (str),
    param_names (list[str]), X (list of param vectors), y (list of objective floats),
    best_params (dict), best_objective (float or None), failed_samples (int)
  Access values as: results_store[0]["y"], results_store[0]["X"],
    results_store[0]["best_objective"], results_store[0]["optimiser_name"]

SAMPLE IDs: Each synthesised sample gets a unique ID (S-001, S-002, ...) persisted across the session.
OPTIMISERS: Specify optimiser_name per optimise_condition step based on user's request.
SAFETY: Respect any operating limits or safety constraints mentioned in equipment manuals or lab context.
STYLE: Be precise, concise, and honest about uncertainty. Speak as a scientific collaborator.
"""


def build_dynamic_system_prompt() -> str:
    from app.core.tool_registry import TOOL_REGISTRY
    from app.core.lab_config import get_lab_settings
    from app.core.documents import get_all_library_context

    settings = get_lab_settings()

    opt_context = ""
    if settings.optimisation_library:
        enabled = [lib for lib in settings.optimisation_library if lib.enabled]
        if enabled:
            lines = ["\nAVAILABLE OPTIMISATION LIBRARIES:\n"]
            for lib in enabled:
                caps = ", ".join(lib.capabilities) if lib.capabilities else "general"
                lines.append(f"- {lib.name}: {lib.description} [capabilities: {caps}]")
            opt_context = "\n".join(lines)

    extension = ""
    if settings.system_prompt_extension.strip():
        extension = f"\n\nLAB CONTEXT:\n{settings.system_prompt_extension.strip()}"

    library_context = get_all_library_context(max_chars_per_doc=800)
    if library_context:
        library_context = f"\n\n{library_context}"

    return (
        _BASE_SYSTEM_PROMPT
        + extension
        + opt_context
        + library_context
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
                    "Includes single-step tasks, multi-step tasks, optimisation campaigns, "
                    "and paper reproduction. The plan is shown to the user for review and "
                    "approval before execution."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "One-line summary of the proposed workflow",
                        },
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
                                    "optimiser_name": {
                                        "type": "string",
                                        "description": (
                                            "Optimiser key for optimise_condition steps. "
                                            "Options: 'gp_bo' (GP Bayesian Optimisation, default), "
                                            "'random' (Random Search), "
                                            "'optuna' (Optuna TPE, requires pip install optuna), "
                                            "'honegumi' (Ax Platform, requires pip install ax-platform honegumi), "
                                            "'deap' (Evolutionary, requires pip install deap). "
                                            "Use the key that matches the user's requested library."
                                        ),
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
                    "Extract an experimental campaign from an uploaded paper and check "
                    "whether the registered instruments can execute it. "
                    "After extraction, automatically present the campaign as a workflow plan."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "case_name": {
                            "type": "string",
                            "description": "The specific case study to extract",
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
                "description": "List all samples in the lab inventory.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_plot",
                        "description": (
                            "Generate a matplotlib figure from experimental data. "
                            "Write pure matplotlib code — no imports, no plt.savefig(). "
                            "\n\nCRITICAL RULES FOR PLOT CODE:"
                            "\n- NEVER hardcode variable names derived from the task (e.g. best_obj_90w_gpbo)."
                            "\n- ALWAYS iterate over results_store dynamically using loops."
                            "\n- ALWAYS check that results_store is non-empty before accessing elements."
                            "\n\nAvailable variables:"
                            "\n  results_store: list of dicts, each with keys:"
                            "\n    condition_label (str), condition_value (float), optimiser_name (str),"
                            "\n    param_names (list[str]),"
                            "\n    X (list of param vectors e.g. [[93.1, 35.2], ...]),"
                            "\n    y (list of objective floats e.g. [104.4, 98.5, ...]),"
                            "\n    best_params (dict), best_objective (float or None),"
                            "\n    failed_samples (int)"
                            "\n  sample_registry: list of sample dicts"
                            "\n\nCORRECT pattern — always use loops:"
                            "\n  for r in results_store:"
                            "\n      cond  = r['condition_value']"
                            "\n      opt   = r.get('optimiser_name', '')"
                            "\n      best  = r.get('best_objective')"
                            "\n      label = f'{r[\"condition_label\"]}={cond} [{opt}]'"
                            "\n\nWRONG pattern — never do this:"
                            "\n  best_obj_90_gpbo = ...  # hardcoded name — will crash"
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
                    "Print results to stdout — they appear in the chat.\n"
                    "Available variables:\n"
                    "  results_store: list of dicts with keys:\n"
                    "    condition_label, condition_value, param_names,\n"
                    "    X (param vectors), y (objective values),\n"
                    "    best_params, best_objective, failed_samples\n"
                    "  sample_registry: list of sample dicts\n"
                    "Example: y_vals = results_store[0]['y'] if results_store else []"
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
                    "Run a read-only SQL SELECT query against the experimental results database. "
                    "Only call when experiments have been run."
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

    now      = datetime.now()
    hour     = now.hour
    time_str = now.strftime("%A, %d %B %Y %H:%M:%S")
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
            f"params: {[p['name'] for p in c.parameter_space]}, "
            f"status: {c.status})"
        )

    doc_context_text = ""
    if session.active_document_id:
        try:
            doc = get_document(session.active_document_id)

            meta_lines = []
            if doc.authors:
                meta_lines.append(f"Authors: {', '.join(doc.authors)}")
            if doc.year:
                meta_lines.append(f"Year: {doc.year}")
            if doc.doi:
                meta_lines.append(f"DOI: {doc.doi}")
            if doc.journal:
                meta_lines.append(f"Journal: {doc.journal}")

            section_toc = ""
            if doc.sections:
                toc_lines = [f"\nSections ({len(doc.sections)}):"]
                for i, s in enumerate(doc.sections[:30]):
                    indent  = "  " * min(s.level - 1, 3)
                    preview = f" — {s.content[:80].strip()}..." if s.content and len(s.content) > 20 else ""
                    toc_lines.append(f"  {indent}{i + 1}. {s.heading}{preview}")
                section_toc = "\n".join(toc_lines)

            table_summary = ""
            if doc.tables:
                table_lines = [f"\nTables ({len(doc.tables)}):"]
                for tbl in doc.tables[:4]:
                    cap = tbl.caption[:80] if tbl.caption else "No caption"
                    table_lines.append(f"  {cap}")
                table_summary = "\n".join(table_lines)

            figure_summary = ""
            if doc.figures:
                figure_lines = [f"\nFigures ({len(doc.figures)}):"]
                for fig in doc.figures[:6]:
                    cap = fig.caption[:60] if fig.caption else "No caption"
                    figure_lines.append(f"  ID={fig.figure_id} | Page {fig.page_idx + 1} | {cap}")
                figure_summary = "\n".join(figure_lines)

            doc_context_text = (
                f"\nACTIVE DOCUMENT: {doc.filename}"
                f"\nTitle: {doc.title or 'Unknown'}"
                + ("\n" + "\n".join(meta_lines) if meta_lines else "")
                + f"\nSections: {len(doc.sections)} | Figures: {len(doc.figures)} | Tables: {len(doc.tables)}"
                + table_summary
                + figure_summary
                + section_toc
            )
        except Exception:
            doc_context_text = "\nDocument loaded but metadata unavailable."

    return {
        "role": "system",
        "content": (
            f"[LAB STATE] "
            f"Time: {time_str} ({office_note}) | "
            f"Evaluations collected: {total_evals} | "
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