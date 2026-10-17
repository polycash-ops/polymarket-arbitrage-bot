"""Responsive Flask dashboard for paper-only Connectome research."""
import asyncio
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from flask import Flask, jsonify
from main import TradingBot

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
bot = None
bot_error = None
lock = threading.Lock()


# Contract metadata (consumer view):
# VERIFIED as read by existing PR2 SQL: market_slug, captured_at, snapshot_id,
#   forecast_direction, probability_up, outcome, checkpoint, brier_score,
#   details.contract_timeframe, details.outcome_verified, details.settlement_source,
#   details.settled_at, details.contract_timeline.current_contract.reference_price,
#   details.fixture_key / is_synthetic filters.
# PROPOSED / NOT verified against worker producer code in this session:
#   details.issued_at, current_contract.start_at/end_at, alert_sequence.
# REQUIRED for open-contract + active-alert panels: identity + trustworthy window
#   bounds + issued_at. Missing bounds => NO_OPEN_CONTRACT (no guess).
DATA_CONTRACT_NOTE = True

from reservoir_consumer import (
    SCORING_POLICY,
    FRESHNESS_DEFAULTS,
    parse_aware_timestamp,
    is_15_minute_product,
    select_open_contract,
    select_active_up_down_alert,
    alerts_to_graph_annotations,
    compute_rolling_accuracy,
    normalize_contract_price_series,
    outcome_provenance_trusted,
)


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
  <article class="card"><div class="metric-label">UP / DOWN · implied probability</div><div class="quote-row"><span>UP chance</span><strong class="quote-value" id="polyUpPct">—</strong></div><div class="quote-row"><span>DOWN chance</span><strong class="quote-value" id="polyDownPct">—</strong></div><div class="quote-meta">Calculated from the UP-token midpoint</div><div class="quote-meta" id="polyQuoteTime">Quote received: —</div><div class="quote-meta">UP token bid / ask: <strong id="polyUpBid">—</strong> / <strong id="polyUpAsk">—</strong></div></article>
  <article class="card"><div class="metric-label">Reference BTC price timestamp</div><div class="quote-value" id="refPrice">—</div><div class="quote-meta" id="refSource">Reference source: —</div><div class="quote-meta" id="refTime">Timestamp: —</div><div class="quote-meta" id="polyRefTime">Contract start/reference time: —</div></article>
 </div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><div><h2>Active contract alert</h2><p class="small">Real worker-issued UP/DOWN for the exact open 15-minute contract only. Prior contracts never carry forward.</p></div>
  <span class="badge warn" id="alertStatus">CHECKING</span></div>
 <div class="grid">
  <article class="card"><div class="metric-label">Open contract</div><div class="quote-value" id="alertContract">—</div><div class="quote-meta" id="alertWindow">Window: —</div></article>
  <article class="card"><div class="metric-label">Active UP/DOWN alert</div><div class="quote-value" id="alertDirection">—</div><div class="quote-meta" id="alertIssued">Issued: —</div></article>
  <article class="card"><div class="metric-label">Issuance source</div><div class="quote-value" id="alertIssuanceSource">—</div><div class="quote-meta" id="alertLifecycle">Lifecycle: —</div></article>
  <article class="card"><div class="metric-label">Trusted graph alert markers</div><div class="quote-value" id="alertAnnotationCount">—</div><div class="quote-meta" id="alertAnnotationNote">Only timestamped, trusted issuance for the exact contract can be overlaid. Missing producer issuance remains unavailable.</div></article>
 </div>
 <ul id="alertAnnotationList" class="small" style="margin:0.5rem 0 0 1.25rem;padding:0"></ul>
 <p class="small" id="alertMessage">Loading active alert…</p>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><div><h2>Exact-contract Polymarket midpoint history</h2><p class="small">Real persisted 15-minute contract snapshots with trusted alert issuance markers when available. Contract rollover clears the prior series.</p></div><span class="badge warn" id="priceChartStatus">WAITING</span></div>
 <p class="small" id="priceChartMessage" role="status">Waiting for the active contract and timestamped price series.</p>
 <div id="contractPriceChart" aria-label="Polymarket UP-token midpoint over the active 15-minute contract" style="width:100%;min-height:240px;overflow:hidden"></div>
 <p class="small" id="priceChartLegend">Line: persisted UP-token midpoint · Vertical markers: trusted issued UP/DOWN alerts for this exact contract only.</p>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><div><h2>Rolling 24h accuracy</h2><p class="small">UP/DOWN-only proposed policy. Public values remain unavailable until explicit scoring-policy approval.</p></div>
  <span class="badge warn" id="accuracyStatus">POLICY PENDING</span></div>
 <div class="grid">
  <article class="card"><div class="metric-label">Accuracy</div><div class="metric" id="accPct">—</div><div class="metric-sub" id="accMessage">Pending approval</div></article>
  <article class="card"><div class="metric-label">Correct / Incorrect</div><div class="metric" id="accCorrect">—</div><div class="metric-sub" id="accScored">Scored: —</div></article>
  <article class="card"><div class="metric-label">Pending / Excluded</div><div class="metric" id="accPending">—</div><div class="metric-sub" id="accExcluded">Excluded: —</div></article>
  <article class="card"><div class="metric-label">Policy</div><div class="metric" id="accPolicyStatus">UNAPPROVED</div><div class="metric-sub" id="accPolicyId">—</div></article>
 </div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><div><h2>Recent reservoir observations</h2><p class="small">UP/DOWN probabilities estimate which side wins at contract expiry relative to that contract’s price to beat. Price to beat is the BTC reference price recorded for the contract.</p></div><span class="small" id="refreshTime">Waiting for first refresh</span></div>
 <div class="table-wrap"><table><thead><tr><th>Captured</th><th>Timeframe</th><th>Checkpoint</th><th>Contract</th><th>Forecast</th><th>UP probability</th><th>DOWN probability</th><th>Price to beat</th><th>Market midpoint</th><th>Order-book depth (bid / ask · imbalance)</th><th>Exchange quotes (bid / ask · age)</th><th>Outcome</th><th>Brier</th><th>Learned</th></tr></thead><tbody id="bioRows"><tr><td colspan="14" class="empty">Connecting to reservoir telemetry…</td></tr></tbody></table></div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><div><h2>Contract signal history</h2><p class="small">Last five persisted forecasts per contract. Pending outcomes remain pending; only explicitly verified settlements count as verified.</p></div><span class="small" id="signalHistoryRefresh">Waiting for signal history</span></div>
 <div class="table-wrap"><table><thead><tr><th>Contract</th><th>Captured</th><th>Timeframe</th><th>Checkpoint</th><th>Forecast</th><th>UP probability</th><th>Outcome</th><th>Verified</th><th>Brier</th></tr></thead><tbody id="signalHistoryRows"><tr><td colspan="9" class="empty">Loading contract signal history…</td></tr></tbody></table></div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><div><h2>Verified contracts</h2><p class="small">Only contracts with an explicit verified UP/DOWN settlement are listed. Pending or inferred outcomes are excluded.</p></div><span class="small" id="verifiedRefresh">Waiting for verified outcomes</span></div>
 <div class="cards" style="margin-bottom:12px">
  <article class="card"><div class="metric-label">Verified outcomes</div><div class="metric" id="verifiedCount">—</div></article>
  <article class="card"><div class="metric-label">Scoring policy</div><div class="metric" id="verifiedCorrect">Pending approval</div></article>
  <article class="card"><div class="metric-label">Directional accuracy</div><div class="metric" id="verifiedAccuracy">—</div></article>
  <article class="card"><div class="metric-label">Mean Brier score</div><div class="metric" id="verifiedBrier">Unavailable</div></article>
  <article class="card"><div class="metric-label">Last verified</div><div class="metric" id="verifiedLast">—</div></article>
 </div>
 <div class="table-wrap"><table><thead><tr><th>Contract</th><th>Timeframe</th><th>Verified outcome</th><th>Settlement source</th><th>Verified at</th></tr></thead><tbody id="verifiedRows"><tr><td colspan="5" class="empty">Loading verified contracts…</td></tr></tbody></table></div>
