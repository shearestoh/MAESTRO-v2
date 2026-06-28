"""
LLM interface — domain-agnostic system prompt generated from tool registry.

Key design principles:
1. System prompt is rebuilt on every call from the live tool registry.
2. All LLM calls trim conversation history to fit within token budget.
3. No domain-specific knowledge hardcoded — agent infers from tool descriptions.
4. Agent has a clear decision tree to prevent wrong tool calls.
5. Agent is figure-aware — can show extracted paper figures inline.
"""
from __future__ import annotations
import re

from openai import OpenAI

from app.core.config import GITHUB_TOKEN, MODEL_NAME
from app.core.database import DB_SCHEMA
from app.core.lab import format_virtual_time, lab_minutes_remaining
from app.core.models import EquipmentStatusModel

if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN not set in .env")

client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=GITHUB_TOKEN,
)

# ── Token budget ──────────────────────────────────────────────────────────────

_MAX_PROMPT_CHARS = 16_000   # ≈ 4,500 tokens — safe for gpt-4o-mini 8k limit


def _total_chars(messages: list) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages)


def trim_messages_to_budget(
    messages:    list,
    max_chars:   int = _MAX_PROMPT_CHARS,
    keep_last_n: int = 8,
) -> list:
    """
    Trim conversation history to fit within character budget.
    Always keeps: system messages + last N non-system messages.
    Drops oldest non-system messages until budget is met.
    """
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

    # Restore chronological order
    sys_part   = [m for m in kept if m.get("role") == "system"]
    other_part = [m for m in kept if m.get("role") != "system"]
    try:
        other_part.sort(key=lambda m: messages.index(m))
    except ValueError:
        pass  # message not in original list — keep as-is

    return sys_part + other_part


# ── Base system prompt ────────────────────────────────────────────────────────

