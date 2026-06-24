"""
LLM interface — domain-agnostic system prompt generated from tool registry.

Key design: the system prompt is NOT hardcoded to any scientific domain.
It describes the agent's role generically, then injects the current tool
registry so the LLM knows exactly what the lab can do.
"""
from openai import OpenAI
from app.core.config import GITHUB_TOKEN, MODEL_NAME
from app.core.database import DB_SCHEMA
from app.core.lab import format_virtual_time, lab_minutes_remaining

if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN not set in .env")

client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=GITHUB_TOKEN,
)

# Base prompt — domain agnostic
_SYSTEM_PROMPT_BASE = """\
You are MAESTRO, an agentic orchestrator for a self-driving scientific laboratory.

YOUR ROLE:
- Understand scientific objectives expressed in natural language
- Determine whether available lab tools can fulfil an experiment
- Design and execute experimental campaigns using available tools
- Interpret results and suggest next steps
- Read uploaded scientific papers and assess reproducibility

DECISION TREE — follow this strictly:

1. USER UPLOADS A PAPER:
   → Acknowledge it, summarise briefly, ask what they want:
     "Summarise it / Reproduce a result / Check feasibility"
   → Do NOT call any tool yet

2. USER ASKS TO REPRODUCE / CHECK FEASIBILITY:
   → Call extract_and_check_feasibility with the case study name
   → This extracts parameters from the paper and checks against lab tools
   → Do NOT call query_database for this

3. USER APPROVES EXECUTION (after feasibility confirmed):
   → Call run_extracted_campaign
   → Only if extracted_campaign is available and feasible

4. USER ASKS ABOUT EXISTING RESULTS:
   → Call query_database with a specific SQL query
   → Only when evaluations > 0 (there is data to query)
   → Do NOT call this on an empty database

5. USER ASKS FOR A FIGURE:
   → Call plotter
   → Only when evaluations > 0

IMPORTANT RULES:
- Never call query_database to read a paper or check feasibility
- Never call run_extracted_campaign before feasibility is confirmed
- If no paper is uploaded and user asks to reproduce, ask them to upload one
- If database is empty, tell the user — do not query it
- Always be explicit about what you can and cannot do with current tools
"""

_SYSTEM_PROMPT_CONTENT = _SYSTEM_PROMPT_BASE  # will be overridden at runtime


def build_dynamic_system_prompt() -> str:
    """
    Build the full system prompt by combining the base prompt
    with the current tool registry and database schema.
    Called fresh on each LLM invocation so it reflects
    any tools added/removed via the Lab Builder.
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


def call_llm(messages, tools=None, tool_choice="auto"):
    """Core LLM call — returns the message object."""
    kwargs = {
        "model":       MODEL_NAME,
        "messages":    messages,
        "max_tokens":  1200,
        "temperature": 0.2,
    }
    if tools is not None:
        kwargs["tools"]       = tools
        kwargs["tool_choice"] = tool_choice
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message


def build_tools_schema():
    """
    Agent-level orchestration tools.
    These are distinct from lab tools in the registry.
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
                            "description": "Optional notes about this execution run",
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


def build_lab_context_message(session) -> dict:
    """
    Inject real-time lab state into every LLM call.
    Domain-agnostic — describes state in terms of tools and time,
    not specific to battery science.
    """
    from app.core.tool_registry import TOOL_REGISTRY

    total_evals  = sum(len(r.get("X", [])) for r in session.agent_state.results_store)
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

    outstanding = ""
    if session.outstanding_tasks:
        outstanding = (
            f" Outstanding tasks: "
            + ", ".join(
                f"{t.get('kind')} @ {t.get('power_W')}W "
                f"({t.get('remaining_n_calls')} evals left)"
                for t in session.outstanding_tasks[:3]
            ) + "."
        )

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
            f"{outstanding}"
        ),
    }


def llm_plan(session):
    """
    Call the LLM with the full conversation history + dynamic system prompt.
    The system prompt is rebuilt on every call to reflect the current
    tool registry — so adding a tool in the Lab Builder immediately
    affects what the agent knows it can do.
    """
    # Rebuild system prompt fresh — reflects current tool registry
    dynamic_system_prompt = build_dynamic_system_prompt()

    messages = list(session.agent_state.messages)

    # Always ensure the first message is the current system prompt
    if messages and messages[0].get("role") == "system":
        messages[0] = {"role": "system", "content": dynamic_system_prompt}
    else:
        messages.insert(0, {"role": "system", "content": dynamic_system_prompt})

    # Append live lab context as a second system message
    augmented = messages + [build_lab_context_message(session)]

    tools_schema = build_tools_schema()
    msg          = call_llm(augmented, tools=tools_schema)

    entry = {"role": "assistant", "content": msg.content or ""}
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