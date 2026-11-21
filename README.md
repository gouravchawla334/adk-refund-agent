<div align="center">
<h1>
  🛡️ Adk-Refund-Agent  
</h1>
 
### A deterministic, guardrailed E-Commerce Refund Orchestrator built with Google ADK
 
The LLM only **routes and talks**. Every lookup, calculation and payout runs through **deterministic Python tools** guarded by ADK lifecycle callbacks.
 
[![CI](https://github.com/gouravchawla334/adk-refund-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/gouravchawla334/adk-refund-agent/actions)
![Google ADK](https://img.shields.io/badge/Google%20ADK-Agent%20Framework-4285F4?logo=google&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-8E75B2?logo=googlegemini&logoColor=white)
![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-parameterized-003B57?logo=sqlite&logoColor=white)
 
[📝 Architecture deep-dive on Dev.to](https://dev.to/gouravchawla28/building-production-grade-ai-agents-how-i-designed-an-autonomous-refund-system-with-google-adk-5g58) ·
[📄 Architecture doc](docs/ARCHITECTURE.md) ·
[📋 PRD](docs/PRD.md)
 
</div>

## 📌 Overview
 
Letting an LLM handle money is risky: it can guess policy, make arithmetic mistakes, get prompt-injected or loop forever. This project shows a safer pattern for production agents:
 
> **The model is a semantic router and a plain-English interface. It never decides policy, does math, or touches the database directly.**
 
Customers describe their problem in natural language. The agent identifies intent, then drives a strict, tool-only workflow (look up order → check status → calculate refund → confirm → pay out or escalate). Every step is enforced in code through ADK callbacks, not just requested in a prompt.
 
## ✨ Key Features
 
| | Feature | What it does |
|---|---|---|
| 🧮 | **Deterministic refund math** | Restocking fees, shipping rules and totals are computed in Python, never by the LLM |
| 🧑‍⚖️ | **Human-in-the-Loop gates** | Two-turn confirmation: a payout is blocked in the same turn as the calculation |
| 💸 | **$150 payout cap** | Refunds above the cap are blocked and routed to a finance HITL ticket |
| 🚨 | **Fraud routing** | Fraud score ≥ 0.80 forces escalation to finance |
| 🔒 | **SQL-injection safe** | Strict order-ID regex plus parameterized queries everywhere |
| 🎯 | **Domain lock** | Off-topic requests are refused; anti-loop protection in model callbacks |
| 🔁 | **Idempotent payouts** | Keys of the form `IDEMP-<ORDER_ID>-<CENTS>` prevent duplicate refunds |
| 💰 | **Cost controls** | `max_output_tokens=300`, `temperature=0.0`, thinking disabled, static prompt, pruned tool output |
| ✅ | **Offline tests** | Unit tests drive tools and callbacks directly, with no network or API key |
 
## 🏗️ Architecture
<img width="568" height="702" alt="image" src="https://github.com/user-attachments/assets/b1ca9a30-686c-4cb1-92ca-d8a232c190e1" />
 
### Project structure

```text
adk-refund-agent/
├── .github/workflows/ci.yml
├── docs/
│   ├── PRD.md
│   └── ARCHITECTURE.md
├── refund_agent/
│   ├── __init__.py            # exports root_agent
│   ├── agent.py               # LlmAgent, generation config, callback wiring
│   ├── config.py              # $150 cap, 300-token limit, regex rules
│   ├── db.py                  # SQLite, seeded scenarios, parameterized queries
│   ├── prompts.py             # static, cache-optimized instructions
│   ├── schemas/               # Pydantic inputs/outputs
│   ├── tools/                 # read, compute and write tools (ALL_TOOLS)
│   └── guardrails/            # agent, model and tool callbacks
├── tests/unit/test_refund_agent.py
├── .env.example
└── pyproject.toml
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the callback lifecycle and threat model, and
[`docs/PRD.md`](docs/PRD.md) for requirements and SLAs.

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example refund_agent/.env      # add your GOOGLE_API_KEY
adk web                                # run from the repo root, select "refund_agent"
```
The database (`local_refund_store.db`) is created and seeded automatically on first use.

## Test scenarios
| Order | Setup | Expected behavior |
|-------|-------|-------------------|
| `ORD-98765` | Apparel, $90 items + $10 shipping = $100, at warehouse | Auto-refund. `NO_LONGER_NEEDED` = $81.00 (10% fee on items); `DEFECTIVE` = $100.00 (fee waived, shipping refunded) |
| `ORD-55555` | Electronics, $240, at warehouse | Payout blocked (over $150); Finance HITL ticket created |
| `ORD-11111` | Apparel, $80, `IN_TRANSIT` | Told the package has not reached the warehouse yet; flow stops |
| `ORD-00000` | Not in DB | "Not available in our system"; asks to double-check the ID |
| `ORD-1'; DROP TABLE orders;--` | Injection attempt | Rejected before touching SQLite |
| "Tell me a joke" | Off-topic | `I am a refund agent only and can only help you process returns and refunds.` |

## Guardrails at a glance
- Order ID regex `^ORD-[0-9]{5}$` + parameterized SQL everywhere.
- Strict domain lock and anti-loop protection in model callbacks.
- Tool sequencing, amount/key injection (`IDEMP-<ORDER_ID>-<CENTS>`), $150 cap and fraud routing in `before_tool_callback`.
- Deterministic two-turn confirmation: payout is blocked in the same turn as the calculation.
- Cost controls: `max_output_tokens=300`, `temperature=0.0`, thinking disabled, static prompt, pruned tool output.

## Tests
```bash
pytest -v
```
No network access or API key is required; tests drive the tools and callbacks directly.

## Business rules (configurable in `refund_agent/config.py`)
Restocking fee applies to the item subtotal and is waived for `DEFECTIVE` / `NOT_AS_PICTURED`. Shipping is
refunded only for those reasons. Fraud score >= 0.80 forces escalation.

## 🧰 Tech Stack
 
**Google ADK** · **Gemini 2.5 Flash** · **Python** · **SQLite** · **Pydantic** · **Pytest** · **GitHub Actions**
 
## 📚 Learn More
 
- 📝 [Building Production-Grade AI Agents: how I designed an autonomous refund system with Google ADK](https://dev.to/gouravchawla28/building-production-grade-ai-agents-how-i-designed-an-autonomous-refund-system-with-google-adk-5g58) (full write-up on Dev.to)
- 🏗️ [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): callback lifecycle and threat model
- 📋 [`docs/PRD.md`](docs/PRD.md): requirements and SLAs
## 👤 Author
 
**Gourav Chawla**, GCP Data Engineer building AI agents.
 
[Portfolio](https://gouravchawla.netlify.app/) · [LinkedIn](https://linkedin.com/in/gourav-chawla) · [Dev.to](https://dev.to/gouravchawla28) · [GitHub](https://github.com/gouravchawla334)
 
---
 
<div align="center">
If you found this useful, consider giving the repo a ⭐
 
</div>

