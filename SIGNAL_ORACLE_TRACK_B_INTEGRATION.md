# Signal Oracle Track B — integration status

Base revision: aff450bd54e8a00c92a285407995ed2f4c503759.
Branch: feat/signal-oracle-track-b-20261018.
PR: #7. This branch is not merged or deployed.

## Current implementation

- `main.py` runs an isolated `_signal_oracle_loop` alongside Track A. Track B exceptions are caught and logged without cancelling Track A.
- `bot/signal_oracle_binance.py` requests Binance Spot `BTCUSDT` `15m` candles for the exact UTC open timestamp. It validates the exact open and close timestamps and finite positive prices. It does not use ticker data as a benchmark fallback. Current ticker is a separate informational quote.
- Benchmark label: **Oracle paper PTB — Binance**. Qualifier: **Binance window-open benchmark; not official Polymarket PTB.** Prices are USDT per BTC; source candle timestamp and acquisition time are separate fields.
- Final outcome is derived only from the same candle after its close timestamp: UP if close > open, DOWN if close < open, TIE if equal. An unfinalized candle remains pending.
- `bot/signal_oracle_postgres.py` implements shared durable persistence through `CONNECTOME_DATABASE_URL`, immutable first benchmark values, deterministic per-window prediction IDs, pending-window recovery, and metrics. It does not apply or create database schema.
- `dashboard.py` registers `/api/track-b/signal-oracle` and renders a Track B panel with signal/reason, benchmark and current quote timestamps, window status, rolling/lifetime accuracy, pending/tie/excluded counts, worker heartbeat, and explicit N/A contract execution/P&L.
- `polymarket_us_ptb.py` owns the canonical `polymarket_us_btc_15m_slug()` generator for the official US `cpc-btc-updown-15m-YYYY-MM-DD-HHMMz` slug. Oracle Track B's official PTB acquisition and the main Track A research market monitor both use this shared helper; the research monitor probes the US slug first, retaining legacy Gamma slug probes only as compatibility fallbacks for its existing quote feed. Official PTB provenance checks remain fail-closed, with bounded retries only for transient null `priceToBeat`. Binance is never a fallback for official PTB.
- Live order submission remains hard-blocked. No token price, fill, or contract P&L is inferred from Binance direction results.

## Strategy configuration blocker

The existing prototype defines an eight-feature logistic readout but the repository contains no authoritative trained readout weights or canonical weight artifact. The worker accepts a nine-value finite `SIGNAL_ORACLE_WEIGHTS` vector (bias plus eight coefficients) only if explicitly supplied. It does not invent weights. When absent, the current dashboard state is NO TRADE with the reason that the readout weights are not configured; any persisted NO TRADE row is excluded from directional accuracy. The first prediction for a window is immutable.

The strategy inputs are sourced from the existing 15-minute Connectome forecast and current quote snapshot, and stale/mismatched windows are rejected. This wiring does not establish strategy accuracy until canonical weights are supplied and real forward predictions resolve.

## Database and release boundary

`PROPOSED_SIGNAL_ORACLE_MIGRATION.sql` defines namespaced PostgreSQL tables for predictions, Binance windows, worker heartbeat, and future paper-trade metadata. It is a proposal only and has **not** been applied. Until the migration is separately approved and applied, the worker/API reports database/schema errors or INITIALIZING; no production database mutation is performed by this branch.

## Verification status

- GitHub Actions PTB safety test run #44 completed successfully on commit `5672e99c6134f996b95c99a6f0cb09bb42d2db2c`.
- Additional Binance tests cover exact window alignment, timestamp units, late acquisition, unfinalized data, UP/DOWN/TIE/NO TRADE scoring, invalid prices, and bounded retries. They have not yet been independently confirmed by a completed CI run in this report.
- End-to-end worker-to-PostgreSQL-to-API-to-browser verification has not been run against the real database. No claim of live accuracy or resolved production predictions is made.
- No schema migration, production configuration change, merge, or deployment has been performed.

## Required before declaring Track B fully operational

1. Supply the canonical Oracle readout weights or point to the authoritative trained artifact; do not substitute invented values.
2. Separately approve and apply the proposed additive schema migration to the intended shared database.
3. Run the complete repository test suite, including the new Binance tests, and verify the worker/store/API/browser flow in an authorized environment.
4. Obtain separate merge/deployment approval. Render `main` may auto-deploy. Live trading remains prohibited.


### Shared official 15-minute market source

The Track A 15-minute quote path uses the same validated official Polymarket US market-by-slug payload and PTB adapter as Oracle Track B. Gamma/international 15-minute rows are rejected rather than used as fallback; Gamma is retained for the separate hourly feed. If the official US response lacks quote/outcome fields, no 15-minute quote is emitted. This is fail-closed; do not claim operational 15-minute quotes until the official US quote schema is confirmed.