_SYSTEM_PROMPT_BASE = """\
You are MAESTRO, an agentic orchestrator for a self-driving scientific laboratory.
You help scientists design, execute, and reproduce experimental campaigns.

YOUR ROLE:
- Understand scientific objectives expressed in natural language
- Determine whether available lab instruments can fulfil an experiment
- Design and execute experimental campaigns using available instruments
- Prepare and test samples independently or as part of workflows
- Interpret results and suggest next steps
- Read uploaded scientific papers and answer questions about them

DECISION TREE — follow this strictly:

1. USER UPLOADS A PAPER:
   → Acknowledge it, give a brief 2-3 sentence summary
   → Ask what they want: summarise / reproduce a result / check feasibility
   → Do NOT call any tool yet

2. USER ASKS A QUESTION ABOUT THE PAPER (authors, year, content, tables, figures):
   → Answer directly from the document context in LAB STATE
   → This includes: "who are the authors", "when was it published",
     "what is case study 2 about", "explain Table 1", "what does Figure 3 show"
   → Do NOT call any tool for these questions
   → Use the document metadata, table content, and section text from LAB STATE
   → If information is not in LAB STATE, say it is not available

3. USER ASKS TO SEE A FIGURE FROM THE PAPER:
   → Check the LAB STATE message for the figure list
   → Search for a figure whose caption contains the requested figure number
   → If found: render it IMMEDIATELY: ![caption](/api/media/{exact_figure_id})
   → Only say "could not be extracted" if the figure number does NOT appear
     in ANY caption in the LAB STATE figure list
   → Use ONLY figure IDs from the LAB STATE list — never invent IDs

4. USER ASKS TO CHECK FEASIBILITY (paper-based):
   → Call extract_and_check_feasibility ONCE
   → Only when user asks "is it feasible", "can the lab do this",
     "can you reproduce", "check feasibility"
   → Do NOT call again if LAB STATE shows "CAMPAIGN ALREADY EXTRACTED"
   → After the report appears, wait for the user to say "run it"

5. USER SAYS "RUN IT" OR APPROVES EXECUTION (paper-based campaign):
   → Trigger words: "run it", "run", "yes", "proceed",
     "execute", "go ahead", "start", "do it", "let's go"
   → Check LAB STATE — if it says "CAMPAIGN ALREADY EXTRACTED":
     call run_extracted_campaign IMMEDIATELY
   → Do NOT call extract_and_check_feasibility again
   → Do NOT ask for more confirmation — just call run_extracted_campaign

5b. USER SAYS "CONTINUE TOMORROW" OR WANTS TO RESUME:
   → Trigger words: "continue tomorrow", "resume", "next day",
     "continue where we left off", "pick up where we left off"
   → Check LAB STATE for outstanding_tasks
   → If outstanding tasks exist: call resume_outstanding_tasks
   → Do NOT just respond conversationally — always call the tool   

6. USER ASKS FOR A FREE-FORM EXPERIMENT (no paper, direct request):
   → Trigger: "optimise X under Y for N iterations",
     "find the best Z", "run BO on...", "search for optimal..."
   → Call plan_workflow with structured steps
   → The plan will be shown to the user for review and modification
   → Do NOT call run_extracted_campaign for free-form requests
   → Examples of free-form requests:
     "optimise porosity and AM under 100W for 30 iterations"
     "find the best specific energy under 150W"
     "make a sample at 92% AM and 50% porosity then test at 100W"

7. USER ASKS TO PREPARE A SAMPLE:
   → Trigger: "make a sample", "prepare an electrode",
     "synthesise a sample", "create a sample with..."
   → For a SINGLE sample preparation only: call prepare_sample directly
   → For prepare + test together: call plan_workflow with both steps
   → Always report the sample ID so the user can reference it later
   → The sample is stored in the lab inventory — it persists

8. USER ASKS TO TEST A SAMPLE:
   → Trigger: "test sample S-1-001", "measure S-1-001 at 100W",
     "what is the specific energy of S-1-001"
   → Call test_sample with the sample_id from LAB STATE and conditions
   → If no sample_id is mentioned, ask which sample to test
   → Check LAB STATE sample_registry for available samples

9. USER ASKS ABOUT SAMPLES IN THE LAB:
   → Trigger: "what samples do I have", "show inventory",
     "list samples", "what's in the lab"
   → Call list_samples

10. USER ASKS ABOUT EXISTING RESULTS:
    → Call query_database with a specific SQL query
    → Only when evaluations > 0 (there is data to query)
    → Do NOT call this on an empty database

11. USER ASKS FOR A SUMMARY FIGURE OF RESULTS:
    → Call plotter — only when evaluations > 0

PAPER FIGURES:
When a paper has been parsed, the LAB STATE message will list all available
figures with their exact IDs and captions.
To show a figure inline, use: ![caption](/api/media/{exact_figure_id})
IMPORTANT: Only use figure IDs listed in the LAB STATE message.
Never invent or guess figure IDs.

SAMPLE REGISTRY RULES:
- Every prepared sample gets a unique ID (e.g. S-1-001, S-1-002)
- Samples persist across the session — the user can test them later
- A sample can be tested multiple times under different conditions
- Always report the sample ID when a sample is prepared
- When the user references a sample by ID, look it up in LAB STATE sample_registry
- If a sample failed preparation, tell the user and offer to retry
- Use plan_workflow for multi-step workflows (prepare + test, or multiple tests)
- Use prepare_sample / test_sample directly for single-step actions

IMPORTANT RULES:
- Never call query_database to read a paper or check feasibility
- Never call extract_and_check_feasibility just because user asks what something is about
- Never call run_extracted_campaign before feasibility is confirmed
- Never call run_extracted_campaign for free-form requests — use plan_workflow
- If no paper is uploaded and user asks to reproduce, ask them to upload one
- If database is empty, say so — do not query it
- Always be explicit about what you can and cannot do with current instruments
- Speak as a scientific collaborator — precise, concise, honest about uncertainty
"""

# This is set at startup — exported for orchestrator.py to use in session init
_SYSTEM_PROMPT_CONTENT = _SYSTEM_PROMPT_BASE


