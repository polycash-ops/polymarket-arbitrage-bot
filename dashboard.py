"""Responsive Flask dashboard for paper-only Connectome research."""
import asyncio
import logging
import os
import threading
from datetime import datetime

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
        bot_error = type(exc).__name__ + ": " + str(exc)
        logging.exception("Paper Connectome bot failed")


def _ensure_bot():
    with lock:
        if not any(t.name == "forked-paper-bot" and t.is_alive() for t in threading.enumerate()):
            threading.Thread(target=_run_bot, name="forked-paper-bot", daemon=True).start()


@app.get("/")
def index():
    """Serve only the independent Biological Reservoir research dashboard."""
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#101722">
<title>Biological Reservoir · Independent Research Agent</title>
<style>
:root{color-scheme:dark;--bg:#0b111a;--panel:#141e2b;--panel2:#101925;--line:#273649;--text:#edf3fa;--muted:#9aabc0;--green:#54d6a0;--red:#ff8585;--amber:#ffd078}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#17283a 0,#0b111a 55%);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:clamp(14px,4vw,34px)}header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px}
h1{font-size:clamp(1.5rem,4vw,2.2rem);line-height:1.15;margin:0 0 8px;letter-spacing:-.03em}h2{font-size:1.05rem;margin:0}.subtitle,.small{color:var(--muted)}.subtitle{margin:0}.small{font-size:.82rem}
.pill{display:inline-flex;align-items:center;gap:8px;border:1px solid #24664e;background:#123327;color:#a8f0cf;border-radius:999px;padding:7px 12px;font-size:.83rem;font-weight:700;white-space:nowrap}
.section{margin-top:18px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden}.panel-inner{padding:18px}.section-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.quote-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.quote-value{font-size:1.25rem;font-weight:750;overflow-wrap:anywhere}.quote-meta{color:var(--muted);font-size:.8rem;margin-top:5px}.quote-row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:8px}.quote-row span{color:var(--muted)}.card{min-width:0;background:linear-gradient(145deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:16px;padding:16px}.metric-label{color:var(--muted);font-size:.82rem;margin-bottom:6px}.metric{font-size:clamp(1.2rem,3vw,1.75rem);font-weight:750;letter-spacing:-.035em;overflow-wrap:anywhere}.metric-sub{font-size:.8rem;color:var(--muted);margin-top:5px}
.badge{border-radius:8px;padding:4px 8px;font-size:.78rem;font-weight:750;background:#263449;color:#dce8f8}.badge.good{background:#123327;color:#a8f0cf}.badge.warn{background:#392d17;color:var(--amber)}.badge.bad{background:#3a2026;color:#ffb4b4}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:760px}th,td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.06em;font-weight:700;background:#111a26}tbody tr:last-child td{border-bottom:0}.empty{text-align:center;color:var(--muted);padding:24px 16px}.foot{color:var(--muted);font-size:.8rem;margin:22px 2px 0}
@media(max-width:850px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.quote-grid{grid-template-columns:1fr}}@media(max-width:440px){main{padding:12px}.card{padding:13px}.metric{font-size:1.4rem}}
</style>
</head>
<body><main>
<header><div><h1>Biological Reservoir · independent research agent</h1><p class="subtitle">Persistent BTC-history research · graph observations and learning evidence · paper forecasting only</p></div><div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px"><span id="clock" class="pill">--:--:-- ET</span><span class="pill">LIVE TRADING BLOCKED</span></div></header>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Reservoir agent status</h2><span id="bioStatus" class="badge warn">CHECKING</span></div>
 <p class="small" id="bioMessage">Connecting to persisted reservoir telemetry…</p>
 <div class="cards" style="margin-top:12px">
  <article class="card"><div class="metric-label">Graph nodes</div><div class="metric" id="bioNodes">—</div><div class="metric-sub" id="bioGraph">Graph pending</div></article>
  <article class="card"><div class="metric-label">Graph edges</div><div class="metric" id="bioEdges">—</div><div class="metric-sub" id="bioSnapshot">Latest snapshot: —</div></article>
  <article class="card"><div class="metric-label">Recorded observations</div><div class="metric" id="bioObservations">—</div><div class="metric-sub" id="bioUpdated">Latest: —</div></article>
  <article class="card"><div class="metric-label">Learning updates</div><div class="metric" id="bioLearning">—</div><div class="metric-sub" id="bioAccuracy">Resolved accuracy: —</div></article>
  <article class="card"><div class="metric-label">Model / market Brier</div><div class="metric" id="bioBrier">—</div><div class="metric-sub" id="bioExpansion">Last graph expansion: —</div></article>
 </div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Live BTC quote sources</h2><span class="small" id="quoteRefresh">Waiting for live quotes</span></div>
 <div class="quote-grid">
  <article class="card"><div class="metric-label">Binance US · BTC</div><div class="quote-value" id="qBinancePrice">—</div><div class="quote-row"><span>Bid</span><strong id="qBinanceBid">—</strong><span>Ask</span><strong id="qBinanceAsk">—</strong></div><div class="quote-meta" id="qBinanceTime">Received: —</div><div class="quote-meta" id="qBinanceAge">Status: waiting</div></article>
  <article class="card"><div class="metric-label">Coinbase · BTC</div><div class="quote-value" id="qCoinbasePrice">—</div><div class="quote-row"><span>Bid</span><strong id="qCoinbaseBid">—</strong><span>Ask</span><strong id="qCoinbaseAsk">—</strong></div><div class="quote-meta" id="qCoinbaseTime">Received: —</div><div class="quote-meta" id="qCoinbaseAge">Status: waiting</div></article>
  <article class="card"><div class="metric-label">Kraken · BTC</div><div class="quote-value" id="qKrakenPrice">—</div><div class="quote-row"><span>Bid</span><strong id="qKrakenBid">—</strong><span>Ask</span><strong id="qKrakenAsk">—</strong></div><div class="quote-meta" id="qKrakenTime">Received: —</div><div class="quote-meta" id="qKrakenAge">Status: waiting</div></article>
 </div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Current Polymarket BTC contract</h2><span class="badge warn" id="polyQuoteStatus">CONNECTING</span></div>
 <div class="quote-grid">
  <article class="card"><div class="metric-label">Active 15-minute contract</div><div class="quote-value" id="polyContract">—</div><div class="quote-meta" id="polyQuestion">—</div><div class="quote-meta" id="polyWindow">Contract window: —</div></article>
  <article class="card"><div class="metric-label">UP token · live best bid / ask</div><div class="quote-value" id="polyUpMid">—</div><div class="quote-row"><span>Bid</span><strong id="polyUpBid">—</strong><span>Ask</span><strong id="polyUpAsk">—</strong></div><div class="quote-meta" id="polyQuoteTime">Quote received: —</div></article>
  <article class="card"><div class="metric-label">Reference BTC price timestamp</div><div class="quote-value" id="refPrice">—</div><div class="quote-meta" id="refSource">Reference source: —</div><div class="quote-meta" id="refTime">Timestamp: —</div><div class="quote-meta" id="polyRefTime">Contract start/reference time: —</div></article>
 </div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Recent reservoir observations</h2><span class="small" id="refreshTime">Waiting for first refresh</span></div>
 <div class="table-wrap"><table><thead><tr><th>Captured</th><th>Timeframe</th><th>Checkpoint</th><th>Contract</th><th>Forecast</th><th>Up probability</th><th>Market midpoint</th><th>Outcome</th><th>Brier</th><th>Learned</th></tr></thead><tbody id="bioRows"><tr><td colspan="9" class="empty">Connecting to reservoir telemetry…</td></tr></tbody></table></div>
</div></section>
<p class="foot">This dashboard reads only the Biological Reservoir research tables. It does not start or control the Polymarket arbitrage bot. All activity is research-only; live trading is hard-blocked.</p>
</main>
<script>
const el=id=>document.getElementById(id);
function put(id,value){const n=el(id);if(n)n.textContent=value}
function fmtTime(v){if(!v)return "—";const d=new Date(v);return isNaN(d)?String(v):d.toLocaleString("en-US",{timeZone:"America/New_York"})}
function clock(){put("clock",new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:true}).format(new Date())+" ET")}
async function refreshReservoir(){
 const badge=el("bioStatus");
 try{
  const r=await fetch("/api/biological-reservoir?ts="+Date.now(),{cache:"no-store"});
  const d=await r.json();
  if(!r.ok)throw new Error(d.message||("HTTP "+r.status));
  const m=d.model||{},o=d.observations||{};
  put("bioStatus",d.status||"INITIALIZING");
  if(badge)badge.className="badge "+(["WORKING","RECENT ACTIVITY","RECORDING"].includes(d.status)?"good":["STALE","ERROR","NOT CONNECTED"].includes(d.status)?"bad":"warn");
  put("bioNodes",m.node_count??0);put("bioEdges",m.edge_count??0);
  put("bioSnapshot","Latest snapshot: "+(o.latest_snapshot_id??m.last_snapshot_id??"—"));
  put("bioGraph",(m.model_version==null?"—":"v"+m.model_version)+" · "+(m.graph_snapshot||"graph pending"));
  put("bioObservations",o.total??0);put("bioLearning",o.learning_updates??m.learning_updates??0);
  put("bioUpdated","Latest: "+fmtTime(o.latest_at||m.updated_at));
  put("bioAccuracy","Resolved accuracy: "+(o.accuracy_pct==null?"—":Number(o.accuracy_pct).toFixed(2)+"%")+" · "+(o.settled??0)+" resolved");
  put("bioBrier",(o.brier_score==null?"—":Number(o.brier_score).toFixed(5))+" / "+(o.market_brier_score==null?"—":Number(o.market_brier_score).toFixed(5)));
  put("bioExpansion","Last graph expansion: "+fmtTime(m.last_expansion_at));
  put("bioMessage",d.message||"Telemetry loaded from persistent reservoir tables.");
  const body=el("bioRows");body.replaceChildren();const rows=Array.isArray(d.recent)?d.recent:[];
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=10;td.className="empty";td.textContent="No reservoir observations recorded yet";tr.appendChild(td);body.appendChild(tr)}
  rows.forEach(x=>{const tr=document.createElement("tr");const vals=[fmtTime(x.captured_at),x.timeframe||"—",x.checkpoint||"continuous",x.market_slug||"—",x.forecast_direction||"—",x.probability_up==null?"—":(100*Number(x.probability_up)).toFixed(1)+"%",x.market_midpoint==null?"—":Number(x.market_midpoint).toFixed(4),x.outcome||"PENDING",x.brier_score==null?"—":Number(x.brier_score).toFixed(5),x.learning_update_applied?"YES":"—"];vals.forEach(v=>{const td=document.createElement("td");td.textContent=String(v);tr.appendChild(td)});body.appendChild(tr)});
  put("refreshTime","Last refreshed "+new Date().toLocaleTimeString("en-US",{timeZone:"America/New_York"})+" ET");
 }catch(e){
  if(badge){badge.textContent="NOT CONNECTED";badge.className="badge bad"}
  put("bioMessage","Reservoir telemetry unavailable: "+String(e.message||e)+". Check CONNECTOME_DATABASE_URL on this dashboard service.");
  put("refreshTime","Refresh failed · "+new Date().toLocaleTimeString("en-US",{timeZone:"America/New_York"})+" ET");
 }
}

