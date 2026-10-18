"""Responsive Flask dashboard for paper-only Connectome research."""
import asyncio
import logging
import os
import threading

from canonical_resolver import resolve_price_to_beat, unavailable_price_to_beat
from polymarket_us_ptb import acquire_official_price_to_beat, current_btc_15m_slug
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
 <div class="section-head"><h2>Polymarket US BTC contract</h2><span class="badge warn" id="polyQuoteStatus">PTB UNAVAILABLE</span></div>
 <div class="quote-grid">
  <article class="card"><div class="metric-label">Active US contract</div><div class="quote-value" id="polyContract">Unavailable</div><div class="quote-meta" id="polyQuestion">No trusted Polymarket US contract source configured.</div><div class="quote-meta" id="polyWindow">Contract window: unavailable</div></article>
  <article class="card"><div class="metric-label">US contract probability</div><div class="quote-row"><span>UP chance</span><strong class="quote-value" id="polyUpPct">Unavailable</strong></div><div class="quote-row"><span>DOWN chance</span><strong class="quote-value" id="polyDownPct">Unavailable</strong></div><div class="quote-meta">International Gamma/CLOB quotes are excluded from this US panel.</div><div class="quote-meta" id="polyQuoteTime">Quote received: unavailable</div><div class="quote-meta">US token bid / ask: <strong id="polyUpBid">Unavailable</strong> / <strong id="polyUpAsk">Unavailable</strong></div></article>
  <article class="card"><div class="metric-label">Exchange reference (not PTB)</div><div class="quote-value" id="refPrice">—</div><div class="quote-meta" id="refSource">Reference source: —</div><div class="quote-meta" id="refTime">Timestamp: —</div><div class="quote-meta" id="polyRefTime">Contract start/reference time: —</div></article>
 </div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><div><h2>Recent reservoir observations</h2><p class="small">Price to beat is shown only when verified Polymarket US contract provenance is available. Exchange reference prices and stored observations are not authoritative PTB values.</p></div><span class="small" id="refreshTime">Waiting for first refresh</span></div>
 <div class="table-wrap"><table><thead><tr><th>Captured</th><th>Timeframe</th><th>Checkpoint</th><th>Contract</th><th>Forecast</th><th>UP probability</th><th>DOWN probability</th><th>Price to beat</th><th>Market midpoint</th><th>Order-book depth (bid / ask · imbalance)</th><th>Exchange quotes (bid / ask · age)</th><th>Outcome</th><th>Brier</th><th>Learned</th></tr></thead><tbody id="bioRows"><tr><td colspan="14" class="empty">Connecting to reservoir telemetry…</td></tr></tbody></table></div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><div><h2>Verified contracts</h2><p class="small">Only contracts with an explicit verified UP/DOWN settlement are listed. Pending or inferred outcomes are excluded.</p></div><span class="small" id="verifiedRefresh">Waiting for verified outcomes</span></div>
 <div class="cards" style="margin-bottom:12px">
  <article class="card"><div class="metric-label">Verified outcomes</div><div class="metric" id="verifiedCount">—</div></article>
  <article class="card"><div class="metric-label">Correct forecasts</div><div class="metric" id="verifiedCorrect">—</div></article>
  <article class="card"><div class="metric-label">Directional accuracy</div><div class="metric" id="verifiedAccuracy">—</div></article>
  <article class="card"><div class="metric-label">Mean Brier score</div><div class="metric" id="verifiedBrier">—</div></article>
  <article class="card"><div class="metric-label">Last verified</div><div class="metric" id="verifiedLast">—</div></article>
 </div>
 <div class="table-wrap"><table><thead><tr><th>Contract</th><th>Timeframe</th><th>Checkpoint</th><th>Forecast</th><th>UP probability</th><th>Verified outcome</th><th>Correct</th><th>Brier</th><th>Learning update</th><th>Update applied at</th><th>Model version</th><th>Settlement source</th><th>Verified at</th></tr></thead><tbody id="verifiedRows"><tr><td colspan="13" class="empty">Loading verified contracts…</td></tr></tbody></table></div>
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
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=14;td.className="empty";td.textContent="No reservoir observations recorded yet";tr.appendChild(td);body.appendChild(tr)}
  rows.forEach(x=>{const tr=document.createElement("tr");const q=x.btc_quotes||{};const qfmt=s=>{const v=q[s];if(!v)return s+": —";const bid=v.bid_usd==null?"—":usd(v.bid_usd),ask=v.ask_usd==null?"—":usd(v.ask_usd),age=v.quote_age_seconds==null?"—":Math.round(Number(v.quote_age_seconds))+"s";return s+": "+bid+" / "+ask+" · "+age};const exchangeQuotes=["coinbase","kraken","binance"].map(qfmt).join(" | ");const depthNum=v=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString("en-US",{maximumFractionDigits:4});const depth="Bid "+depthNum(x.market_bid_depth)+" / Ask "+depthNum(x.market_ask_depth)+" · Imbalance "+(x.market_depth_imbalance==null?"—":Number(x.market_depth_imbalance).toFixed(3));const vals=[fmtTime(x.captured_at),x.timeframe||"—",x.checkpoint||"continuous",x.market_slug||"—",x.forecast_direction||"—",x.probability_up==null?"—":(100*Number(x.probability_up)).toFixed(1)+"%",x.probability_up==null?"—":(100*(1-Number(x.probability_up))).toFixed(1)+"%",x.price_to_beat==null?"UNAVAILABLE":usd(x.price_to_beat),x.market_midpoint==null?"—":Number(x.market_midpoint).toFixed(4),depth,exchangeQuotes,x.outcome||"PENDING",x.brier_score==null?"—":Number(x.brier_score).toFixed(5),x.learning_update_applied?"YES":"—"];vals.forEach(v=>{const td=document.createElement("td");td.textContent=String(v);tr.appendChild(td)});body.appendChild(tr)});
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
let liveQuoteRequestId=0;
let activeTrustedUsContractId=null;
function isCurrentLiveQuoteResponse(requestId,currentRequestId){return requestId===currentRequestId;}
function expectedCurrentUsContractId(nowMs=Date.now()){
 const start=new Date(Math.floor(nowMs/900000)*900000);
 return "btc-updown-15m-"+start.toISOString().slice(0,16).replace("T","-").replace(":","")+"z";
}
function canonicalPtbValue(payload, expectedContractId, nowMs=Date.now()){
 if(!payload||payload.status!=="verified"||payload.source!=="polymarket_us_official"||payload.provenance_verified!==true)return null;
 if(!expectedContractId||payload.contract_id!==expectedContractId)return null;
 const price=Number(payload.price_to_beat), retrieved=Date.parse(payload.retrieved_at);
 const start=Date.parse(payload.contract_start_at), end=Date.parse(payload.contract_end_at);
 if(!Number.isFinite(price)||price<=0||!Number.isFinite(retrieved)||!Number.isFinite(start)||!Number.isFinite(end))return null;
 if(end-start!==900000||nowMs<start||nowMs>=end||retrieved>nowMs+1000||nowMs-retrieved>120000)return null;
 return price;
}
function updatePtbForContract(contractId,payload,nowMs=Date.now()){
 if(contractId!==activeTrustedUsContractId){activeTrustedUsContractId=contractId||null;clearPtb("Contract changed; waiting for verified Polymarket US price-to-beat data.");}
 const value=canonicalPtbValue(payload,activeTrustedUsContractId,nowMs);
 if(value===null){clearPtb(payload&&payload.reason?payload.reason:undefined);return null;}
 put("polyContract",activeTrustedUsContractId);
 put("polyQuestion","Official Polymarket US field: assetPriceTerms.priceToBeat");
 put("polyWindow","Window: "+fmtTime(payload.contract_start_at)+" – "+fmtTime(payload.contract_end_at)+" · PTB: "+usd(value));
 put("polyQuoteTime","PTB source: official Polymarket US market metadata");put("polyRefTime","Official PTB retrieved: "+fmtTime(payload.retrieved_at));
 const status=el("polyQuoteStatus");if(status){status.textContent="PTB VERIFIED";status.className="badge good";}
 return value;
}
function clearPtb(reason="No trusted Polymarket US price-to-beat source is configured."){
 put("polyContract","Unavailable");put("polyQuestion",reason);put("polyWindow","Contract window: unavailable");
 put("polyUpPct","Unavailable");put("polyDownPct","Unavailable");put("polyUpBid","Unavailable");put("polyUpAsk","Unavailable");put("polyQuoteTime","Quote received: unavailable");put("polyRefTime","PTB timestamp: unavailable");
 const status=el("polyQuoteStatus");if(status){status.textContent="PTB UNAVAILABLE";status.className="badge warn"}
}
async function refreshLiveQuotes(){
 const requestId=++liveQuoteRequestId;
 clearPtb();
 try{
  const r=await fetch("/api/live-quotes?ts="+Date.now(),{cache:"no-store"});const d=await r.json();if(!isCurrentLiveQuoteResponse(requestId,liveQuoteRequestId))return;if(!r.ok)throw new Error(d.message||("HTTP "+r.status));
  for(const [key,prefix] of [["binance","qBinance"],["coinbase","qCoinbase"],["kraken","qKraken"]]){
   const q=(d.sources||{})[key]||{};put(prefix+"Price",usd(q.price));put(prefix+"Bid",usd(q.bid));put(prefix+"Ask",usd(q.ask));
   put(prefix+"Time","Received: "+fmtTime(q.received_at));put(prefix+"Age",q.error?"Unavailable: "+q.error:ageLabel(q.received_at));
  }
  const ptb=d.polymarket||{};updatePtbForContract(expectedCurrentUsContractId(),ptb);
  const ref=d.reference||{};put("refPrice",usd(ref.price));put("refSource","Exchange reference (not PTB): "+(ref.source||"—"));put("refTime","Timestamp: "+fmtTime(ref.received_at));
  put("quoteRefresh","Last refreshed "+new Date().toLocaleTimeString("en-US",{timeZone:"America/New_York"})+" ET");
 }catch(e){if(!isCurrentLiveQuoteResponse(requestId,liveQuoteRequestId))return;put("quoteRefresh","Live quote refresh failed: "+String(e.message||e))}
}

