-- Oracle Track B: paper-only schema over FlyWire Biological Reservoir observations.
-- Apply only after the exact paid output database has been independently verified.
-- No existing main-track table or model is altered by this migration.
CREATE TABLE IF NOT EXISTS oracle_track_b_state (
  id INTEGER PRIMARY KEY CHECK (id=1),
  started_at TIMESTAMPTZ NOT NULL
);
INSERT INTO oracle_track_b_state(id,started_at) VALUES(1,NOW()) ON CONFLICT(id) DO NOTHING;
CREATE TABLE IF NOT EXISTS oracle_market_discovery (
  market_slug TEXT PRIMARY KEY,
  official_market_id TEXT NOT NULL,
  official_ptb DOUBLE PRECISION NOT NULL CHECK (official_ptb > 0),
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  title TEXT NOT NULL,
  metadata JSONB NOT NULL,
  discovered_at TIMESTAMPTZ NOT NULL,
  discovery_source TEXT NOT NULL DEFAULT 'polymarket_us_gateway',
  CHECK (window_end > window_start)
);
CREATE INDEX IF NOT EXISTS oracle_market_discovery_window_idx
  ON oracle_market_discovery(window_start DESC,window_end DESC);
CREATE TABLE IF NOT EXISTS oracle_source_forecasts (
  id BIGSERIAL PRIMARY KEY,
  source_observation_id BIGINT NOT NULL UNIQUE,
  market_slug TEXT NOT NULL,
  official_market_id TEXT NOT NULL,
  official_ptb DOUBLE PRECISION NOT NULL,
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  forecast_at TIMESTAMPTZ NOT NULL,
  source_name TEXT NOT NULL DEFAULT 'FlyWire Biological Reservoir',
  source_model_version INTEGER NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('UP','DOWN')),
  probability_up DOUBLE PRECISION NOT NULL CHECK (probability_up >= 0 AND probability_up <= 1),
  input_features JSONB NOT NULL,
  source_details JSONB NOT NULL DEFAULT '{}'::jsonb,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS oracle_source_forecasts_market_time_idx
  ON oracle_source_forecasts(market_slug,forecast_at DESC);
CREATE TABLE IF NOT EXISTS oracle_decisions (
  id BIGSERIAL PRIMARY KEY,
  market_slug TEXT NOT NULL UNIQUE,
  official_market_id TEXT,
  official_ptb DOUBLE PRECISION,
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  entry_at TIMESTAMPTZ NOT NULL,
  checkpoint_processed_at TIMESTAMPTZ,
  source_forecast_id BIGINT REFERENCES oracle_source_forecasts(id),
  source_direction TEXT CHECK (source_direction IN ('UP','DOWN')),
  oracle_direction TEXT CHECK (oracle_direction IN ('UP','DOWN')),
  oracle_score DOUBLE PRECISION,
  oracle_model_version TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('ENTER','SKIP')),
  reason TEXT NOT NULL,
  source_forecast_at TIMESTAMPTZ,
  source_age_seconds DOUBLE PRECISION,
  entry_inputs JSONB NOT NULL DEFAULT '{}'::jsonb,
  paper_entry_status TEXT NOT NULL DEFAULT 'NOT_ENTERED'
    CHECK (paper_entry_status IN ('NOT_ENTERED','PREDICTION_ONLY','FILL_UNAVAILABLE','FILLED_SIMULATED')),
  fill_price DOUBLE PRECISION,
  fill_assumptions JSONB,
  outcome TEXT CHECK (outcome IN ('UP','DOWN')),
  resolved_at TIMESTAMPTZ,
  outcome_source TEXT,
  correct BOOLEAN,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS oracle_decisions_entry_idx ON oracle_decisions(entry_at DESC);
CREATE INDEX IF NOT EXISTS oracle_decisions_outcome_idx ON oracle_decisions(resolved_at DESC);
CREATE TABLE IF NOT EXISTS oracle_paper_entries (
  id BIGSERIAL PRIMARY KEY,
  market_slug TEXT NOT NULL UNIQUE REFERENCES oracle_decisions(market_slug),
  entry_at TIMESTAMPTZ NOT NULL,
  official_market_id TEXT NOT NULL,
  official_ptb DOUBLE PRECISION NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('UP','DOWN')),
  source_forecast_id BIGINT NOT NULL REFERENCES oracle_source_forecasts(id),
  oracle_model_version TEXT NOT NULL,
  source_forecast_at TIMESTAMPTZ NOT NULL,
  entry_inputs JSONB NOT NULL,
  fill_status TEXT NOT NULL DEFAULT 'UNAVAILABLE' CHECK (fill_status IN ('UNAVAILABLE','SIMULATED','NOT_ATTEMPTED')),
  fill_price DOUBLE PRECISION,
  fill_assumptions JSONB NOT NULL DEFAULT '{}'::jsonb,
  outcome TEXT CHECK (outcome IN ('UP','DOWN')),
  resolved_at TIMESTAMPTZ,
  outcome_source TEXT,
  correct BOOLEAN,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS oracle_paper_entries_outcome_idx ON oracle_paper_entries(resolved_at DESC);

CREATE TABLE IF NOT EXISTS oracle_model_versions (
  version TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('BASELINE','CANDIDATE','ACTIVE','PROMOTED','REJECTED','ROLLED_BACK')),
  trained_at TIMESTAMPTZ,
  training_cutoff TIMESTAMPTZ,
  training_samples INTEGER NOT NULL DEFAULT 0,
  validation_samples INTEGER NOT NULL DEFAULT 0,
  validation_accuracy DOUBLE PRECISION,
  baseline_accuracy DOUBLE PRECISION,
  validation_coverage DOUBLE PRECISION,
  baseline_coverage DOUBLE PRECISION,
  promoted BOOLEAN NOT NULL DEFAULT FALSE,
  rollback_version TEXT,
  parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS oracle_learning_runs (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  training_cutoff TIMESTAMPTZ,
  training_samples INTEGER NOT NULL DEFAULT 0,
  validation_samples INTEGER NOT NULL DEFAULT 0,
  baseline_accuracy DOUBLE PRECISION,
  candidate_accuracy DOUBLE PRECISION,
  baseline_coverage DOUBLE PRECISION,
  candidate_coverage DOUBLE PRECISION,
  accepted BOOLEAN NOT NULL DEFAULT FALSE,
  reason TEXT NOT NULL,
  candidate_version TEXT,
  rollback_version TEXT,
  details JSONB NOT NULL DEFAULT '{}'::jsonb
);
INSERT INTO oracle_model_versions(version,status,parameters,details)
VALUES('baseline-follow-main-v1','BASELINE','{}'::jsonb,
       '{"strategy":"follow eligible FlyWire Biological Reservoir main-track direction","trained_weights":false,"live_trading_enabled":false,"entry_offset_seconds":420,"entry_tolerance_seconds":20}'::jsonb)
ON CONFLICT(version) DO NOTHING;