</div></section>
<p class="foot">This dashboard reads only the Biological Reservoir research tables. It does not start or control the Polymarket arbitrage bot. All activity is research-only; live trading is hard-blocked.</p>
</main>
<script>
const el=id=>document.getElementById(id);
function put(id,value){const n=el(id);if(n)n.textContent=value}
function fmtTime(v){if(!v)return "—";const d=new Date(v);return isNaN(d)?String(v):d.toLocaleString("en-US",{timeZone:"America/New_York"})}
function clock(){put("clock",new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:true}).format(new Date())+" ET")}
let activeAlertState={contractIdentity:null,annotations:[]};
let priceChartGeneration=0, priceChartSlug=null, lastPriceChartFetchAt=0, lastPriceSeries=null;
const svgNS="http://www.w3.org/2000/svg";
function svgNode(tag,attrs={},label){const n=document.createElementNS(svgNS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));if(label!==undefined)n.textContent=String(label);return n;}
function clearPriceChart(message,status="UNAVAILABLE",tone="warn"){
 const host=el("contractPriceChart");if(host)host.replaceChildren();const b=el("priceChartStatus");if(b){b.textContent=status;b.className="badge "+tone;}put("priceChartMessage",message);lastPriceSeries=null;
}
function renderContractPriceChart(d){
 if(!d||!Array.isArray(d.points)||d.points.length<2){clearPriceChart((d&&d.message)||"No adequate timestamped midpoint series exists for this exact contract.",d&&d.status||"UNAVAILABLE");return;}
 const points=d.points.map(p=>({t:new Date(p.captured_at).getTime(),v:Number(p.midpoint)})).filter(p=>Number.isFinite(p.t)&&Number.isFinite(p.v)&&p.v>=0&&p.v<=1).sort((a,b)=>a.t-b.t);
 if(points.length<2){clearPriceChart("No adequate timestamped midpoint series exists for this exact contract.","UNAVAILABLE");return;}
 const W=900,H=300,L=54,R=18,T=18,B=38,iw=W-L-R,ih=H-T-B;
 const x=t=>L+(t-points[0].t)/(Math.max(1,points[points.length-1].t-points[0].t))*iw;
 const y=v=>T+(1-v)*ih;
 const host=el("contractPriceChart");if(!host)return;host.replaceChildren();
 const svg=svgNode("svg",{viewBox:`0 0 ${W} ${H}`,width:"100%",height:"auto",role:"img","aria-label":"Exact contract midpoint time series with alert issuance markers"});
 [0,.25,.5,.75,1].forEach(v=>{svg.appendChild(svgNode("line",{x1:L,y1:y(v),x2:W-R,y2:y(v),stroke:"#34465c","stroke-width":1}));svg.appendChild(svgNode("text",{x:L-8,y:y(v)+4,"text-anchor":"end",fill:"#9aabc0","font-size":12},(v*100).toFixed(0)+"¢"));});
 const line=points.map(p=>`${x(p.t).toFixed(2)},${y(p.v).toFixed(2)}`).join(" ");svg.appendChild(svgNode("polyline",{points:line,fill:"none",stroke:"#65b8ff","stroke-width":2.5,"stroke-linejoin":"round","stroke-linecap":"round"}));
 const start=new Date(d.window_start),end=new Date(d.window_end);svg.appendChild(svgNode("text",{x:L,y:H-10,fill:"#9aabc0","font-size":12},start.toLocaleTimeString("en-US",{timeZone:"America/New_York",hour:"2-digit",minute:"2-digit"})+" ET"));svg.appendChild(svgNode("text",{x:W-R,y:H-10,"text-anchor":"end",fill:"#9aabc0","font-size":12},end.toLocaleTimeString("en-US",{timeZone:"America/New_York",hour:"2-digit",minute:"2-digit"})+" ET"));
 const anns=activeAlertState.contractIdentity===d.contract_identity?activeAlertState.annotations:[];let drawn=0;
 anns.forEach(a=>{const t=new Date(a.x||a.issued_at).getTime();if(!Number.isFinite(t)||t<start.getTime()||t>=end.getTime())return;const nearest=points.reduce((best,p)=>Math.abs(p.t-t)<Math.abs(best.t-t)?p:best,points[0]);const xx=x(t),yy=y(nearest.v),color=a.direction==="UP"?"#54d6a0":"#ff8585";svg.appendChild(svgNode("line",{x1:xx,y1:T,x2:xx,y2:T+ih,stroke:color,"stroke-width":1.5,"stroke-dasharray":"5 4"}));svg.appendChild(svgNode("circle",{cx:xx,cy:yy,r:5,fill:color,stroke:"#0b111a","stroke-width":2}));svg.appendChild(svgNode("text",{x:Math.min(W-R-45,Math.max(L,xx+5)),y:T+14+drawn*14,fill:color,"font-size":12,"font-weight":700},a.direction+" alert"));drawn++;});
 host.appendChild(svg);const stale=d.status==="STALE";const b=el("priceChartStatus");if(b){b.textContent=stale?"STALE SERIES":"FRESH SERIES";b.className="badge "+(stale?"warn":"good");}
 put("priceChartMessage",`${d.contract_identity} · ${points.length} persisted points · latest ${fmtTime(d.latest_at)} · age ${Math.round(Number(d.age_seconds)||0)}s`+(drawn?` · ${drawn} trusted alert marker(s)`:" · no trusted issuance markers for this contract")+(stale?" · not current live evidence":""));
 lastPriceSeries=d;
}
async function refreshContractPriceChart(slug){
 const now=Date.now();if(!slug){if(priceChartSlug!==null){priceChartGeneration++;priceChartSlug=null;clearPriceChart("No active Polymarket 15-minute contract is available.","NO CONTRACT");}return;}
 const changed=slug!==priceChartSlug;if(!changed&&now-lastPriceChartFetchAt<10000)return;
 if(changed){priceChartSlug=slug;lastPriceSeries=null;const host=el("contractPriceChart");if(host)host.replaceChildren();put("priceChartMessage","Contract rolled over; loading a fresh exact-contract series.");}
 const generation=++priceChartGeneration;lastPriceChartFetchAt=now;
 try{const r=await fetch("/api/contract-price-series?market_slug="+encodeURIComponent(slug)+"&ts="+now,{cache:"no-store"});const d=await r.json();if(generation!==priceChartGeneration||priceChartSlug!==slug)return;if(d.contract_identity!==slug){clearPriceChart("The returned series does not match the active contract; it was discarded.","IDENTITY MISMATCH","bad");return;}renderContractPriceChart(d);}
 catch(e){if(generation!==priceChartGeneration||priceChartSlug!==slug)return;clearPriceChart("Price series unavailable: "+String(e.message||e),"UNAVAILABLE","warn");}
}
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
  put("bioAccuracy","Accuracy unavailable pending scoring-policy approval · "+(o.settled??0)+" resolved rows");
  put("bioBrier",(o.brier_score==null?"—":Number(o.brier_score).toFixed(5))+" / "+(o.market_brier_score==null?"—":Number(o.market_brier_score).toFixed(5)));
  put("bioExpansion","Last graph expansion: "+fmtTime(m.last_expansion_at));
  const freshness=d.freshness||{};const wf=freshness.worker_heartbeat||{};const sf=freshness.source_snapshot||{};put("bioMessage",(d.message||"Telemetry loaded from persistent reservoir tables.")+" Worker heartbeat: "+(wf.status||"UNAVAILABLE")+"; source snapshot: "+(sf.status||"UNAVAILABLE")+".");
  const body=el("bioRows");body.replaceChildren();const rows=Array.isArray(d.recent)?d.recent:[];
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=14;td.className="empty";td.textContent="No reservoir observations recorded yet";tr.appendChild(td);body.appendChild(tr)}
  rows.forEach(x=>{const tr=document.createElement("tr");const q=x.btc_quotes||{};const qfmt=s=>{const v=q[s];if(!v)return s+": —";const bid=v.bid_usd==null?"—":usd(v.bid_usd),ask=v.ask_usd==null?"—":usd(v.ask_usd),age=v.quote_age_seconds==null?"—":Math.round(Number(v.quote_age_seconds))+"s";return s+": "+bid+" / "+ask+" · "+age};const exchangeQuotes=["coinbase","kraken","binance"].map(qfmt).join(" | ");const depthNum=v=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString("en-US",{maximumFractionDigits:4});const depth="Bid "+depthNum(x.market_bid_depth)+" / Ask "+depthNum(x.market_ask_depth)+" · Imbalance "+(x.market_depth_imbalance==null?"—":Number(x.market_depth_imbalance).toFixed(3));const vals=[fmtTime(x.captured_at),x.timeframe||"—",x.checkpoint||"continuous",x.market_slug||"—",x.forecast_direction||"—",x.probability_up==null?"—":(100*Number(x.probability_up)).toFixed(1)+"%",x.probability_up==null?"—":(100*(1-Number(x.probability_up))).toFixed(1)+"%",x.price_to_beat==null?"—":usd(x.price_to_beat),x.market_midpoint==null?"—":Number(x.market_midpoint).toFixed(4),depth,exchangeQuotes,x.outcome||"PENDING",x.brier_score==null?"—":Number(x.brier_score).toFixed(5),x.learning_update_applied?"YES":"—"];vals.forEach(v=>{const td=document.createElement("td");td.textContent=String(v);tr.appendChild(td)});body.appendChild(tr)});
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
  const upPct=p.midpoint==null?null:Math.max(0,Math.min(100,100*Number(p.midpoint)));put("polyUpPct",upPct==null?"—":upPct.toFixed(1)+"%");put("polyDownPct",upPct==null?"—":(100-upPct).toFixed(1)+"%");put("polyUpBid",cents(p.bid));put("polyUpAsk",cents(p.ask));put("polyQuoteTime","Quote received: "+fmtTime(p.received_at));
  const status=el("polyQuoteStatus");if(status){status.textContent=p.error?"QUOTE UNAVAILABLE":p.slug?"LIVE QUOTE":"NO CONTRACT";status.className="badge "+(p.error||!p.slug?"warn":"good")}
  refreshContractPriceChart(p.slug||null);
  const ref=d.reference||{};put("refPrice",usd(ref.price));put("refSource","Reference source: "+(ref.source||"—"));put("refTime","Timestamp: "+fmtTime(ref.received_at));put("polyRefTime","Contract start/reference time: "+fmtTime(p.start_at));
  put("quoteRefresh","Last refreshed "+new Date().toLocaleTimeString("en-US",{timeZone:"America/New_York"})+" ET");
 }catch(e){put("quoteRefresh","Live quote refresh failed: "+String(e.message||e))}
}

