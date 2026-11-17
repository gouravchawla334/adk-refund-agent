# adk-refund-agent

[Read the full architectural deep-dive on Dev.to](https://dev.to/gouravchawla28/building-production-grade-ai-agents-how-i-designed-an-autonomous-refund-system-with-google-adk-5g58)

A production-style **E-Commerce Refund Orchestrator** built with the Google Agent Development Kit (ADK).
The LLM (`gemini-2.5-flash`) is only a semantic router and plain-English interface. Every lookup,
calculation and payout runs through deterministic Python tools guarded by ADK lifecycle callbacks.

## Architecture
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