async function refreshVerifiedContracts(){
 try{
  const r=await fetch("/api/verified-contracts?ts="+Date.now(),{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.message||("HTTP "+r.status));
  const m=d.metrics||{};put("verifiedCount",m.verified??0);put("verifiedCorrect",m.correct==null?"—":m.correct+" / "+(m.verified??0));put("verifiedAccuracy",m.accuracy_pct==null?"—":Number(m.accuracy_pct).toFixed(1)+"%");put("verifiedBrier",m.mean_brier==null?"—":Number(m.mean_brier).toFixed(5));put("verifiedLast",fmtTime(m.last_verified_at));
  const body=el("verifiedRows");body.replaceChildren();const rows=Array.isArray(d.contracts)?d.contracts:[];
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=13;td.className="empty";td.textContent="No explicitly verified reservoir outcomes yet. Pending contracts are intentionally excluded.";tr.appendChild(td);body.appendChild(tr)}
  rows.forEach(x=>{const tr=document.createElement("tr");const vals=[x.market_slug||"—",x.timeframe||"—",x.checkpoint||"—",x.forecast_direction||"—",x.probability_up==null?"—":(100*Number(x.probability_up)).toFixed(1)+"%",x.outcome||"—",x.correct==null?"—":(x.correct?"YES":"NO"),x.brier_score==null?"—":Number(x.brier_score).toFixed(5),x.learning_update_applied?"APPLIED":"NOT APPLIED",fmtTime(x.learning_applied_at),x.model_version==null?"—":"v"+x.model_version,x.settlement_source||"Explicit settlement recorded",fmtTime(x.verified_at)];vals.forEach(v=>{const td=document.createElement("td");td.textContent=String(v);tr.appendChild(td)});body.appendChild(tr)});
  put("verifiedRefresh","Updated "+new Date().toLocaleTimeString("en-US",{timeZone:"America/New_York"})+" ET");
 }catch(e){put("verifiedRefresh","Could not load verified outcomes: "+String(e.message||e))}
}
clock();setInterval(clock,1000);refreshReservoir();setInterval(refreshReservoir,10000);refreshLiveQuotes();setInterval(refreshLiveQuotes,5000);refreshVerifiedContracts();setInterval(refreshVerifiedContracts,15000);
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
                forecast_direction, probability_up,
                NULL::double precision AS price_to_beat,
                market_midpoint, market_bid_depth, market_ask_depth, market_depth_imbalance, order_book_levels, outcome, brier_score,
                learning_update_applied, details->'btc_feed_asof'->'samples' AS btc_quotes
                FROM biological_reservoir_observations
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