async function refreshVerifiedContracts(){
 try{
  const r=await fetch("/api/verified-contracts?ts="+Date.now(),{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.message||("HTTP "+r.status));
  const m=d.metrics||{};put("verifiedCount",m.verified??0);put("verifiedCorrect","Pending approval");put("verifiedAccuracy",m.accuracy_status==="UNAVAILABLE_POLICY_PENDING"?"Unavailable · scoring policy pending":"—");put("verifiedBrier","Unavailable pending policy");put("verifiedLast",fmtTime(m.last_verified_at));
  const body=el("verifiedRows");body.replaceChildren();const rows=Array.isArray(d.contracts)?d.contracts:[];
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=5;td.className="empty";td.textContent="No explicitly verified reservoir outcomes yet. Pending contracts are intentionally excluded.";tr.appendChild(td);body.appendChild(tr)}
  rows.forEach(x=>{const tr=document.createElement("tr");const vals=[x.market_slug||"—",x.timeframe||"—",x.outcome||"—",x.settlement_source||"Explicit settlement recorded",fmtTime(x.verified_at)];vals.forEach(v=>{const td=document.createElement("td");td.textContent=String(v);tr.appendChild(td)});body.appendChild(tr)});
  put("verifiedRefresh","Updated "+new Date().toLocaleTimeString("en-US",{timeZone:"America/New_York"})+" ET");
 }catch(e){put("verifiedRefresh","Could not load verified outcomes: "+String(e.message||e))}
}
async function refreshSignalHistory(){
 try{
  const r=await fetch("/api/reservoir-signal-history?ts="+Date.now(),{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.message||("HTTP "+r.status));
  const body=el("signalHistoryRows");body.replaceChildren();const rows=Array.isArray(d.contracts)?d.contracts:[];
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=9;td.className="empty";td.textContent=d.status==="SCHEMA NOT INITIALIZED"?"Reservoir observation schema is not initialized.":"No persisted contract forecasts yet.";tr.appendChild(td);body.appendChild(tr)}
  rows.forEach(x=>{const tr=document.createElement("tr");const vals=[x.market_slug||"—",fmtTime(x.captured_at),x.timeframe||"—",x.checkpoint||"continuous",x.forecast_direction||"NO SIGNAL",x.probability_up==null?"—":(100*Number(x.probability_up)).toFixed(1)+"%",x.outcome||"PENDING",x.outcome_verified?"YES":"NO",x.brier_score==null?"—":Number(x.brier_score).toFixed(5)];vals.forEach(v=>{const td=document.createElement("td");td.textContent=String(v);tr.appendChild(td)});body.appendChild(tr)});
  put("signalHistoryRefresh","Updated "+new Date().toLocaleTimeString("en-US",{timeZone:"America/New_York"})+" ET · "+rows.length+" forecasts");
 }catch(e){put("signalHistoryRefresh","Could not load signal history: "+String(e.message||e))}
}


