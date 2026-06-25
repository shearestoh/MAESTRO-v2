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
- Determine whether available lab tools can fulfil an experiment
- Design and execute experimental campaigns using available tools
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
   → If information is not in LAB STATE, say it is not available in the extracted content

3. USER ASKS TO SEE A FIGURE FROM THE PAPER:
   → Check the LAB STATE message for the figure list
   → Search for a figure whose caption contains the requested figure number
     e.g. "Figure 5" → look for caption containing "Figure 5" or "figure 5"
   → If found: render it immediately as: ![caption](/api/media/{figure_id})
   → If NOT found: say clearly "Figure X could not be extracted from this paper
     (likely a vector graphic or multi-panel figure that MinerU could not capture).
     The available figures are: [list captions briefly]"
   → Do NOT silently show a different figure as a substitute without telling the user
   → Do NOT list raw figure IDs — only show captions and render images
   → Use ONLY figure IDs from the LAB STATE list — never invent IDs
   → If no figures are listed in LAB STATE, say no figures are available

4. USER EXPLICITLY ASKS TO REPRODUCE OR CHECK FEASIBILITY:
   → Only call extract_and_check_feasibility when the user uses explicit language:
     "reproduce", "can you run this", "is it feasible", "execute this experiment",
     "check if the lab can do this"
   → Do NOT call this tool just because the user asks what a case study is about
   → Requires a paper to be uploaded first

5. USER APPROVES EXECUTION (after feasibility confirmed):
   → Call run_extracted_campaign
   → Only if extracted_campaign is available and feasible

6. USER ASKS ABOUT EXISTING RESULTS:
   → Call query_database with a specific SQL query
   → Only when evaluations > 0 (there is data to query)
   → Do NOT call this on an empty database

7. USER ASKS FOR A SUMMARY FIGURE OF RESULTS:
   → Call plotter — only when evaluations > 0

PAPER FIGURES:
When a paper has been parsed, the LAB STATE message will list all available
figures with their exact IDs and captions.
To show a figure inline, use: ![caption](/api/media/{exact_figure_id})
IMPORTANT: Only use figure IDs listed in the LAB STATE message.
Never invent or guess figure IDs.
When a user asks to see a figure, find the best matching ID from the list
and render it. If no figures are available, say so clearly.

IMPORTANT RULES:
- Never call query_database to read a paper or check feasibility
- Never call extract_and_check_feasibility just because user asks what something is about
- Never call run_extracted_campaign before feasibility is confirmed
- If no paper is uploaded and user asks to reproduce, ask them to upload one
- If database is empty, say so — do not query it
- Always be explicit about what you can and cannot do with current tools
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
    Agent-level orchestration tools.
    Distinct from lab tools in the registry — these are workflow actions.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "extract_and_check_feasibility",
                "description": (
                    "Extract an experimental campaign from the uploaded paper "
                    "and check whether the current virtual lab tools can execute it. "
                    "Use this when the user asks to reproduce results, check feasibility, "
                    "or asks what a paper's experiment requires. "
                    "Requires a paper to be uploaded first."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "case_name": {
                            "type": "string",
                            "description": (
                                "The specific case study or section to extract, "
                                "e.g. 'Case Study 2', 'Figure 3 experiment', "
                                "'Section 3.2 results'"
                            ),
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
                    "Execute the currently extracted experimental campaign "
                    "using the available lab tools. "
                    "Only call this after extract_and_check_feasibility has confirmed "
                    "the campaign is feasible and the user has approved execution."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "notes": {
                            "type": "string",
                            "description": "Optional notes about this run",
                        }
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
                    "experimental results. Call this after experiments have run."
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
                    "results database. Only call this when experiments have already "
                    "been run and the user asks a specific question about the data. "
                    "Do NOT call this to check feasibility or read a paper."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "SELECT statement to execute",
                        },
                        "description": {
                            "type": "string",
                            "description": "Human-readable description of what this query answers",
                        },
                    },
                    "required": ["sql", "description"],
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
            f"Active campaign: '{c.title}'. "
            f"Objective: {c.objective_metric}. "
            f"Parameters: {[p['name'] for p in c.parameter_space]}. "
            f"Conditions: {c.operating_conditions}. "
            f"Status: {c.status}."
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
                import re as _re
                # Search for year patterns: "2024", "December 4, 2024", etc.
                date_patterns = [
                    r'(?:January|February|March|April|May|June|July|August|'
                    r'September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                    r'Published[:\s]+\w+\s+\d{1,2},?\s+\d{4}',
                    r'Received[:\s].{0,60}(?:Accepted|Published)[:\s].{0,60}\d{4}',
                    r'\d{4}\s*[,\.]\s*(?:Vol|Volume|Issue)',
                    r'(?:doi|DOI)[:\s].{5,60}',
                ]
                for pattern in date_patterns:
                    match = _re.search(pattern, doc.raw_text[:8000])
                    if match:
                        # Get surrounding context
                        start = max(0, match.start() - 50)
                        end   = min(len(doc.raw_text), match.end() + 100)
                        date_snippet = doc.raw_text[start:end].strip()
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
                for i, s in enumerate(doc.sections[:40]):  # cap at 40
                    indent = "  " * min(s.level - 1, 3)
                    toc_lines.append(f"  {indent}{i + 1}. {s.heading}")
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