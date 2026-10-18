# Signal Oracle Track B — integration boundary

Base revision: aff450bd54e8a00c92a285407995ed2f4c503759.
Branch: feat/signal-oracle-track-b-20261018.

This PR adds a disabled-by-default strategy scaffold, isolated fixture persistence,
API blueprint scaffold, configuration example, tests, and proposed namespaced
PostgreSQL schema. It does NOT yet integrate the strategy into main.py or register
the blueprint in dashboard.py. No worker cycle or browser rendering is claimed.

## Strategy identity
- strategy_id: signal_oracle
- strategy_version: oracle-logistic-head-v1
- feature schema: oracle-eight-features-v1
- default state: disabled / "Oracle strategy not configured"
- paper_only is mandatory; non-paper configuration is rejected.

The eight features summarize bounded existing signal probabilities/directions,
market midpoint, depth imbalance, short momentum, confidence, number of inputs,
and disagreement. This is a prototype readout, not evidence of accuracy. No
external oracle price feed or Momentum D alias is introduced.

## Metric definitions
Score one immutable first-issued directional prediction per
(contract_id, window_start, strategy_id). Repeated polling cannot replace it.
Only authoritative resolved UP/DOWN outcomes count; NO TRADE, unresolved, and
VOID do not enter the directional denominator. Accuracy is correct / eligible
resolved predictions * 100. Rolling accuracy uses latest configured N by window
close. Paper P&L is separate. PTB metadata is not a settlement source.

## Required before production integration
1. Map worker observations to Oracle inputs with timestamps and provenance; reject
   future/stale observations and fail closed on unverified US contract identity.
2. Implement a shared PostgreSQL adapter against CONNECTOME_DATABASE_URL for both
   worker writes and dashboard reads; do not use SQLite across Render services.
3. Add bounded, exception-isolated invocation in main.py without changing Track A.
4. Register the dashboard API and render the panel in dashboard.py's inline page.
5. Wire official US settlement events, idempotent paper entries, bankroll/exposure
   constraints, and restart/overlapping-worker protection transactionally.
6. Run repository dependencies, focused tests, worker cycle, API and browser tests.
7. Confirm deployment target and obtain separate merge/deployment approval.