/* Request generation: ignore late responses after contract rollover. */
window.__reservoirAlertGeneration = window.__reservoirAlertGeneration || 0;
function bumpAlertGeneration(){ window.__reservoirAlertGeneration += 1; return window.__reservoirAlertGeneration; }
function applyAlertPayload(generation, d){
  if(generation !== window.__reservoirAlertGeneration){ return false; }
  const st=el("alertStatus");
  activeAlertState={contractIdentity:(d.status==="ACTIVE"&&d.contract&&d.contract.identity)||null,annotations:(d.status==="ACTIVE"&&Array.isArray(d.graph_annotations)?d.graph_annotations:[])};
  if(lastPriceSeries)renderContractPriceChart(lastPriceSeries);
  const list=el("alertAnnotationList");
  if(list){ list.replaceChildren(); }
  if(d.status==="ACTIVE"&&d.alert){
    if(st){st.textContent="ACTIVE "+d.alert.direction;st.className="badge ok";}
    put("alertContract",d.contract&&d.contract.identity||"—");
    put("alertWindow",d.contract?("start "+(d.contract.start_at||"—")+" · end "+(d.contract.end_at||"—")):"—");
    put("alertDirection",d.alert.direction);
    put("alertIssued",fmtTime(d.alert.issued_at));
    put("alertIssuanceSource",d.alert.issuance_timestamp_source||"—");
    put("alertLifecycle",d.alert.lifecycle||"active");
    const anns=Array.isArray(d.graph_annotations)?d.graph_annotations:[];
    put("alertAnnotationCount",anns.length);
    if(list){
      anns.forEach(a=>{
        const li=document.createElement("li");
        li.textContent=(a.direction||"—")+" @ "+(a.x||a.issued_at||"—")+" · "+(a.contract_identity||"");
        list.appendChild(li);
      });
    }
    put("alertMessage",d.issuance_note||"Active alert loaded.");
  }else{
    if(st){st.textContent=d.status||"NO ALERT";st.className="badge warn";}
    put("alertContract",(d.contract&&d.contract.identity)||"No open 15m contract");
    put("alertWindow","—");
    put("alertDirection", d.status==="AMBIGUOUS_ALERT" ? "Ambiguous — no active alert." : "No active UP/DOWN alert.");
    put("alertIssued","—");
    put("alertIssuanceSource","—");
    put("alertLifecycle","—");
    put("alertAnnotationCount",0);
    put("alertMessage",d.message||d.reason||"No active UP/DOWN alert.");
  }
  return true;
}
async function refreshActiveAlert(){
  const generation = bumpAlertGeneration();
  try{
    const r=await fetch("/api/active-alert?ts="+Date.now(),{cache:"no-store"});
    const d=await r.json();
    if(!applyAlertPayload(generation, d)){
      /* Stale response after rollover/generation bump — ignored. */
      return;
    }
  }catch(e){
    if(generation !== window.__reservoirAlertGeneration){ return; }
    const st=el("alertStatus");if(st){st.textContent="ERROR";st.className="badge bad";}
    put("alertMessage","Active alert fetch failed: "+String(e.message||e));
  }
}
async function refreshRollingAccuracy(){
  try{
    const r=await fetch("/api/rolling-accuracy?ts="+Date.now(),{cache:"no-store"});
    const d=await r.json();
    const st=el("accuracyStatus");
    const pol=d.policy||{};
    put("accPolicyStatus",pol.status||d.status||"UNAPPROVED");
    put("accPolicyId",pol.id||"—");
    if(d.status==="UNAVAILABLE_POLICY_PENDING"||!d.policy_approved_env){
      if(st){st.textContent="POLICY PENDING";st.className="badge warn";}
      put("accPct","—");
      put("accMessage",d.message||"Accuracy unavailable pending scoring-policy approval.");
      put("accCorrect","—");
      put("accScored","Scored: —");
      put("accPending","—");
      put("accExcluded","Excluded: —");
    }else if(d.status==="UNAVAILABLE_NO_SCORED"||d.scored_total===0){
      if(st){st.textContent="NO SCORED";st.className="badge warn";}
      put("accPct","—");
      put("accMessage",d.message||"Accuracy unavailable — no scored outcomes.");
      put("accCorrect",String(d.correct??0));
      put("accScored","Scored: "+(d.scored_total??0));
      put("accPending",String(d.pending??0));
      put("accExcluded","Excluded: "+(d.excluded??0));
    }else{
      if(st){st.textContent="SCORED";st.className="badge ok";}
      put("accPct",d.accuracy_pct==null?"—":Number(d.accuracy_pct).toFixed(2)+"%");
      put("accMessage","Policy "+(pol.id||""));
      put("accCorrect",(d.correct??0)+" / "+(d.incorrect??0));
      put("accScored","Scored: "+(d.scored_total??0));
      put("accPending",String(d.pending??0));
      put("accExcluded","Excluded: "+(d.excluded??0));
    }
  }catch(e){
    const st=el("accuracyStatus");if(st){st.textContent="ERROR";st.className="badge bad";}
    put("accMessage","Accuracy fetch failed: "+String(e.message||e));
  }
}
clock();setInterval(clock,1000);refreshReservoir();setInterval(refreshReservoir,10000);refreshLiveQuotes();setInterval(refreshLiveQuotes,5000);refreshVerifiedContracts();setInterval(refreshVerifiedContracts,15000);refreshSignalHistory();setInterval(refreshSignalHistory,15000);refreshActiveAlert();setInterval(refreshActiveAlert,10000);refreshRollingAccuracy();setInterval(refreshRollingAccuracy,30000);</script></body></html>"""


def _reservoir_columns(conn, table_name):
    """Return actual public-table columns; missing telemetry is a supported state."""
    rows = conn.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
    """, (table_name,)).fetchall()
    return {row["column_name"] for row in rows}


