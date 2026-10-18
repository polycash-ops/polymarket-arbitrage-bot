"""Signal Oracle dashboard blueprint; must use the same production store as worker."""
from flask import Blueprint, jsonify

def create_oracle_blueprint(store_provider):
    bp = Blueprint("signal_oracle", __name__)

    @bp.get("/api/track-b/signal-oracle")
    def signal_oracle_status():
        try:
            store = store_provider()
            # Production adapter must implement metrics and latest persisted records.
            if not getattr(store, "production_shared_store", False):
                return jsonify({"ok": True, "configured": False,
                    "state": "Oracle strategy not configured",
                    "paper_only": True, "live_trading_enabled": False,
                    "reason": "shared durable worker/dashboard PostgreSQL adapter not registered",
                    "metrics": {"rolling_accuracy_pct": None, "lifetime_accuracy_pct": None},
                    "signals": [], "trades": []})
            return jsonify(store.dashboard_payload())
        except Exception:
            return jsonify({"ok": False, "state": "unavailable",
                "paper_only": True, "live_trading_enabled": False}), 503

    return bp
