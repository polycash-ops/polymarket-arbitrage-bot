# Polymarket Arbitrage Research Bot

Paper-only research system for studying whether BTC moves on Binance US, Coinbase, and Kraken precede changes in Polymarket BTC Up/Down 15-minute contracts.

**Live trading is hard-blocked in code.** This repository simulates fills at observed quotes and records outcomes only after Polymarket publishes a definitive final result. Historical examples or detector scores are not proof of profitability.

## Architecture

```text
Market Monitor
  ├─ Binance US
  ├─ Coinbase
  ├─ Kraken
  └─ Polymarket BTC Up/Down 15m quotes
             │
             ▼
Opportunity Detector ──► paper signal candidate
             │
             ▼
     ┌───────────────────┐       ┌───────────────────┐
     │ Decision Connectome│       │ Research Connectome│
     │ up to 1M nodes     │       │ up to 1M nodes     │
     │ up to 1M edges     │       │ up to 1M edges     │
     │ learned confidence │       │ independent pattern│
     │ and signal gate    │       │ and checkpoint test│
     └───────────────────┘       └───────────────────┘
             │                            │
             └─────────────┬──────────────┘
                           ▼
                Trade Executor (PAPER ONLY)
                           │
                           ▼
              Verified contract final outcome
                           │
                           ▼
           Update both Connectomes' learned edges
```

The two Connectomes use separate SQLite databases and different feature representations. The configured one-million-node and one-million-edge values are **capacity ceilings**; nodes and edges are created as scan observations arrive, not pre-populated.

## What each scan teaches

For eligible active 15-minute BTC contracts, the system records one observation at each checkpoint it actually sees:

- `first_seen`
- `10m` remaining
- `5m` remaining
- `3m` remaining
- `1m` remaining

If the process first discovers a contract after a checkpoint has passed, that checkpoint is marked missed rather than fabricated. Each observation records the market ID, remaining time, Up probability/midpoint, available bid/ask spread, recent odds momentum, BTC move, exchange agreement, raw scan score, predicted directional-success probability, and feature signatures. Depth imbalance is left unknown because the current market feed does not supply full order-book depth.

When Gamma confirms the closed contract's final Up/Down outcome, each checkpoint prediction is labelled correct or incorrect. The Connectomes update the relevant nodes and edges only after this verified label. Repeated scans for the same market/checkpoint are idempotent.

## Confidence and checkpoint selection

- The detector's raw score is a heuristic from observed scan data; it is not represented as proven accuracy.
- Each Connectome predicts the historical chance that the chosen direction will be correct for similar features.
- Predicted probabilities are stored before the contract resolves and compared with the final label using Brier score, alongside directional win rate.
- The dashboard reports per-checkpoint results. A recommended checkpoint is reported only after that checkpoint has at least the configured minimum number of settled observations (default 20); the lower Brier score is preferred when available.
- The recommendation is evidence-based research, not a guarantee that future trades will be profitable.

## Dashboard

Dashboard: https://polymarket-arbitrage-dashboard.onrender.com/

The dashboard reports paper balance, settled P/L, paper equity curve, scan count, market feed prices, recent paper trades, each Connectome's active graph counts/capacities, settled accuracy, per-checkpoint performance, Brier scores, and the best supported checkpoint.

## Run locally

```bash
pip install -r requirements.txt
python main.py --paper-trading
```

The dashboard service is started with:

```bash
gunicorn dashboard:app --workers 1 --threads 4 --bind 0.0.0.0:$PORT
```

Configuration lives in `config.example.yaml`. Connectome storage defaults to `connectome_data/`; set `CONNECTOME_DATA_DIR` to a persistent mounted directory if the runtime provides one. Without persistent storage, learned state may be lost when the service is replaced.

## Safety and interpretation

- Live trading is hard-blocked.
- No synthetic exchange moves, market quotes, fills, or settlements should be introduced to improve results.
- Unresolved contracts do not contribute to settled accuracy or edge learning.
- Checkpoint samples from the same 15-minute contract are correlated observations, not independent contracts. Compare checkpoint performance on chronological, out-of-sample contract windows before treating a recommendation as reliable.
- There are no validated profitability claims or guaranteed win-rate targets in this README.