def _freshness(timestamp, *, now=None, fresh_seconds=30, recent_seconds=180):
    """Describe a timestamp without substituting unrelated timestamps for missing telemetry."""
    now = now or datetime.now().astimezone()
    if timestamp is None:
        return {"status": "UNAVAILABLE", "timestamp": None, "age_seconds": None}
    age = max(0, (now - timestamp.astimezone()).total_seconds())
    status = "FRESH" if age <= fresh_seconds else "RECENT" if age <= recent_seconds else "STALE"
    return {"status": status, "timestamp": timestamp, "age_seconds": round(age, 1)}


@app.get("/api/biological-reservoir")
def biological_reservoir_status():
    """Read independent worker, source, observation, and directional-signal freshness."""
    url = os.getenv("CONNECTOME_DATABASE_URL")
    if not url:
        return jsonify({"ok": False, "status": "NOT CONFIGURED",
                        "message": "CONNECTOME_DATABASE_URL is not set on this dashboard service.",
                        "model": None, "observations": {}, "recent": [], "freshness": {}}), 503
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(url, connect_timeout=4, row_factory=dict_row) as conn:
            ready = conn.execute("""
                SELECT to_regclass('public.biological_reservoir_model_state') AS model_table,
                       to_regclass('public.biological_reservoir_observations') AS obs_table
            """).fetchone()
            if not ready["model_table"] or not ready["obs_table"]:
                return jsonify({"ok": True, "status": "INITIALIZING",
                    "message": "Connected; Reservoir telemetry tables are not initialized.",
                    "model": None, "observations": {}, "recent": [], "freshness": {
                        "worker_heartbeat": {"status": "UNAVAILABLE", "timestamp": None, "age_seconds": None},
                        "source_snapshot": {"status": "UNAVAILABLE", "timestamp": None, "age_seconds": None}}})
            model_columns = _reservoir_columns(conn, "biological_reservoir_model_state")
            heartbeat_expr = "worker_heartbeat_at" if "worker_heartbeat_at" in model_columns else "NULL::timestamptz AS worker_heartbeat_at"
            source_expr = "source_snapshot_at" if "source_snapshot_at" in model_columns else "NULL::timestamptz AS source_snapshot_at"
            model = conn.execute(f"""
                SELECT model_version, graph_snapshot, graph_hash,
                    jsonb_array_length(node_ids) AS node_count, edge_count, learning_updates,
                    last_snapshot_id, last_expansion_at, updated_at,
                    {heartbeat_expr}, {source_expr}
                FROM biological_reservoir_model_state WHERE id=1
            """).fetchone()
            if not model:
                return jsonify({"ok": True, "status": "INITIALIZING",
                    "message": "Reservoir model state row has not been created yet.",
                    "model": None, "observations": {}, "recent": [], "freshness": {
                        "worker_heartbeat": {"status": "UNAVAILABLE", "timestamp": None, "age_seconds": None},
                        "source_snapshot": {"status": "UNAVAILABLE", "timestamp": None, "age_seconds": None}}})
            stats = conn.execute("""
                SELECT count(*) AS total, max(captured_at) AS latest_at,
                    max(snapshot_id) AS latest_snapshot_id,
                    count(*) FILTER (WHERE outcome IN ('UP','DOWN')
                        AND forecast_direction IN ('UP','DOWN')) AS settled_directional,
                    count(*) FILTER (WHERE outcome IN ('UP','DOWN')
                        AND forecast_direction IN ('UP','DOWN')
                        AND upper(forecast_direction)=upper(outcome)) AS correct_directional,
                    avg(brier_score) FILTER (WHERE brier_score IS NOT NULL) AS brier_score,
                    count(*) FILTER (WHERE learning_update_applied) AS learning_updates
                FROM biological_reservoir_observations
                WHERE COALESCE(details->>'fixture_key','')=''
                  AND COALESCE(details->>'is_synthetic','false') <> 'true'
            """).fetchone()
            market = conn.execute("""
                SELECT avg(power(market_midpoint -
                    CASE WHEN upper(outcome)='UP' THEN 1.0 ELSE 0.0 END, 2)) AS score
                FROM biological_reservoir_observations
                WHERE outcome IN ('UP','DOWN')
                  AND COALESCE(details->>'fixture_key','')=''
                  AND COALESCE(details->>'is_synthetic','false') <> 'true'
            """).fetchone()
            recent = conn.execute("""
                SELECT snapshot_id, market_slug, captured_at,
                    details->>'contract_timeframe' AS timeframe, checkpoint,
                    forecast_direction, probability_up,
                    NULLIF(details->'contract_timeline'->'current_contract'->>'reference_price','')::double precision AS price_to_beat,
                    market_midpoint, market_bid_depth, market_ask_depth, market_depth_imbalance,
                    order_book_levels, outcome, brier_score, learning_update_applied,
                    details->'btc_feed_asof'->'samples' AS btc_quotes
                FROM biological_reservoir_observations
                WHERE COALESCE(details->>'fixture_key','')=''
                  AND COALESCE(details->>'is_synthetic','false') <> 'true'
                ORDER BY captured_at DESC, snapshot_id DESC LIMIT 30
            """).fetchall()
            history = conn.execute("""
                WITH ranked AS (
                    SELECT snapshot_id, market_slug, captured_at,
                        details->>'contract_timeframe' AS timeframe, checkpoint,
                        forecast_direction, probability_up, outcome, brier_score,
                        (details->>'outcome_verified'='true'
                         AND details ? 'settlement_source'
                         AND outcome IN ('UP','DOWN')) AS outcome_verified,
                        row_number() OVER (PARTITION BY market_slug
                            ORDER BY captured_at DESC, snapshot_id DESC) AS contract_row
                    FROM biological_reservoir_observations
                    WHERE market_slug IS NOT NULL
                      AND COALESCE(details->>'fixture_key','')=''
                      AND COALESCE(details->>'is_synthetic','false') <> 'true'
                )
                SELECT * FROM ranked WHERE contract_row <= 5
                ORDER BY captured_at DESC, snapshot_id DESC LIMIT 200
            """).fetchall()
        worker_freshness = _freshness(model["worker_heartbeat_at"])
        source_freshness = _freshness(model["source_snapshot_at"])
        observation_freshness = _freshness(stats["latest_at"])
        signal_time = next((row["captured_at"] for row in recent
                            if row.get("forecast_direction") in ("UP", "DOWN")), None)
        signal_freshness = _freshness(signal_time)
        schema_complete = ("worker_heartbeat_at" in model_columns and "source_snapshot_at" in model_columns)
        worker_status = worker_freshness["status"] if schema_complete else "SCHEMA INCOMPLETE"
        overall = ("WORKING" if worker_status == "FRESH" else
                   "RECENT ACTIVITY" if worker_status == "RECENT" else
                   "STALE" if worker_status == "STALE" else
                   "TELEMETRY SCHEMA INCOMPLETE" if not schema_complete else "WORKER STATUS UNAVAILABLE")
        settled = int(stats["settled_directional"] or 0)
        correct = int(stats["correct_directional"] or 0)
        return jsonify({"ok": True, "status": overall, "research_only": True, "live_trading_enabled": False,
            "model": model, "freshness": {
                "worker_heartbeat": worker_freshness,
                "source_snapshot": source_freshness,
                "model_observation": observation_freshness,
                "trade_signal": signal_freshness,
                "telemetry_schema_complete": schema_complete},
            "observations": {"total": int(stats["total"] or 0),
                "latest_at": stats["latest_at"], "latest_snapshot_id": stats["latest_snapshot_id"],
                "settled": settled, "correct": None,
                "accuracy_status": "UNAVAILABLE_POLICY_PENDING",
                "accuracy_denominator": "not scored; contract scoring unit and forecast-selection rule require approval",
                "accuracy_pct": None,
                "brier_score": round(float(stats["brier_score"]), 5) if stats["brier_score"] is not None else None,
                "market_brier_score": round(float(market["score"]), 5) if market["score"] is not None else None,
                "learning_updates": int(stats["learning_updates"] or 0)},
            "verified_metrics": {
                "accuracy_pct": None,
                "accuracy_status": "UNAVAILABLE_POLICY_PENDING",
                "accuracy_denominator": "not scored; scoring unit and forecast-selection rule require approval",
            },
            "recent": recent, "signal_history": history,
            "message": ("Worker heartbeat and source freshness are separate. Missing telemetry columns are not inferred from model writes or observations. "
                        "Research/paper forecasts only; live trading is hard-blocked.")})
    except Exception as exc:
        logging.exception("Biological Reservoir telemetry endpoint failed")
        return jsonify({"ok": False, "status": "ERROR", "message": type(exc).__name__ + ": " + str(exc),
                        "model": None, "observations": {}, "recent": [], "freshness": {}}), 500


