-- PROPOSAL ONLY: not applied. Review schema names/types against the production
-- database before applying. Tables are namespaced and do not alter Track A tables.
CREATE TABLE IF NOT EXISTS signal_oracle_predictions (
  prediction_id TEXT PRIMARY KEY,
  contract_id TEXT NOT NULL,
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  issued_at TIMESTAMPTZ NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('UP','DOWN','NO TRADE')),
  score DOUBLE PRECISION,
  features_json JSONB NOT NULL,
  provenance_json JSONB NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  outcome TEXT,
  outcome_source TEXT,
  settled_at TIMESTAMPTZ,
  strategy_id TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  UNIQUE (contract_id, window_start, strategy_id)
);
CREATE INDEX IF NOT EXISTS signal_oracle_predictions_window_idx
  ON signal_oracle_predictions(window_end DESC, issued_at DESC);
CREATE TABLE IF NOT EXISTS signal_oracle_paper_trades (
  trade_id TEXT PRIMARY KEY,
  prediction_id TEXT NOT NULL UNIQUE REFERENCES signal_oracle_predictions(prediction_id),
  stake NUMERIC NOT NULL CHECK (stake > 0),
  entry_price NUMERIC,
  status TEXT NOT NULL,
  blocking_reason TEXT,
  pnl NUMERIC,
  opened_at TIMESTAMPTZ,
  settled_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS signal_oracle_settlement_events (
  event_id TEXT PRIMARY KEY,
  prediction_id TEXT NOT NULL REFERENCES signal_oracle_predictions(prediction_id),
  outcome TEXT NOT NULL,
  source TEXT NOT NULL,
  verified_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_oracle_applied_labels (
  prediction_id TEXT PRIMARY KEY REFERENCES signal_oracle_predictions(prediction_id),
  event_id TEXT NOT NULL UNIQUE REFERENCES signal_oracle_settlement_events(event_id),
  applied_at TIMESTAMPTZ NOT NULL
);
