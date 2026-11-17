# Product Requirements Document: RefundOrchestratorAgent

## 1. Summary
An autonomous, conversational agent that processes e-commerce return refunds end to end.
The LLM (`gemini-2.5-flash`) is a semantic router and plain-English interface only. All
lookups, calculations, writes and payouts run through deterministic Python tools guarded
by ADK lifecycle callbacks.

## 2. Goals
- Resolve eligible refunds up to **$150.00** with no human involvement.
- Route refunds **above $150.00**, or **fraud-flagged** cases, to Finance via a HITL ticket.
- Zero hallucinated order data, policy windows or refund math.
- Keep per-turn cost low: static prompt (cache-friendly), `max_output_tokens=300`, `temperature=0.0`.

## 3. Non-goals
Exchanges, partial-quantity returns, multi-item order splitting, real payment-processor integration
(the payout tool writes to the local audit table; swap it for a PSP client in production),
and authentication of the customer (assumed handled upstream).

## 4. Personas
- **Customer:** wants a fast, clear answer in plain English.
- **Finance reviewer:** receives only the cases that exceed the cap or are flagged.
- **Platform engineer:** needs auditable, testable guardrails.

## 5. Functional requirements
| ID | Requirement |
|----|-------------|
| F1 | Ask for an Order ID (`ORD-XXXXX`) and look it up. Invalid or unknown IDs get a plain-English "not available in our system" reply and the flow stops. |
| F2 | Summarize items and total paid; ask for a return reason (`DEFECTIVE`, `WRONG_SIZE`, `NOT_AS_PICTURED`, `NO_LONGER_NEEDED`, `OTHER`); persist it. (HITL gate 1) |
| F3 | Check return logistics, refund policy and fraud score. If the package is not `DELIVERED_AT_WAREHOUSE`, tell the customer it has not been scanned yet and stop. |
| F4 | Compute the net refund deterministically; present the exact breakdown and require explicit confirmation in a later turn. (HITL gate 2) |
| F5 | After confirmation, pay out if the net refund is <= $150.00 and not fraud-flagged; otherwise open a Finance ticket. |
| F6 | Reject off-topic prompts with the exact sentence: "I am a refund agent only and can only help you process returns and refunds." |
| F7 | Detect and break assistant response loops (same message repeated twice more). |

## 6. Business rules
- Restocking fee: category percentage of the **item subtotal**; **0%** for `DEFECTIVE` and `NOT_AS_PICTURED`.
- Shipping is refunded only for those merchant-fault reasons.
- Auto-approve cap: net refund <= $150.00. Fraud score >= 0.80 flags a case.
- Amounts are computed in integer cents with half-up rounding.
- Payout idempotency key: `IDEMP-<ORDER_ID>-<CENTS>`.

Seed scenarios: `ORD-98765` ($100.00, auto-refund), `ORD-55555` ($240.00, Finance escalation),
`ORD-11111` ($80.00, in transit).

## 7. Service levels (targets)
| Metric | Target |
|--------|--------|
| Time to first response | p95 <= 3 s |
| Auto-approved refund, end to end (conversation turns) | <= 6 turns |
| Finance ticket review | <= 1 business day (human process, out of agent scope) |
| Hallucinated amounts or IDs | 0 (enforced by tool-only architecture and tests) |
| Duplicate payouts | 0 (idempotency key + `ALREADY_PROCESSED` guard) |
| Output tokens per reply | <= 300 |

## 8. Success metrics
Auto-resolution rate, escalation rate, loop-breaker trigger rate, off-topic rejection rate, and
guardrail block counts by `error_code` (from the audit log).

## 9. Risks
Prompt injection, parameter tampering, duplicate payouts and SQL injection. See the threat model in
`ARCHITECTURE.md`.