@app.get("/api/verified-contracts")
def verified_contracts():
    """Return outcomes only after authoritative settlement provenance is owner-verified."""
    if not outcome_provenance_trusted():
        return jsonify({
            "ok": True,
            "status": "UNAVAILABLE_OUTCOME_PROVENANCE_PENDING",
            "message": "Outcome verification provenance is not established; no outcomes are represented as verified.",
            "research_only": True,
            "live_trading_enabled": False,
            "metrics": {"verified": None, "accuracy_pct": None,
                        "accuracy_status": "UNAVAILABLE_OUTCOME_PROVENANCE_PENDING",
                        "last_verified_at": None},
            "scoring_policy": {"status": "UNAPPROVED", "unit": None, "forecast_selection": None},
            "contracts": [],
        })
    url = os.getenv("CONNECTOME_DATABASE_URL")
    if not url:
        return jsonify({"ok": False, "message": "CONNECTOME_DATABASE_URL is not configured.",
                        "metrics": {}, "contracts": []}), 503
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(url, connect_timeout=4, row_factory=dict_row) as conn:
            exists = conn.execute(
                "SELECT to_regclass('public.biological_reservoir_observations') AS obs_table"
            ).fetchone()
            if not exists or not exists["obs_table"]:
                return jsonify({
                    "ok": True,
                    "metrics": {"verified": 0, "accuracy_pct": None,
                                "accuracy_status": "UNAVAILABLE_POLICY_PENDING",
                                "last_verified_at": None},
                    "scoring_policy": {"status": "UNAPPROVED", "unit": None, "forecast_selection": None},
                    "contracts": [],
                })
            metrics = conn.execute("""
                SELECT count(DISTINCT market_slug) AS verified,
                       max(NULLIF(details->>'settled_at','')::timestamptz) AS last_verified_at
                FROM biological_reservoir_observations
                WHERE market_slug IS NOT NULL
                  AND outcome IN ('UP','DOWN')
                  AND details->>'outcome_verified'='true'
                  AND NULLIF(BTRIM(details->>'settlement_source'),'') IS NOT NULL
                  AND NULLIF(BTRIM(details->>'settled_at'),'') IS NOT NULL
                  AND COALESCE(details->>'fixture_key','')=''
                  AND COALESCE(details->>'is_synthetic','false') <> 'true'
            """).fetchone()
            rows = conn.execute("""
                WITH verified_outcomes AS (
                    SELECT DISTINCT ON (market_slug)
                        market_slug,
                        details->>'contract_timeframe' AS timeframe,
                        outcome,
                        details->>'settlement_source' AS settlement_source,
                        NULLIF(details->>'settled_at','')::timestamptz AS verified_at,
                        captured_at
                    FROM biological_reservoir_observations
                    WHERE market_slug IS NOT NULL
                      AND outcome IN ('UP','DOWN')
                      AND details->>'outcome_verified'='true'
                      AND NULLIF(BTRIM(details->>'settlement_source'),'') IS NOT NULL
                      AND NULLIF(BTRIM(details->>'settled_at'),'') IS NOT NULL
                      AND COALESCE(details->>'fixture_key','')=''
                      AND COALESCE(details->>'is_synthetic','false') <> 'true'
                    ORDER BY market_slug,
                        NULLIF(details->>'settled_at','')::timestamptz DESC NULLS LAST,
                        captured_at DESC, snapshot_id DESC
                )
                SELECT market_slug, timeframe, outcome, settlement_source, verified_at
                FROM verified_outcomes
                ORDER BY verified_at DESC NULLS LAST, market_slug
                LIMIT 200
            """).fetchall()
        return jsonify({
            "ok": True, "research_only": True, "live_trading_enabled": False,
            "metrics": {
                "verified": int(metrics["verified"] or 0),
                "accuracy_pct": None,
                "accuracy_status": "UNAVAILABLE_POLICY_PENDING",
                "accuracy_denominator": "not scored; contract scoring unit and forecast-selection rule require approval",
                "last_verified_at": metrics["last_verified_at"],
            },
            "scoring_policy": {"status": "UNAPPROVED", "unit": None, "forecast_selection": None},
            "contracts": rows,
        })
    except Exception as exc:
        logging.exception("Verified Reservoir outcomes endpoint failed")
        return jsonify({"ok": False, "message": type(exc).__name__ + ": " + str(exc),
                        "metrics": {}, "contracts": []}), 500