def build_dynamic_system_prompt() -> str:
    """
    Build the full system prompt by combining the base with the
    current tool registry and database schema.
    Called fresh on every LLM invocation.
    """
    from app.core.tool_registry import TOOL_REGISTRY

    return (
        _SYSTEM_PROMPT_BASE
        + "\n\n"
        + "=" * 60 + "\n"
        + "AVAILABLE LAB TOOLS (current registry):\n"
        + "=" * 60 + "\n"
        + TOOL_REGISTRY.to_llm_context()
        + "\n"
        + "=" * 60 + "\n"
        + "EXPERIMENTAL DATABASE SCHEMA:\n"
        + "=" * 60 + "\n"
        + DB_SCHEMA
    )


# ── Core LLM call ─────────────────────────────────────────────────────────────

def call_llm(messages: list, tools=None, tool_choice: str = "auto"):
    """
    Core LLM call with automatic message trimming.
    Every call is guaranteed to fit within the model's token limit.
    """
    safe_messages = trim_messages_to_budget(messages)

    kwargs: dict = {
        "model":       MODEL_NAME,
        "messages":    safe_messages,
        "max_tokens":  1200,
        "temperature": 0.2,
    }
    if tools is not None:
        kwargs["tools"]       = tools
        kwargs["tool_choice"] = tool_choice

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message


# ── Tool schema ───────────────────────────────────────────────────────────────

