# Architecture

## Project tree
```text
adk-refund-agent/
├── .github/workflows/ci.yml
├── docs/{PRD.md, ARCHITECTURE.md}
├── refund_agent/
│   ├── __init__.py            exports root_agent
│   ├── agent.py               LlmAgent + generation config + callback wiring
│   ├── config.py              caps, token limits, regex, state defaults
│   ├── db.py                  SQLite (auto-init, seed, parameterized queries)
│   ├── prompts.py             static system instruction
│   ├── schemas/{inputs.py, outputs.py}
│   ├── tools/{read_tools.py, compute_tools.py, write_tools.py}
│   └── guardrails/{agent,model,tool}_callbacks.py
└── tests/unit/test_refund_agent.py
```

## Callback lifecycle
```text
user message
   │
   ▼
before_agent_callback ── init DB + session state defaults
   │
   ▼
before_model_callback ── domain lock (exact refusal string, skips the LLM call)
   │
   ▼
 Gemini ─► after_model_callback ── anti-loop (3rd identical reply is replaced)
   │ function call
   ▼
before_tool_callback ── order-ID regex, sequence gates, identifier/amount overwrite,
   │                    $150 cap + fraud routing, confirmation-in-later-turn gate
   ▼ (or BLOCKED dict returned instead of running the tool)
 Python tool ── parameterized SQLite
   │
   ▼
after_tool_callback ── prune timestamps/metadata from LLM context
   │
   ▼
 Gemini ─► plain-English reply
   │
   ▼
after_agent_callback ── structured audit log (RefundDecisionSummary)
```

## Workflow state machine
`ORDER_LOADED -> FEEDBACK_CAPTURED -> LOGISTICS_VERIFIED + FRAUD_CHECKED -> CALCULATED ->
(next user turn = confirmation) -> REFUNDED | ESCALATED_TO_FINANCE`.
State lives in ADK session state (`config.WORKFLOW_STATE_DEFAULTS`) and resets when the customer
switches to a different order.

## Design decisions
- **Integer cents** everywhere; floats only at the display edge.
- **Confirmation gate is deterministic:** payout and ticket tools are blocked in the same
  invocation as the calculation, so the LLM cannot self-confirm.
- **Thinking disabled** via `BuiltInPlanner(thinking_budget=0)`; thinking tokens would consume the 300-token cap.
- **Static instruction** (no braces, timestamps or IDs) for prompt-cache hits and to avoid ADK state templating.
- **Domain lock is layered:** deterministic regex for obvious cases, static prompt for the semantic long tail.

## Threat model
| Threat | Mitigation |
|--------|-----------|
| SQL injection via Order ID | `^ORD-[0-9]{5}$` fullmatch in callback, tool and DB layer; `?` placeholders only |
| LLM invents order data or math | Tool-only architecture; math in `compute_refund_cents`; prompt forbids guessing |
| LLM tampers with payout amount | `before_tool_callback` overwrites `amount` from `verified_refund_amount`; tool re-verifies |
| Customer/LLM switches reason to waive fees | `reason_category` overwritten from captured feedback |
| Skipping workflow stages | State gates for feedback, logistics, fraud and calculation |
| Self-confirmation by the LLM | Payout/ticket blocked within the calculating invocation |
| Refund over cap or fraud-flagged | Payout blocked; only `create_hitl_ticket` allowed, with a deterministic reason code |
| Duplicate payout | `IDEMP-<ORDER>-<CENTS>` primary key + `ALREADY_PROCESSED` guard |
| Cross-order confusion | `ORDER_MISMATCH` block; state reset on order switch |
| Prompt injection / off-topic abuse | Domain-lock callback and prompt; injection phrases rejected |
| Response loops burning tokens | Anti-loop callback; 300-token cap |
| Internal data leakage into context | `after_tool_callback` prunes metadata; prompt forbids revealing fraud results |

## Known limitations
The regex domain lock is intentionally conservative; a classifier model could be added for
higher recall. The payout tool is a local stand-in for a payment processor.