function usd(v){return v==null||!Number.isFinite(Number(v))?"—":"$"+Number(v).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})}
function cents(v){return v==null||!Number.isFinite(Number(v))?"—":(100*Number(v)).toFixed(2)+"¢"}
function ageLabel(v){if(!v)return "No timestamp";const age=Math.max(0,(Date.now()-new Date(v).getTime())/1000);return age<60?"Quote age: "+Math.round(age)+"s": "Quote age: "+Math.floor(age/60)+"m "+Math.round(age%60)+"s"}
async function refreshLiveQuotes(){
 try{
  const r=await fetch("/api/live-quotes?ts="+Date.now(),{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.message||("HTTP "+r.status));
  for(const [key,prefix] of [["binance","qBinance"],["coinbase","qCoinbase"],["kraken","qKraken"]]){
   const q=(d.sources||{})[key]||{};put(prefix+"Price",usd(q.price));put(prefix+"Bid",usd(q.bid));put(prefix+"Ask",usd(q.ask));
   put(prefix+"Time","Received: "+fmtTime(q.received_at));put(prefix+"Age",q.error?"Unavailable: "+q.error:ageLabel(q.received_at));
  }
  const p=d.polymarket||{};put("polyContract",p.slug||"No active 15m BTC contract found");put("polyQuestion",p.question||"");put("polyWindow",(p.start_at||p.end_at)?"Contract window: "+fmtTime(p.start_at)+" – "+fmtTime(p.end_at):"Contract window: —");
  put("polyUpMid",p.midpoint==null?"—":cents(p.midpoint));put("polyUpBid",cents(p.bid));put("polyUpAsk",cents(p.ask));put("polyQuoteTime","Quote received: "+fmtTime(p.received_at));
  const status=el("polyQuoteStatus");if(status){status.textContent=p.error?"QUOTE UNAVAILABLE":p.slug?"LIVE QUOTE":"NO CONTRACT";status.className="badge "+(p.error||!p.slug?"warn":"good")}
  const ref=d.reference||{};put("refPrice",usd(ref.price));put("refSource","Reference source: "+(ref.source||"—"));put("refTime","Timestamp: "+fmtTime(ref.received_at));put("polyRefTime","Contract start/reference time: "+fmtTime(p.start_at));
  put("quoteRefresh","Last refreshed "+new Date().toLocaleTimeString("en-US",{timeZone:"America/New_York"})+" ET");
 }catch(e){put("quoteRefresh","Live quote refresh failed: "+String(e.message||e))}
}

clock();setInterval(clock,1000);refreshReservoir();setInterval(refreshReservoir,10000);refreshLiveQuotes();setInterval(refreshLiveQuotes,5000);
</script></body></html>"""


@app.get("/api/biological-reservoir")
def biological_reservoir_status():
    """Read persisted status for the separate Biological Reservoir research worker."""
    url = os.getenv("CONNECTOME_DATABASE_URL")
    if not url:
        return jsonify({"ok": False, "status": "NOT CONFIGURED", "message": "CONNECTOME_DATABASE_URL is not set on this dashboard service.", "model": None, "observations": {}, "recent": []}), 503
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(url, connect_timeout=4, row_factory=dict_row) as conn:
            ready = conn.execute("SELECT to_regclass('public.biological_reservoir_model_state') AS model_table, to_regclass('public.biological_reservoir_observations') AS obs_table").fetchone()
            if not ready["model_table"] or not ready["obs_table"]:
                return jsonify({"ok": True, "status": "INITIALIZING", "message": "Dashboard is connected; telemetry tables are not initialized yet. Status will update when the worker creates them.", "model": None, "observations": {}, "recent": []})
            model = conn.execute("""SELECT model_version, graph_snapshot, graph_hash,
                jsonb_array_length(node_ids) AS node_count, edge_count, learning_updates,
                last_snapshot_id, last_expansion_at, updated_at
                FROM biological_reservoir_model_state WHERE id=1""").fetchone()
            if not model:
                return jsonify({"ok": True, "status": "INITIALIZING", "message": "Reservoir model state row has not been created yet.", "model": None, "observations": {}, "recent": []})
            stats = conn.execute("""SELECT count(*) AS total, max(captured_at) AS latest_at,
                max(snapshot_id) AS latest_snapshot_id,
                count(*) FILTER (WHERE outcome IS NOT NULL) AS settled,
                count(*) FILTER (WHERE outcome IS NOT NULL AND upper(forecast_direction)=upper(outcome)) AS correct,
                avg(brier_score) FILTER (WHERE brier_score IS NOT NULL) AS brier_score,
                count(*) FILTER (WHERE learning_update_applied) AS learning_updates
                FROM biological_reservoir_observations""").fetchone()
            market = conn.execute("""SELECT avg(power(market_midpoint -
                CASE WHEN upper(outcome)='UP' THEN 1.0 ELSE 0.0 END, 2)) AS score
                FROM biological_reservoir_observations WHERE outcome IS NOT NULL""").fetchone()
            recent = conn.execute("""SELECT snapshot_id, market_slug, captured_at, details->>'contract_timeframe' AS timeframe, checkpoint,
                forecast_direction, probability_up, market_midpoint, outcome, brier_score,
                learning_update_applied FROM biological_reservoir_observations
                ORDER BY captured_at DESC, snapshot_id DESC LIMIT 30""").fetchall()
        settled = int(stats["settled"] or 0)
        # Use whichever persisted heartbeat is newer: model-state writes can lag
        # while the worker continues appending observation snapshots.
        timestamps = [value for value in (model["updated_at"], stats["latest_at"]) if value is not None]
        latest = max(timestamps) if timestamps else None
        age = max(0, (datetime.now().astimezone() - latest.astimezone()).total_seconds()) if latest else None
        status = "WORKING" if age is not None and age <= 30 else "RECENT ACTIVITY" if age is not None and age <= 180 else "STALE" if age is not None else "INITIALIZING"
        return jsonify({"ok": True, "status": status, "research_only": True, "live_trading_enabled": False,
            "model": model, "observations": {"total": int(stats["total"] or 0),
            "latest_at": stats["latest_at"], "latest_snapshot_id": stats["latest_snapshot_id"],
            "settled": settled, "accuracy_pct": round(100 * int(stats["correct"] or 0) / settled, 2) if settled else None,
            "brier_score": round(float(stats["brier_score"]), 5) if stats["brier_score"] is not None else None,
            "market_brier_score": round(float(market["score"]), 5) if market["score"] is not None else None,
            "learning_updates": int(stats["learning_updates"] or 0)}, "recent": recent,
            "message": "Research/paper forecasts only. Accuracy counts only resolved outcomes; learning counts persisted updates."})
    except Exception as exc:
        logging.exception("Biological Reservoir telemetry endpoint failed")
        return jsonify({"ok": False, "status": "ERROR", "message": type(exc).__name__ + ": " + str(exc), "model": None, "observations": {}, "recent": []}), 500


def _get_json(url, timeout=4, headers=None):
    """Fetch a small public market-data JSON response without adding dependencies."""
    import json
    from urllib.request import Request, urlopen
    request = Request(url, headers=headers or {"User-Agent": "biological-reservoir-dashboard/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@app.get("/api/live-quotes")
def live_quotes():
    """Serve fresh public BTC reference quotes and the active Polymarket 15m contract."""
    import time
    from datetime import timezone, timedelta
    from urllib.parse import quote
    received = datetime.now(timezone.utc).isoformat()
    sources = {}
    source_specs = {
        "binance": ("https://api.binance.us/api/v3/ticker/24hr?symbol=BTCUSD", "https://api.binance.us/api/v3/ticker/bookTicker?symbol=BTCUSD"),
        "coinbase": ("https://api.exchange.coinbase.com/products/BTC-USD/ticker", None),
        "kraken": ("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", None),
    }
    for name, (ticker_url, book_url) in source_specs.items():
        try:
            headers = {"User-Agent": "biological-reservoir-dashboard/1.0"}
            data = _get_json(ticker_url, headers=headers)
            if name == "binance":
                book = _get_json(book_url, headers=headers)
                sources[name] = {"price": float(data["lastPrice"]), "bid": float(book["bidPrice"]), "ask": float(book["askPrice"]), "received_at": datetime.now(timezone.utc).isoformat()}
            elif name == "coinbase":
                sources[name] = {"price": float(data["price"]), "bid": float(data["bid"]), "ask": float(data["ask"]), "received_at": datetime.now(timezone.utc).isoformat()}
            else:
                result = data.get("result") or {}
                ticker = next(iter(result.values()))
                sources[name] = {"price": float(ticker["c"][0]), "bid": float(ticker["b"][0]), "ask": float(ticker["a"][0]), "received_at": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:
            sources[name] = {"error": type(exc).__name__ + ": " + str(exc), "received_at": datetime.now(timezone.utc).isoformat()}

    # Use Binance US as the explicit reference source when available; fall back to Coinbase then Kraken.
    reference = next(({"source": name.upper(), "price": q.get("price"), "received_at": q.get("received_at")}
                      for name in ("binance", "coinbase", "kraken")
                      if (q := sources.get(name, {})).get("price") is not None), {})

    now = datetime.now(timezone.utc)
    start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    slugs = []
    for window in (start, start + timedelta(minutes=15)):
        epoch = int(window.timestamp())
        slugs.extend([
            f"btc-updown-15m-{epoch}",
            f"bitcoin-updown-15m-{epoch}",
            f"cpc-btc-updown-15m-{window:%Y-%m-%d}-{window:%H%M}z",
        ])
    poly = {"received_at": datetime.now(timezone.utc).isoformat()}
    try:
        market = None
        for slug in slugs:
            try:
                candidate = _get_json("https://gamma-api.polymarket.com/markets/slug/" + quote(slug, safe="-"), timeout=3)
                if isinstance(candidate, list):
                    candidate = candidate[0] if candidate else None
                if isinstance(candidate, dict) and candidate.get("slug") == slug and not candidate.get("closed"):
                    end_raw = candidate.get("endDate") or candidate.get("endDateIso") or candidate.get("end_date")
                    end_at = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00")) if end_raw else None
                    if end_at is None or end_at > now:
                        market = candidate
                        break
            except Exception:
                continue
        if market:
            import json
            outcomes = market.get("outcomes") or []
            tokens = market.get("clobTokenIds") or []
            if isinstance(outcomes, str): outcomes = json.loads(outcomes)
            if isinstance(tokens, str): tokens = json.loads(tokens)
            up_index = next((i for i, name in enumerate(outcomes) if "up" in str(name).lower()), 0)
            bid = ask = midpoint = None
            if len(tokens) > up_index:
                book = _get_json("https://clob.polymarket.com/book?token_id=" + quote(str(tokens[up_index]), safe=""), timeout=3)
                bids, asks = book.get("bids") or [], book.get("asks") or []
                bid = max((float(level["price"]) for level in bids if level.get("price") is not None), default=None)
                ask = min((float(level["price"]) for level in asks if level.get("price") is not None), default=None)
                midpoint = (bid + ask) / 2 if bid is not None and ask is not None else bid if bid is not None else ask
            start_raw = market.get("eventStartTime") or market.get("startDate") or market.get("startDateIso")
            end_raw = market.get("endDate") or market.get("endDateIso") or market.get("end_date")
            poly.update({"slug": market.get("slug"), "question": market.get("question"),
                         "start_at": start_raw, "end_at": end_raw,
                         "bid": bid, "ask": ask, "midpoint": midpoint,
                         "received_at": datetime.now(timezone.utc).isoformat()})
        else:
            poly["error"] = "No active BTC 15-minute contract matched the known current/next slugs."
    except Exception as exc:
        poly["error"] = type(exc).__name__ + ": " + str(exc)
    return jsonify({"ok": True, "sources": sources, "reference": reference, "polymarket": poly,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "refresh_seconds": 5, "research_only": True, "live_trading_enabled": False})


@app.get("/health")
def health():
    return jsonify({"ok": True, "live_trading": False})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