@app.get("/api/reservoir-signal-history")
def reservoir_signal_history():
    """Return bounded per-contract forecast history, including pending but not synthetic records."""
    url = os.getenv("CONNECTOME_DATABASE_URL")
    if not url:
        return jsonify({"ok": False, "message": "CONNECTOME_DATABASE_URL is not configured.", "contracts": []}), 503
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(url, connect_timeout=4, row_factory=dict_row) as conn:
            exists = conn.execute("SELECT to_regclass('public.biological_reservoir_observations') AS obs_table").fetchone()
            if not exists or not exists["obs_table"]:
                return jsonify({"ok": True, "status": "SCHEMA NOT INITIALIZED", "contracts": []})
            rows = conn.execute("""
                WITH ranked AS (
                    SELECT snapshot_id, market_slug, captured_at,
                        details->>'contract_timeframe' AS timeframe, checkpoint,
                        forecast_direction, probability_up, outcome, brier_score,
                        (details->>'outcome_verified'='true'
                         AND NULLIF(BTRIM(details->>'settlement_source'),'') IS NOT NULL
                         AND NULLIF(BTRIM(details->>'settled_at'),'') IS NOT NULL
                         AND outcome IN ('UP','DOWN')) AS outcome_verified,
                        row_number() OVER (PARTITION BY market_slug
                            ORDER BY captured_at DESC, snapshot_id DESC) AS history_rank
                    FROM biological_reservoir_observations
                    WHERE market_slug IS NOT NULL
                      AND COALESCE(details->>'fixture_key','')=''
                      AND COALESCE(details->>'is_synthetic','false') <> 'true'
                )
                SELECT * FROM ranked WHERE history_rank <= 5
                ORDER BY captured_at DESC, snapshot_id DESC LIMIT 200
            """).fetchall()
        return jsonify({"ok": True, "research_only": True, "live_trading_enabled": False,
                        "history_per_contract": 5, "contracts": rows})
    except Exception as exc:
        logging.exception("Reservoir signal history endpoint failed")
        return jsonify({"ok": False, "message": type(exc).__name__ + ": " + str(exc), "contracts": []}), 500

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




@app.get("/api/contract-price-series")
def contract_price_series():
    """Return a bounded, real midpoint series for one exact 15-minute contract."""
    import re
    from flask import request
    identity = (request.args.get("market_slug") or "").strip()
    if not identity or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", identity):
        return jsonify({"ok": False, "status": "UNAVAILABLE_INVALID_REQUEST",
                        "message": "A valid exact market_slug is required.",
                        "contract_identity": identity or None, "points": []}), 400
    url = os.getenv("CONNECTOME_DATABASE_URL")
    if not url:
        return jsonify({"ok": True, "status": "UNAVAILABLE_DATABASE",
                        "message": "CONNECTOME_DATABASE_URL is not configured.",
                        "contract_identity": identity, "points": []}), 503
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(url, connect_timeout=4, row_factory=dict_row) as conn:
            exists = conn.execute("SELECT to_regclass('public.snapshots') AS table_name").fetchone()
            if not exists or not exists["table_name"]:
                return jsonify({"ok": True, "status": "UNAVAILABLE_SOURCE_TABLE",
                                "message": "The persisted Polymarket snapshots table is unavailable.",
                                "contract_identity": identity, "points": []})
            rows = conn.execute("""
                WITH bounded AS (
                    SELECT id, market_slug, captured_at, midpoint, window_start, window_end
                    FROM public.snapshots
                    WHERE market_slug=%s AND timeframe='15m'
                      AND midpoint IS NOT NULL
                      AND window_start IS NOT NULL AND window_end IS NOT NULL
                      AND window_end-window_start=INTERVAL '15 minutes'
                      AND captured_at >= window_start AND captured_at < window_end
                    ORDER BY captured_at DESC, id DESC
                    LIMIT 500
                )
                SELECT market_slug, captured_at, midpoint, window_start, window_end
                FROM bounded ORDER BY captured_at ASC, id ASC
            """, (identity,)).fetchall()
        result = normalize_contract_price_series(rows, identity, datetime.now(timezone.utc))
        return jsonify({"ok": True, "research_only": True, "live_trading_enabled": False, **result})
    except Exception as exc:
        logging.exception("Exact contract price series query failed")
        return jsonify({"ok": False, "status": "UNAVAILABLE_QUERY_ERROR",
                        "message": "Price history is temporarily unavailable; server-side query failed.",
                        "contract_identity": identity, "points": []}), 500


@app.get("/api/current-contract")
def current_contract():
    """
    Resolve the exact open 15-minute contract at evaluation time T (start <= T < end).

    Accepts optional JSON body via query is not used; evaluation uses server UTC now.
    When CONNECTOME_DATABASE_URL is set, candidate windows are read from recent
    observations' details.contract_timeline when present. Otherwise returns
    NO_OPEN_CONTRACT with an explicit reason (producer gap / no candidates).
    """
    from flask import request
    now = datetime.now(timezone.utc)
    # Optional override for deterministic tests only via header (not documented publicly)
    override = request.headers.get("X-Evaluation-Time")
    if override:
        parsed = parse_aware_timestamp(override)
        if parsed:
            now = parsed

    candidates = []
    url = os.getenv("CONNECTOME_DATABASE_URL")
    if url:
        try:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(url, connect_timeout=4, row_factory=dict_row) as conn:
                exists = conn.execute(
                    "SELECT to_regclass('public.biological_reservoir_observations') AS obs"
                ).fetchone()
                if exists and exists["obs"]:
                    rows = conn.execute("""
                        SELECT DISTINCT ON (market_slug)
                            market_slug,
                            details->'contract_timeline'->'current_contract' AS current_contract,
                            details->>'contract_timeframe' AS timeframe,
                            captured_at
                        FROM biological_reservoir_observations
                        WHERE market_slug IS NOT NULL
                          AND COALESCE(details->>'fixture_key','')=''
                          AND COALESCE(details->>'is_synthetic','false') <> 'true'
                        ORDER BY market_slug, captured_at DESC
                        LIMIT 50
                    """).fetchall()
                    for row in rows:
                        cc = row.get("current_contract") or {}
                        if not isinstance(cc, dict):
                            cc = {}
                        candidates.append({
                            "identity": row["market_slug"],
                            "market_slug": row["market_slug"],
                            "start_at": cc.get("start_at") or cc.get("start") or cc.get("window_start"),
                            "end_at": cc.get("end_at") or cc.get("end") or cc.get("window_end"),
                            "timeframe": row.get("timeframe") or cc.get("timeframe"),
                            "question": cc.get("question"),
                            "source": "observation_contract_timeline",
                        })
        except Exception as exc:
            logging.exception("current-contract candidate load failed")
            return jsonify({
                "ok": False,
                "status": "ERROR",
                "message": type(exc).__name__ + ": " + str(exc),
                "contract": None,
            }), 500

    result = select_open_contract(candidates, now)
    result["ok"] = result["status"] in ("OPEN", "NO_OPEN_CONTRACT")
    result["research_only"] = True
    result["live_trading_enabled"] = False
    result["candidate_count"] = len(candidates)
    return jsonify(result)


