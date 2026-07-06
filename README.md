# MAESTRO

**Materials Acceleration Engine for Synthesis, Testing and Research Orchestration**

MAESTRO is an open-source, domain-agnostic platform for agentic scientific discovery in self-driving laboratories. Scientists interact with an LLM-powered orchestrator via a chat interface to design, execute, and analyse experimental campaigns — with human approval at every instrument action.

## Features

- 🤖 **Agentic orchestration** — LLM plans and executes multi-step experimental workflows
- 🔬 **Instrument-agnostic** — connect any synthesis or characterisation instrument via adapters
- 📈 **Bayesian optimisation** — closed-loop GP-BO campaigns with live progress tracking
- 📄 **RAG pipeline** — upload papers (MinerU parsing) for question answering and campaign extraction
- 🔄 **Human-in-the-loop** — all instrument actions require explicit user approval
- 📊 **Live dashboard** — real-time workflow monitor, digital twin, Gantt schedule, execution log

## Quick Start

### Prerequisites

- Python ≥ 3.12
- Node.js ≥ 20
- A GitHub personal access token (for GitHub Models API)

### Backend

```bash
cd backend
cp .env.example .env          # add your GITHUB_TOKEN
pip install uv
uv sync
uv run uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
uv mineru
uv run mineru-models-download
npm run dev
```
