-- PROPOSAL ONLY: not applied. Review schema names/types against the production
-- database before applying. Tables are namespaced and do not alter Track A tables.
CREATE TABLE IF NOT EXISTS signal_oracle_predictions (
  prediction_id TEXT PRIMARY KEY,
  contract_id TEXT,
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
  benchmark_source TEXT,
  contract_verified BOOLEAN NOT NULL DEFAULT FALSE,
  execution_status TEXT NOT NULL DEFAULT 'unavailable_no_verified_contract_quotes',
  pnl NUMERIC,
  strategy_id TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  UNIQUE (contract_id, window_start, strategy_id)
);
CREATE INDEX IF NOT EXISTS signal_oracle_predictions_window_idx
  ON signal_oracle_predictions(window_end DESC, issued_at DESC);

-- Separate UTC Binance candle window and worker heartbeat. This benchmark is
-- explicitly not official Polymarket PTB and is not a contract settlement source.
CREATE TABLE IF NOT EXISTS signal_oracle_windows (
  window_id TEXT PRIMARY KEY,
  window_start TIMESTAMPTZ NOT NULL UNIQUE,
  window_end TIMESTAMPTZ NOT NULL,
  contract_id TEXT,
  contract_verified BOOLEAN NOT NULL DEFAULT FALSE,
  benchmark_name TEXT NOT NULL,
  benchmark_qualifier TEXT NOT NULL,
  benchmark_symbol TEXT NOT NULL CHECK (benchmark_symbol='BTCUSDT'),
  benchmark_interval TEXT NOT NULL CHECK (benchmark_interval='15m'),
  benchmark_quote_currency TEXT NOT NULL CHECK (benchmark_quote_currency='USDT'),
  benchmark_price DOUBLE PRECISION,
  benchmark_source_timestamp TIMESTAMPTZ,
  benchmark_acquired_at TIMESTAMPTZ,
  benchmark_status TEXT NOT NULL,
  current_price DOUBLE PRECISION,
  current_price_timestamp TIMESTAMPTZ,
  current_signal TEXT NOT NULL DEFAULT 'NO TRADE',
  current_signal_reason TEXT NOT NULL DEFAULT 'Oracle strategy not configured',
  strategy_version TEXT NOT NULL DEFAULT 'oracle-logistic-head-v1',
  candle_close_price DOUBLE PRECISION,
  candle_close_source_timestamp TIMESTAMPTZ,
  candle_finalized BOOLEAN NOT NULL DEFAULT FALSE,
  outcome TEXT CHECK (outcome IS NULL OR outcome IN ('UP','DOWN','TIE')),
  heartbeat_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS signal_oracle_windows_recent_idx
  ON signal_oracle_windows(window_start DESC);

CREATE TABLE IF NOT EXISTS signal_oracle_worker_state (
  id INTEGER PRIMARY KEY CHECK (id=1),
  heartbeat_at TIMESTAMPTZ NOT NULL,
  state TEXT NOT NULL,
  message TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