@app.get("/api/active-alert")
def active_alert():
    """
    Active UP/DOWN alert for the exact open contract only.

    Never carries a prior contract's alert forward. Returns explicit
    NO_ACTIVE_ALERT when none is eligible.
    """
    from flask import request
    now = datetime.now(timezone.utc)
    override = request.headers.get("X-Evaluation-Time")
    if override:
        parsed = parse_aware_timestamp(override)
        if parsed:
            now = parsed

    # Resolve open contract first
    contract_resp = current_contract().get_json()
    contract = (contract_resp or {}).get("contract")
    if not contract or contract_resp.get("status") != "OPEN":
        return jsonify({
            "ok": True,
            "status": "NO_ACTIVE_ALERT",
            "message": "No active UP/DOWN alert.",
            "reason": "no_open_contract",
            "alert": None,
            "contract": contract,
            "graph_annotations": [],
            "research_only": True,
            "live_trading_enabled": False,
        })

    identity = contract["identity"]
    records = []
    url = os.getenv("CONNECTOME_DATABASE_URL")
    if url:
        try:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(url, connect_timeout=4, row_factory=dict_row) as conn:
                rows = conn.execute("""
                    SELECT snapshot_id, market_slug, captured_at, checkpoint,
                           forecast_direction, probability_up,
                           details->>'issued_at' AS issued_at
                    FROM biological_reservoir_observations
                    WHERE market_slug = %s
                      AND forecast_direction IN ('UP', 'DOWN')
                      AND COALESCE(details->>'fixture_key','')=''
                      AND COALESCE(details->>'is_synthetic','false') <> 'true'
                    ORDER BY captured_at DESC, snapshot_id DESC
                    LIMIT 50
                """, (identity,)).fetchall()
                for row in rows:
                    records.append({
                        "market_slug": row["market_slug"],
                        "direction": row["forecast_direction"],
                        "forecast_direction": row["forecast_direction"],
                        "captured_at": row["captured_at"],
                        "issued_at": row.get("issued_at"),
                        "snapshot_id": row["snapshot_id"],
                        "checkpoint": row.get("checkpoint"),
                        "probability_up": row.get("probability_up"),
                    })
        except Exception as exc:
            logging.exception("active-alert load failed")
            return jsonify({
                "ok": False,
                "status": "ERROR",
                "message": type(exc).__name__ + ": " + str(exc),
                "alert": None,
                "graph_annotations": [],
            }), 500

    selected = select_active_up_down_alert(
        records,
        identity,
        now,
        contract_start=contract.get("start_at"),
        contract_end=contract.get("end_at"),
    )
    annotations = alerts_to_graph_annotations(
        [selected["alert"]] if selected.get("alert") else []
    )
    return jsonify({
        "ok": True,
        "research_only": True,
        "live_trading_enabled": False,
        "contract": contract,
        "graph_annotations": annotations,
        "issuance_note": (
            "Active alerts require ISSUANCE_SEMANTICS_TRUSTED and issued_at. Records with only "
            "captured_at are not eligible alerts or graph annotations; they may "
            "appear as alert_issuance_unverified observations. details.issued_at "
            "is a proposed producer field until verified against worker code."
        ),
        "contract_metadata_contract": {
            "verified_observation_fields": [
                "snapshot_id", "market_slug", "captured_at", "checkpoint",
                "forecast_direction", "probability_up", "outcome", "brier_score",
                "details.contract_timeframe", "details.outcome_verified",
                "details.settlement_source", "details.settled_at",
                "details.contract_timeline.current_contract.reference_price (read by main telemetry)",
            ],
            "proposed_or_unverified_fields": [
                "details.issued_at",
                "details.contract_timeline.current_contract.start_at",
                "details.contract_timeline.current_contract.end_at",
                "alert_sequence / issuance_sequence",
            ],
            "required_for_active_alert": [
                "exact contract identity", "UP or DOWN direction", "issued_at",
                "timezone-aware exact 15-minute contract start_at/end_at",
                "ISSUANCE_SEMANTICS_TRUSTED=true after producer verification",
            ],
            "ordering_trust": (
                "ALERT_SEQUENCE_ORDERING_TRUSTED=true is separately required before "
                "sequence values can resolve conflicting equal-time directions; default false."
            ),
            "missing_boundaries_behavior": "UNAVAILABLE; no guessed contract or issuance window",
        },
        **selected,
    })


@app.get("/api/rolling-accuracy")
def rolling_accuracy():
    """
    Rolling 24h UP/DOWN accuracy account. Always returns policy-pending values
    until an explicit approval flag is set in process environment.

    Owner approval required: set RESERVOIR_SCORING_POLICY_APPROVED=true only after
    explicit scoring-policy and release approval. Default is disabled.
    """
    from flask import request
    now = datetime.now(timezone.utc)
    override = request.headers.get("X-Evaluation-Time")
    if override:
        parsed = parse_aware_timestamp(override)
        if parsed:
            now = parsed

    approved = os.getenv("RESERVOIR_SCORING_POLICY_APPROVED", "").strip().lower() == "true"

    records = []
    url = os.getenv("CONNECTOME_DATABASE_URL")
    if url and approved:
        # Only load scoring inputs when approved; still safe if not configured
        try:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(url, connect_timeout=4, row_factory=dict_row) as conn:
                rows = conn.execute("""
                    SELECT snapshot_id, market_slug, captured_at, forecast_direction,
                           outcome,
                           details->>'outcome_verified' AS outcome_verified,
                           details->>'settled_at' AS settled_at,
                           details->>'issued_at' AS issued_at,
                           details->'contract_timeline'->'current_contract'->>'start_at' AS contract_start,
                           details->'contract_timeline'->'current_contract'->>'end_at' AS contract_end
                    FROM biological_reservoir_observations
                    WHERE market_slug IS NOT NULL
                      AND COALESCE(details->>'fixture_key','')=''
                      AND COALESCE(details->>'is_synthetic','false') <> 'true'
                      AND captured_at > (NOW() AT TIME ZONE 'utc') - INTERVAL '48 hours'
                    ORDER BY captured_at ASC
                    LIMIT 5000
                """).fetchall()
                for row in rows:
                    records.append(dict(row))
        except Exception as exc:
            logging.exception("rolling-accuracy load failed")
            return jsonify({
                "ok": False,
                "status": "ERROR",
                "message": type(exc).__name__ + ": " + str(exc),
            }), 500

    result = compute_rolling_accuracy(records, now, policy_approved=approved)
    result["ok"] = True
    result["research_only"] = True
    result["live_trading_enabled"] = False
    result["policy_approved_env"] = approved
    return jsonify(result)


@app.get("/health")
def health():
    return jsonify({"ok": True, "live_trading": False})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