def build_tools_schema() -> list:
    """
    Agent-level actions the LLM can call.

    Phase 3 additions:
    - plan_workflow: propose a structured workflow from free-form request
    - prepare_sample: run SamplerAgent on given params
    - test_sample: run TesterAgent on a stored sample
    - list_samples: show sample inventory
    """
    return [
        # ── Existing actions ──────────────────────────────────────────────────
        {
            "type": "function",
            "function": {
                "name": "extract_and_check_feasibility",
                "description": (
                    "Extract an experimental campaign from the uploaded paper "
                    "and check whether the current virtual lab can execute it. "
                    "Use when user says 'reproduce', 'is it feasible', 'can the lab do this'. "
                    "READ-ONLY — does not run experiments. Requires a paper to be uploaded."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "case_name": {
                            "type": "string",
                            "description": "The specific case study to extract, e.g. 'Case Study 2'",
                        },
                    },
                    "required": ["case_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_extracted_campaign",
                "description": (
                    "Execute the currently extracted experimental campaign from a paper. "
                    "Call when user says 'run it', 'execute', 'proceed' after a feasibility report. "
                    "Only call when extracted_campaign is available in LAB STATE."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "notes": {"type": "string", "description": "Optional notes"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "plotter",
                "description": (
                    "Generate a multi-panel summary figure from all collected "
                    "experimental results. Call after experiments have run."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_database",
                "description": (
                    "Run a read-only SQL SELECT query against the experimental "
                    "results database. Only call when experiments have been run."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SELECT statement"},
                        "description": {"type": "string", "description": "What this query answers"},
                    },
                    "required": ["sql", "description"],
                },
            },
        },

        # ── Phase 3: new agent actions ────────────────────────────────────────

        {
            "type": "function",
            "function": {
                "name": "plan_workflow",
                "description": (
                    "Propose a structured workflow plan for any free-form experimental request. "
                    "Use this when the user asks to run experiments that are NOT from an uploaded paper. "
                    "Examples: 'optimise porosity and AM under 100W for 30 iterations', "
                    "'make a sample at 92% AM and 50% porosity then test at 100W', "
                    "'find the best specific energy under 150W'. "
                    "The plan will be shown to the user for review and modification before execution. "
                    "Each step in the plan must have a 'kind' matching available step types. "
                    "Use {{variable_name}} syntax to reference outputs of previous steps."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "One-line human-readable summary of the proposed workflow",
                        },
                        "steps": {
                            "type": "array",
                            "description": "Ordered list of workflow steps",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": [
                                            "prepare_sample",
                                            "test_sample",
                                            "optimise_condition",
                                            "list_samples",
                                            "query_database",
                                            "plotter",
                                        ],
                                        "description": "Step type",
                                    },
                                    "label": {
                                        "type": "string",
                                        "description": "Human-readable step description",
                                    },
                                    "instrument": {
                                        "type": "string",
                                        "description": "Instrument to use e.g. 'SamplerAgent', 'TesterAgent'",
                                    },
                                    "params": {
                                        "type": "object",
                                        "description": "Parameters for prepare_sample step",
                                    },
                                    "produces": {
                                        "type": "string",
                                        "description": "Variable name for step output e.g. 'sample_id'",
                                    },
                                    "sample_ref": {
                                        "type": "string",
                                        "description": "Sample ID or {{variable}} reference for test_sample",
                                    },
                                    "conditions": {
                                        "type": "object",
                                        "description": "Fixed conditions for test_sample e.g. {'power_W': 100}",
                                    },
                                    "measures": {
                                        "type": "string",
                                        "description": "Output metric name e.g. 'specific_energy'",
                                    },
                                    "condition_label": {
                                        "type": "string",
                                        "description": "Condition name for optimise_condition e.g. 'power_W'",
                                    },
                                    "condition_value": {
                                        "type": "number",
                                        "description": "Fixed condition value for optimise_condition",
                                    },
                                    "condition_unit": {
                                        "type": "string",
                                        "description": "Unit for condition e.g. 'W', 'C', 'pH'",
                                    },
                                    "free_params": {
                                        "type": "array",
                                        "description": "Free parameters for BO optimise_condition step",
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
                                    "objective_metric": {
                                        "type": "string",
                                        "description": "Metric to optimise e.g. 'specific_energy'",
                                    },
                                    "n_calls": {
                                        "type": "integer",
                                        "description": "Number of BO iterations",
                                    },
                                    "n_initial_points": {
                                        "type": "integer",
                                        "description": "Random initial points before GP fitting",
                                    },
                                    "sql": {
                                        "type": "string",
                                        "description": "SQL query for query_database step",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Query description",
                                    },
                                    "editable_fields": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Fields the user can edit in the plan editor",
                                    },
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
                "name": "prepare_sample",
                "description": (
                    "Prepare a physical sample using the SamplerAgent. "
                    "Use when user asks to 'make a sample', 'prepare an electrode', "
                    "or similar. The sample is stored in the lab inventory with a unique ID. "
                    "The user can later ask to test it. "
                    "Prefer plan_workflow for multi-step requests."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "params": {
                            "type": "object",
                            "description": "Preparation parameters e.g. {'active_material': 92, 'porosity': 50}",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional notes about this sample",
                        },
                    },
                    "required": ["params"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "test_sample",
                "description": (
                    "Test a prepared sample using the TesterAgent. "
                    "Use when user asks to 'test sample S-1-001', 'measure the specific energy of S-1-001', "
                    "or similar. The sample must exist in the lab inventory. "
                    "Prefer plan_workflow for multi-step requests."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sample_id": {
                            "type": "string",
                            "description": "Sample ID from the lab inventory e.g. 'S-1-001'",
                        },
                        "conditions": {
                            "type": "object",
                            "description": "Test conditions e.g. {'power_W': 100}",
                        },
                        "measures": {
                            "type": "string",
                            "description": "Output metric to measure e.g. 'specific_energy'",
                        },
                    },
                    "required": ["sample_id", "conditions"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "list_samples",
                "description": (
                    "List all samples in the lab inventory. "
                    "Use when user asks 'what samples do I have', 'show my samples', "
                    "'what's in the lab', or similar."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "resume_outstanding_tasks",
                "description": (
                    "Resume any incomplete experimental runs from a previous lab day. "
                    "Call this when the user says 'continue tomorrow', 'resume', "
                    "'continue where we left off', 'next day', or similar. "
                    "This will advance the virtual lab clock to the next day and "
                    "re-queue all incomplete runs for execution. "
                    "Only call when LAB STATE shows outstanding tasks."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "notes": {
                            "type": "string",
                            "description": "Optional notes about resuming",
                        },
                    },
                    "required": [],
                },
            },
        },
    ]


# ── Lab context injection ─────────────────────────────────────────────────────

def build_lab_context_message(session) -> dict:
    """
    Inject real-time lab state into every LLM call.
    Includes: tool registry, campaign state, document metadata,
    table content, figure index, and first-page text for author/year queries.
    """
    from app.core.tool_registry import TOOL_REGISTRY
    from app.core.documents import get_document

    total_evals  = sum(
        len(r.get("X", [])) for r in session.agent_state.results_store
    )
    tool_summary = f"{len(TOOL_REGISTRY.list_all())} tools registered"

    campaign_text = "No campaign active."
    if session.extracted_campaign:
        c = session.extracted_campaign
        campaign_text = (
            f"CAMPAIGN ALREADY EXTRACTED — do not call "
            f"extract_and_check_feasibility again. "
            f"Campaign: '{c.title}'. "
            f"Objective: {c.objective_metric}. "
            f"Parameters: {[p['name'] for p in c.parameter_space]}. "
            f"Conditions: {c.operating_conditions}. "
            f"Status: {c.status}. "
            f"If user says 'run it' or similar, call run_extracted_campaign."
        )

    outstanding_text = ""
    if session.outstanding_tasks:
        outstanding_text = " Outstanding tasks: " + ", ".join(
            f"{t.get('kind')} @ {t.get('power_W')}W "
            f"({t.get('remaining_n_calls')} evals left)"
            for t in session.outstanding_tasks[:3]
        ) + "."

    # Build rich document context
    doc_context_text = ""
    if session.active_document_id:
        try:
            doc = get_document(session.active_document_id)

            # Table summaries — inject content so agent can answer questions
            table_summary = ""
            if doc.tables:
                table_lines = [f"\nAvailable tables ({len(doc.tables)}):"]
                for tbl in doc.tables[:5]:
                    cap = tbl.caption[:100] if tbl.caption else "No caption"
                    # Strip HTML tags to get plain text
                    html_text = re.sub(r'<[^>]+>', ' ', tbl.html)[:500].strip()
                    html_text = ' '.join(html_text.split())
                    table_lines.append(f"  Table: {cap}")
                    if html_text:
                        table_lines.append(f"  Content: {html_text}")
                table_summary = "\n".join(table_lines)

            # Figure index — real IDs only
            figure_lines: list[str] = []
            if doc.figures:
                figure_lines = [
                    f"\nAvailable figures ({len(doc.figures)} extracted):",
                    "NOTE: Vector graphics and multi-panel figures may be missing.",
                ]
                for fig in doc.figures:
                    cap = fig.caption[:80] if fig.caption else "No caption"
                    figure_lines.append(
                        f"  ID={fig.figure_id} | Page {fig.page_idx + 1} | {cap}"
                    )
                figure_lines.append(
                    "If a requested figure is not listed, "
                    "tell the user it could not be extracted."
                )
            else:
                figure_lines = ["\nNo figures were extracted from this paper."]

            # Use raw_text start for author/affiliation info
            raw_start = doc.raw_text[:1500] if doc.raw_text else ""
            if not raw_start and doc.pages:
                raw_start = doc.pages[0][:1500]

            # Also search the full raw text for publication date patterns
            # Date is often on page 1 footer or journal header, beyond first 1200 chars
            date_snippet = ""
            if doc.raw_text:
                # Search broader range — date often in footer/header beyond first 8000 chars
                search_text = doc.raw_text[:15000]
                date_patterns = [
                    # "December 4, 2024" or "December 2024"
                    r'(?:January|February|March|April|May|June|July|August|'
                    r'September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                    # "Published: September 23, 2024"
                    r'Published[:\s]+\S+\s+\d{1,2},?\s+\d{4}',
                    # "Received: April 2, 2024 ... Accepted: August 16, 2024"
                    r'Received[:\s].{0,80}(?:Accepted|Published)[:\s].{0,80}\d{4}',
                    # "Matter 7, 4260–4269, December 4, 2024"
                    r'(?:Matter|Nature|Science|Cell|JACS|ACS|RSC|Elsevier)'
                    r'.{0,50}\d{4}',
                    # "2024, Vol. 7"
                    r'\d{4}\s*[,\.]\s*(?:Vol|Volume|Issue|No\.)',
                    # DOI line often contains year
                    r'(?:doi|DOI|https://doi)[:\s/].{5,80}',
                    # Copyright year
                    r'©\s*\d{4}',
                    # "ª 2024" (Elsevier style)
                    r'ª\s*\d{4}',
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, search_text)
                    if match:
                        start = max(0, match.start() - 80)
                        end   = min(len(search_text), match.end() + 150)
                        date_snippet = search_text[start:end].strip()
                        date_snippet = ' '.join(date_snippet.split())
                        break

            first_page_text = ""
            if raw_start:
                first_page_text = (
                    f"\nDocument start (use for author/affiliation queries):\n"
                    f"{raw_start}"
                )
            if date_snippet:
                first_page_text += (
                    f"\nPublication metadata found in document:\n{date_snippet}"
                )

            # Section table of contents — so agent can answer
            # "what sections are there" and "what is section 2 about"
            section_toc = ""
            if doc.sections:
                toc_lines = [f"\nSection headings ({len(doc.sections)} total):"]
                for i, s in enumerate(doc.sections[:40]):
                    indent = "  " * min(s.level - 1, 3)
                    # Include first 120 chars of content for context
                    # so agent can answer "what is section N about"
                    preview = ""
                    if s.content and len(s.content) > 20:
                        preview = f" — {s.content[:120].strip()}..."
                    toc_lines.append(
                        f"  {indent}{i + 1}. {s.heading}{preview}"
                    )
                section_toc = "\n".join(toc_lines)

            doc_context_text = (
                f"\nDocument loaded: {doc.filename}"
                f"\nTitle: {doc.title or 'Unknown'}"
                f"\nSections: {len(doc.sections)} | "
                f"Figures: {len(doc.figures)} | "
                f"Tables: {len(doc.tables)}"
                f"{table_summary}"
                + "\n".join(figure_lines)
                + first_page_text
                + section_toc
            )


        except Exception:
            doc_context_text = "\nDocument loaded but metadata unavailable."

    return {
        "role": "system",
        "content": (
            f"[LAB STATE] "
            f"Day {session.virtual_day_index} | "
            f"Time: {format_virtual_time(session.virtual_clock_minutes)} | "
            f"Remaining today: {lab_minutes_remaining(session)} min | "
            f"Evaluations collected: {total_evals} | "
            f"Lab: {tool_summary} | "
            f"{campaign_text}"
            f"{outstanding_text}"
            f"{doc_context_text}"
        ),
    }

# ── Main LLM planning call ────────────────────────────────────────────────────
def _repair_tool_call_chain(messages: list) -> list:
    """
    Ensure every assistant message with tool_calls is followed by
    matching tool response messages.

    Called before every LLM invocation as a safety net.
    Repairs in-place and returns the repaired list.
    """
    import json as _json

    # Collect responded IDs
    responded_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id:
                responded_ids.add(tc_id)

    # Find orphaned tool_call_ids
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
                        "message": (
                            f"Tool '{tc_name}' executed successfully."
                        ),
                    }),
                }))
                responded_ids.add(tc_id)

    # Insert in reverse order to preserve indices
    for insert_idx, tool_msg in reversed(injections):
        messages.insert(insert_idx, tool_msg)

    return messages

def llm_plan(session) -> dict:
    """
    Call the LLM with the full conversation history + dynamic system prompt.
    Lights up the knowledge node when the query is document-related.
    """
    dynamic_system = build_dynamic_system_prompt()
    messages       = list(session.agent_state.messages)

    if messages and messages[0].get("role") == "system":
        messages[0] = {"role": "system", "content": dynamic_system}
    else:
        messages.insert(0, {"role": "system", "content": dynamic_system})

    augmented    = messages + [build_lab_context_message(session)]
    augmented = _repair_tool_call_chain(augmented)
    tools_schema = build_tools_schema()

    # Detect document-related queries to light up the knowledge node
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