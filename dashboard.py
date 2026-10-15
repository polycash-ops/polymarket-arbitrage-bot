"""Paper-only web dashboard for the fork's existing strategy."""
import asyncio
import logging
import os
import threading
from flask import Flask, jsonify

from main import TradingBot

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
bot = None
bot_error = None
lock = threading.Lock()


def _run_bot():
    global bot, bot_error
    try:
        bot = TradingBot(os.getenv("BOT_CONFIG", "config.example.yaml"), paper_trading=True)
        asyncio.run(bot.start())
    except Exception as exc:
        bot_error = f"{type(exc).__name__}: {exc}"
        logging.exception("Forked paper bot failed")


def _ensure_bot():
    with lock:
        if not any(t.name == "forked-paper-bot" and t.is_alive() for t in threading.enumerate()):
            threading.Thread(target=_run_bot, name="forked-paper-bot", daemon=True).start()


@app.get("/")
def index():
    _ensure_bot()
    return """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Polymarket Arbitrage Bot — Paper</title>
<style>body{font:16px system-ui;background:#10141b;color:#edf2f7;margin:0;padding:20px}main{max-width:900px;margin:auto}.card{background:#1b2430;padding:16px;border-radius:12px;margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>
</head><body><main><h1>Polymarket Arbitrage Bot</h1><p>Forked strategy · Paper trading only · Live execution hard-blocked</p>
<div class="card"><h2>Performance and status</h2><pre id="status">Loading…</pre></div>
<div class="card"><h2>Recent paper trades</h2><pre id="trades">Loading…</pre></div>
<div class="card"><h2>Market data</h2><pre id="prices">Loading…</pre></div>
<script>async function r(){try{let d=await(await fetch('/api/status',{cache:'no-store'})).json();document.getElementById('status').textContent=JSON.stringify({mode:d.mode,live_trading:d.live_trading,bot_running:d.bot_running,bot_error:d.bot_error,stats:d.stats,performance:d.performance},null,2);document.getElementById('trades').textContent=JSON.stringify(d.recent_trades||[],null,2);document.getElementById('prices').textContent=JSON.stringify({latest_prices:d.latest_prices,price_spreads:d.price_spreads},null,2)}catch(e){document.getElementById('status').textContent=String(e)}}r();setInterval(r,5000)</script>
</main></body></html>"""


@app.get("/health")
def health():
    return jsonify({"ok": True, "live_trading": False})


@app.get("/api/status")
def status():
    _ensure_bot()
    if bot is None:
        return jsonify({"mode": "paper", "live_trading": False, "bot_running": False,
                        "bot_error": bot_error, "recent_trades": []})
    try:
        data = bot.get_status()
        data["bot_running"] = any(t.name == "forked-paper-bot" and t.is_alive() for t in threading.enumerate())
        data["bot_error"] = bot_error
        data["live_trading"] = False
        data["recent_trades"] = [
            {"id": t.id, "action": t.action, "amount_usd": t.amount, "status": t.status.value,
             "profit_loss_usd": t.profit_loss, "confidence": getattr(t.opportunity, "confidence", None),
             "direction": getattr(t.opportunity, "direction", None), "exchange_moved": getattr(t.opportunity, "exchange_moved", None)}
            for t in bot.trade_executor.get_recent_trades(20)
        ]
        return jsonify(data)
    except Exception as exc:
        logging.exception("Status endpoint failed")
        return jsonify({"mode": "paper", "live_trading": False, "bot_running": False,
                        "bot_error": str(exc), "recent_trades": []}), 500


if __name__ == "__main__":
    _ensure_bot()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