@app.get("/api/verified-contracts")
def verified_contracts():
    """List only reservoir records carrying an explicit verified UP/DOWN outcome."""
    url = os.getenv("CONNECTOME_DATABASE_URL")
    if not url:
        return jsonify({"ok": False, "message": "CONNECTOME_DATABASE_URL is not configured.", "metrics": {}, "contracts": []}), 503
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(url, connect_timeout=4, row_factory=dict_row) as conn:
            exists = conn.execute("SELECT to_regclass('public.biological_reservoir_observations') AS obs_table").fetchone()
            if not exists or not exists["obs_table"]:
                return jsonify({"ok": True, "metrics": {"verified": 0, "correct": 0, "accuracy_pct": None, "mean_brier": None, "last_verified_at": None}, "contracts": []})
            metrics = conn.execute("""
                SELECT count(*) AS verified,
                       count(*) FILTER (WHERE upper(forecast_direction)=upper(outcome)) AS correct,
                       avg(brier_score) FILTER (WHERE brier_score IS NOT NULL) AS mean_brier,
                       max(NULLIF(details->>'settled_at','')::timestamptz) AS last_verified_at
                FROM biological_reservoir_observations
                WHERE outcome IN ('UP','DOWN') AND details->>'outcome_verified'='true' AND details ? 'settlement_source'
            """).fetchone()
            rows = conn.execute("""
                SELECT o.market_slug, o.captured_at, o.checkpoint, o.forecast_direction,
                       o.probability_up, o.outcome, o.brier_score, o.learning_update_applied,
                       o.details->>'learning_applied_at' AS learning_applied_at,
                       NULLIF(o.details->>'reservoir_model_version', '')::integer AS model_version,
                       o.details->>'settlement_source' AS settlement_source,
                       NULLIF(o.details->>'settled_at','')::timestamptz AS verified_at,
                       o.details->>'contract_timeframe' AS timeframe,
                       (upper(o.forecast_direction)=upper(o.outcome)) AS correct
                FROM biological_reservoir_observations o
                WHERE o.outcome IN ('UP','DOWN') AND o.details->>'outcome_verified'='true' AND o.details ? 'settlement_source'
                ORDER BY NULLIF(o.details->>'settled_at','')::timestamptz DESC NULLS LAST,
                         o.captured_at DESC
                LIMIT 200
            """).fetchall()
        n = int(metrics["verified"] or 0)
        correct = int(metrics["correct"] or 0)
        return jsonify({"ok": True, "research_only": True, "live_trading_enabled": False,
            "metrics": {"verified": n, "correct": correct,
                "accuracy_pct": round(100 * correct / n, 2) if n else None,
                "mean_brier": round(float(metrics["mean_brier"]), 5) if metrics["mean_brier"] is not None else None,
                "last_verified_at": metrics["last_verified_at"]},
            "contracts": rows})
    except Exception as exc:
        logging.exception("Verified contracts endpoint failed")
        return jsonify({"ok": False, "message": type(exc).__name__ + ": " + str(exc),
                        "metrics": {}, "contracts": []}), 500


def _get_json(url, timeout=4, headers=None):
    """Fetch a small public market-data JSON response without adding dependencies."""
    import json
    from urllib.request import Request, urlopen
    request = Request(url, headers=headers or {"User-Agent": "biological-reservoir-dashboard/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@app.get("/api/live-quotes")
def live_quotes():
    """Serve independent exchange references and fail-closed Polymarket US PTB state."""
    from datetime import timezone
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

    # Exchange quotes are informational references only, never contract PTB values.
    reference = next(({"source": name.upper(), "price": q.get("price"), "received_at": q.get("received_at")}
                      for name in ("binance", "coinbase", "kraken")
                      if (q := sources.get(name, {})).get("price") is not None), {})
    candidate = acquire_official_price_to_beat()
    if candidate.get("status") == "unavailable":
        poly = candidate
    else:
        poly = resolve_price_to_beat(candidate, expected_contract_id=current_btc_15m_slug())
    return jsonify({"ok": True, "sources": sources, "reference": reference, "polymarket": poly,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "refresh_seconds": 5, "research_only": True, "live_trading_enabled": False})


@app.get("/health")
def health():
    return jsonify({"ok": True, "live_trading": False})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
