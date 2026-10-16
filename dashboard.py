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
    _ensure_bot()
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#101722">
<title>BTC Polymarket Connectome Trend Research</title>
<style>
:root{color-scheme:dark;--bg:#0b111a;--panel:#141e2b;--panel2:#101925;--line:#273649;--text:#edf3fa;--muted:#9aabc0;--green:#54d6a0;--red:#ff8585;--amber:#ffd078;--blue:#84baff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#17283a 0,#0b111a 55%);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1120px;margin:0 auto;padding:clamp(14px,4vw,34px)}header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px}
h1{font-size:clamp(1.5rem,4vw,2.2rem);line-height:1.15;margin:0 0 8px;letter-spacing:-.03em}h2{font-size:1.05rem;margin:0 0 14px}.subtitle{color:var(--muted);margin:0}.pill{display:inline-flex;align-items:center;gap:8px;border:1px solid #24664e;background:#123327;color:#a8f0cf;border-radius:999px;padding:7px 12px;font-size:.83rem;font-weight:700;white-space:nowrap}.dot{width:7px;height:7px;border-radius:50%;background:var(--green)}
.section{margin-top:22px}.section-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}.section-head h2{margin:0}.updated,.small{font-size:.82rem;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.card{min-width:0;background:linear-gradient(145deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 8px 24px #00000018}.metric-label{color:var(--muted);font-size:.82rem;margin-bottom:6px}.metric{font-size:clamp(1.2rem,3vw,1.75rem);font-weight:750;letter-spacing:-.035em;overflow-wrap:anywhere}.metric-sub{font-size:.8rem;color:var(--muted);margin-top:5px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden}.panel-inner{padding:18px}.statusline{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.badge{border-radius:8px;padding:4px 8px;font-size:.78rem;font-weight:750;background:#263449;color:#dce8f8}.badge.good{background:#123327;color:#a8f0cf}.badge.warn{background:#392d17;color:var(--amber)}.badge.bad{background:#3a2026;color:#ffb4b4}
.grid-two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:600px}th,td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.06em;font-weight:700;background:#111a26}tbody tr:last-child td{border-bottom:0}.empty{text-align:center;color:var(--muted);padding:24px 16px}.feed{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.feed-item{background:#101925;border:1px solid var(--line);border-radius:12px;padding:14px;min-width:0}.feed-name{color:var(--muted);font-size:.82rem}.feed-price{font-size:1.2rem;font-weight:750;margin-top:4px}#error{display:none;margin:12px 0;background:#3a2026;border:1px solid #71404a;color:#ffd6d6;border-radius:12px;padding:12px}.foot{color:var(--muted);font-size:.8rem;margin:22px 2px 0}
@media(max-width:850px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.grid-two{grid-template-columns:1fr}}
@media(max-width:440px){main{padding:12px}.card{padding:13px}.feed{grid-template-columns:1fr}.metric{font-size:1.4rem}.pill{font-size:.76rem}}
</style>
</head>
<body><main>
<header><div><h1>BTC Polymarket Connectome Trend Research</h1><p class="subtitle">Three independent Connectomes · 5-second quote snapshots · 15m and hourly directional forecasting · trade execution disabled</p></div><span class="pill"><span class="dot"></span> FORECAST-ONLY MODE</span></header>
<div id="error" role="alert"></div>
<section class="section">
 <div class="section-head"><h2>Performance overview</h2><span class="updated" id="updated">Waiting for status…</span></div>
 <div class="cards">
  <article class="card"><div class="metric-label">Trade execution</div><div class="metric" id="balance">—</div><div class="metric-sub">Simulation only</div></article>
  <article class="card"><div class="metric-label">Trading P/L</div><div class="metric" id="profit">—</div><div class="metric-sub" id="todayProfit">Settled trades only</div></article>
  <article class="card"><div class="metric-label">Trades</div><div class="metric" id="tradesCount">—</div><div class="metric-sub" id="winRate">Win rate: —</div></article>
  <article class="card"><div class="metric-label">Opportunities detected</div><div class="metric" id="opportunities">—</div><div class="metric-sub" id="uptime">Uptime: —</div></article>
  <article class="card"><div class="metric-label">Polymarket scans</div><div class="metric" id="scanCount">—</div><div class="metric-sub">Completed scan cycles</div></article>
 </div>
</section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Paper equity curve</h2><span class="small" id="curveSummary">Settled trades only</span></div>
 <canvas id="profitChart" height="220" style="display:block;width:100%;height:220px" aria-label="Cumulative paper balance after settled trades"></canvas>
 <p class="small">Open positions and unsettled results are excluded. The curve reflects the current process's in-memory paper-trade history.</p>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Bot status</h2><div class="statusline"><span id="runningBadge" class="badge">Checking…</span><span class="badge good">LIVE TRADING BLOCKED</span></div></div>
 <div class="grid-two">
  <div><div class="metric-label">Mode</div><div id="mode" style="font-weight:700">—</div></div>
  <div><div class="metric-label">Average profit per settled trade</div><div id="avgProfit" style="font-weight:700">—</div></div>
  <div><div class="metric-label">Best settled trade</div><div id="bestTrade" style="font-weight:700">—</div></div>
  <div><div class="metric-label">Worst settled trade</div><div id="worstTrade" style="font-weight:700">—</div></div>
 </div>
</div></section>
<section class="section">
 <div class="section-head"><h2>Connectome learning graphs</h2><span class="small" id="connectomeSummary">Learning from settled forecast outcomes only</span></div>
 <div class="grid-two">
  <article class="card"><h2>Decision Connectome</h2><div class="metric-label">Snapshot forecast accuracy · settled snapshots</div><div class="metric" id="decisionAccuracy">—</div><div class="small" id="decisionAccuracyDetail">Awaiting verified settlements</div><div class="metric-label" style="margin-top:12px">Up-probability Brier score</div><div id="decisionBrier" style="font-weight:700">—</div><div class="metric-label" style="margin-top:12px">Active nodes / capacity</div><div class="metric" id="decisionNodes">—</div><div class="metric-label" style="margin-top:12px">Active edges / capacity</div><div class="metric" id="decisionEdges">—</div><div class="small" id="decisionActivity">Awaiting first snapshots</div><div class="metric-label" style="margin-top:12px">Checkpoint coverage & scoring</div><div class="table-wrap"><table><thead><tr><th>Checkpoint</th><th>Observed</th><th>Pending</th><th>Settled</th><th>Accuracy</th><th>Model Brier</th><th>Market Brier</th></tr></thead><tbody id="decisionCheckpoints"><tr><td colspan="7" class="empty">No observations yet</td></tr></tbody></table></div><div class="metric-label" style="margin-top:10px">Best supported checkpoint</div><div id="decisionBestCheckpoint" style="font-weight:700">Not enough samples</div></article>
  <article class="card"><h2>Research Connectome</h2><div class="metric-label">Snapshot forecast accuracy · settled snapshots</div><div class="metric" id="researchAccuracy">—</div><div class="small" id="researchAccuracyDetail">Awaiting verified settlements</div><div class="metric-label" style="margin-top:12px">Up-probability Brier score</div><div id="researchBrier" style="font-weight:700">—</div><div class="metric-label" style="margin-top:12px">Active nodes / capacity</div><div class="metric" id="researchNodes">—</div><div class="metric-label" style="margin-top:12px">Active edges / capacity</div><div class="metric" id="researchEdges">—</div><div class="small" id="researchActivity">Awaiting first snapshots</div><div class="metric-label" style="margin-top:12px">Checkpoint coverage & scoring</div><div class="table-wrap"><table><thead><tr><th>Checkpoint</th><th>Observed</th><th>Pending</th><th>Settled</th><th>Accuracy</th><th>Model Brier</th><th>Market Brier</th></tr></thead><tbody id="researchCheckpoints"><tr><td colspan="7" class="empty">No observations yet</td></tr></tbody></table></div><div class="metric-label" style="margin-top:10px">Best supported checkpoint</div><div id="researchBestCheckpoint" style="font-weight:700">Not enough samples</div></article>
 </div>
 <p class="small">Each graph supports up to 1,000,000 nodes and 1,000,000 edges. Every valid quote refresh is recorded by all three Connectomes; node visits and graph connections update on that snapshot. Forecast accuracy and edge-weight training change only after the exact contract has an authoritative verified settlement. Pending snapshots are never counted as wins. The ≥98% figure is a target to evaluate, not a guaranteed result.</p>
</section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Walk-forward training evidence</h2><span class="small" id="trainingSummary">Waiting for persisted training runs…</span></div>
 <p class="small">Each run uses chronologically ordered, officially settled observations. Validation predictions can only use labels whose settlement timestamp precedes the validation snapshot. A candidate is marked accepted only when its validation Brier score beats the market-midpoint baseline; accepted status is evaluation evidence, not a promise of future profitability.</p>
 <div class="table-wrap"><table><thead><tr><th>Graph</th><th>Saved runs</th><th>Latest run (UTC)</th><th>Validation samples</th><th>Market baseline Brier</th><th>Candidate Brier</th><th>Changed edges</th><th>Result</th></tr></thead><tbody id="trainingRows"><tr><td colspan="8" class="empty">Waiting for persisted training runs</td></tr></tbody></table></div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Independent Live-Trading Readiness Model</h2><span class="small" id="readinessSummary">Waiting for saved readiness audits…</span></div>
 <p class="small">A separate auditor evaluates each Connectome against the requested targets. Forecast win rate is not a trading win rate. Daily/monthly returns, drawdown, and trades/day require an authoritative realized-trade ledger; they are not inferred from quote simulations. This report never enables live trading.</p>
 <div class="table-wrap"><table><thead><tr><th>Connectome</th><th>Overall readiness</th><th>Settled contracts</th><th>Forecast win rate</th><th>Forecast Brier</th><th>Market Brier</th><th>Daily return target 3.2%</th><th>Monthly return target 140%</th><th>Max drawdown under 5%</th><th>Trades/day target 240</th><th>Candidate applied</th></tr></thead><tbody id="readinessRows"><tr><td colspan="11" class="empty">Waiting for readiness reports</td></tr></tbody></table></div>
 <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>Connectome</th><th>Readiness check</th><th>Status</th><th>Actual evidence</th><th>Required target / note</th></tr></thead><tbody id="readinessGateRows"><tr><td colspan="5" class="empty">Waiting for readiness gates</td></tr></tbody></table></div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Entry timing experiment · contract-aligned</h2><span class="small" id="entryTimingSummary">Waiting for settled contracts…</span></div>
 <p class="small">Each contract contributes at most one snapshot per timing bucket. Returns estimate buying UP at the observed ask or DOWN at 1 − UP bid, then settling to $1/$0. These are quote-based research estimates—not verified fills—and exclude fees, slippage and latency. “Best” is provisional until tested on a later chronological holdout.</p>
 <div class="table-wrap"><table><thead><tr><th>Connectome</th><th>Entry timing</th><th>Contracts</th><th>Directional accuracy</th><th>Up-probability Brier</th><th>Priced entries</th><th>Mean return / $1</th><th>Profitable entries</th></tr></thead><tbody id="entryTimingRows"><tr><td colspan="8" class="empty">Waiting for settled contract snapshots</td></tr></tbody></table></div>
</div></section>
<section class="section panel"><div class="panel-inner">
 <div class="section-head"><h2>Overlapping Trend Analysis Connectome</h2><span class="small">Independent graph · 1,000,000-node capacity · 5-second snapshot cadence</span></div>
 <div class="grid-two">
  <div><div class="metric-label">Analysis graph nodes / capacity</div><div class="metric" id="analysisNodes">—</div><div class="metric-label">Edges / 1M capacity</div><div id="analysisEdges" style="font-weight:700">—</div><div class="metric-label">Nodes touched in last 15 minutes</div><div id="analysisRecentNodes" style="font-weight:700">—</div><div class="metric-label">Edges touched in last 15 minutes</div><div id="analysisRecentEdges" style="font-weight:700">—</div><div class="metric-label">New nodes / new edges in last 15 minutes</div><div id="analysisNewGraph" style="font-weight:700">—</div></div>
  <div><div class="metric-label">Recorded snapshots</div><div class="metric" id="analysisObservations">—</div><div class="metric-label">Snapshots in last 15 minutes / last snapshot age</div><div id="analysisRecentSnapshots" style="font-weight:700">—</div><div class="metric-label">Node visits / edge traversals</div><div id="analysisTraversals" style="font-weight:700">—</div><div class="metric-label">Verified settlements / forecast accuracy (target ≥98%)</div><div id="analysisSettled" style="font-weight:700">Awaiting verified settlements</div><div class="metric-label">Model Brier vs market midpoint Brier</div><div id="analysisBrier" style="font-weight:700">—</div><div class="metric-label">Edges updated by verified outcomes</div><div id="analysisLearnedEdges" style="font-weight:700">—</div></div>
 </div>
 <p class="small">The analysis graph scores directional forecasts against each contract's verified close. It samples quote changes on the dashboard's 5-second refresh cadence and keeps 15-minute and hourly contracts separate by market ID and end timestamp. Depth comes from the Polymarket CLOB top-five order-book levels when the book endpoint responds; unavailable readings remain explicitly marked, never inferred from quotes.</p>
 <div class="table-wrap"><table><thead><tr><th>Contract horizon</th><th>Market / close</th><th>Bid</th><th>Ask</th><th>Midpoint</th><th>Midpoint Δ / refresh</th><th>Depth imbalance</th><th>Bid depth</th><th>Ask depth</th><th>Analysis P(Up)</th><th>Trend</th><th>Time to close</th></tr></thead><tbody id="polymarketQuoteRows"><tr><td colspan="12" class="empty">Waiting for Polymarket quotes</td></tr></tbody></table></div>
</div></section>
<section class="section">
 <div class="section-head"><h2>Market data</h2><span class="small">Latest observed exchange prices</span></div>
 <div class="feed">
  <div class="feed-item"><div class="feed-name">Binance</div><div class="feed-price" id="binance">—</div><div class="small" id="bcSpread">vs Coinbase: —</div></div>
  <div class="feed-item"><div class="feed-name">Coinbase</div><div class="feed-price" id="coinbase">—</div><div class="small" id="ckSpread">vs Kraken: —</div></div>
  <div class="feed-item"><div class="feed-name">Kraken</div><div class="feed-price" id="kraken">—</div><div class="small" id="bkSpread">vs Binance: —</div></div>
 </div>
</section>
<section class="section panel"><div class="panel-inner section-head"><h2>Recent paper trades</h2><span class="small" id="tradeSummary">0 recorded</span></div>
 <div class="table-wrap"><table><thead><tr><th>Trade</th><th>Timestamp (ET)</th><th>Action</th><th>Direction</th><th>Stake</th><th>Execution status</th><th>Result</th><th>P/L</th><th>Signal score</th></tr></thead><tbody id="tradeRows"><tr><td class="empty" colspan="7">No paper trades recorded yet.</td></tr></tbody></table></div>
</section>
<p class="foot">Observed quotes are not guaranteed executable prices. This dashboard is research and paper simulation only; live order execution remains hard-blocked.</p>
</main>
<script>
const el=id=>document.getElementById(id);
const num=v=>typeof v==="number"&&Number.isFinite(v)?v:(v!==null&&v!==undefined&&v!==""&&Number.isFinite(Number(v))?Number(v):null);
const money=v=>{const n=num(v);return n===null?"—":(n<0?"−":"")+"$"+Math.abs(n).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})};
const pct=v=>{const n=num(v);return n===null?"—":(n*100).toFixed(2)+"%"};
const price=v=>{const n=num(v);return n===null?"—":"$"+n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})};
const duration=v=>{const n=Math.max(0,Math.floor(num(v)||0)),h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;return h?h+"h "+m+"m":m?m+"m "+s+"s":s+"s"};
function put(id,value){const node=el(id);if(node)node.textContent=value}
function paintConnectomes(graphs){
 const fmt=n=>num(n)===null?"—":Math.trunc(num(n)).toLocaleString("en-US");
 const rate=g=>num(g&&g.win_rate)===null?"Not yet measured":pct(g.win_rate);
 const d=graphs&&graphs.decision||{},r=graphs&&graphs.research||{},a=graphs&&graphs.analysis||{};
 put("analysisNodes",fmt(a.nodes_active)+" / "+fmt(a.node_capacity));
 put("analysisEdges",fmt(a.edges_active)+" / "+fmt(a.edge_capacity));
 put("analysisObservations",fmt(a.observations));
 put("analysisRecentSnapshots",fmt(a.observations_last_15m)+" / "+(num(a.last_observation_age_seconds)===null?"no snapshot":duration(a.last_observation_age_seconds)+" ago"));
 put("analysisRecentNodes",fmt(a.nodes_touched_last_15m));
 put("analysisRecentEdges",fmt(a.edges_touched_last_15m));
 put("analysisNewGraph",fmt(a.new_nodes_last_15m)+" new nodes · "+fmt(a.new_edges_last_15m)+" new edges");
 put("analysisTraversals",fmt(a.total_node_visits)+" visits · "+fmt(a.total_edge_traversals)+" edge traversals");
 put("analysisLearnedEdges",fmt(a.learned_edge_updates)+" verified-outcome edge updates");
 put("analysisSettled",fmt(a.settled_observations)+" settled · "+rate(a)+" · target ≥98% (not guaranteed)");
 put("analysisBrier",(num(a.brier_score)===null?"—":Number(a.brier_score).toFixed(3))+" vs "+(num(a.market_baseline_brier)===null?"—":Number(a.market_baseline_brier).toFixed(3)));
 put("decisionAccuracy",rate(d));put("decisionAccuracyDetail",fmt(d.settled_observations)+" settled · "+fmt(Math.max(0,(num(d.observations)||0)-(num(d.settled_observations)||0)))+" pending");
 put("decisionBrier",num(d.brier_score)===null?"Awaiting verified settlements":Number(d.brier_score).toFixed(3)+" vs market "+(num(d.market_baseline_brier)===null?"—":Number(d.market_baseline_brier).toFixed(3)));
 put("decisionNodes",fmt(d.nodes_active)+" / "+fmt(d.node_capacity));put("decisionEdges",fmt(d.edges_active)+" / "+fmt(d.edge_capacity));
 put("decisionActivity",fmt(d.observations_last_15m)+" snapshots/15m · "+fmt(d.nodes_touched_last_15m)+" nodes touched · "+fmt(d.edges_touched_last_15m)+" edges touched · "+fmt(d.new_nodes_last_15m)+" new nodes / "+fmt(d.new_edges_last_15m)+" new edges · "+fmt(d.learned_edge_updates)+" verified weight updates");
 put("researchAccuracy",rate(r));put("researchAccuracyDetail",fmt(r.settled_observations)+" settled · "+fmt(Math.max(0,(num(r.observations)||0)-(num(r.settled_observations)||0)))+" pending");
 put("researchBrier",num(r.brier_score)===null?"Awaiting verified settlements":Number(r.brier_score).toFixed(3)+" vs market "+(num(r.market_baseline_brier)===null?"—":Number(r.market_baseline_brier).toFixed(3)));
 put("researchNodes",fmt(r.nodes_active)+" / "+fmt(r.node_capacity));put("researchEdges",fmt(r.edges_active)+" / "+fmt(r.edge_capacity));
 put("researchActivity",fmt(r.observations_last_15m)+" snapshots/15m · "+fmt(r.nodes_touched_last_15m)+" nodes touched · "+fmt(r.edges_touched_last_15m)+" edges touched · "+fmt(r.new_nodes_last_15m)+" new nodes / "+fmt(r.new_edges_last_15m)+" new edges · "+fmt(r.learned_edge_updates)+" verified weight updates");
 const paintCheckpointTable=(id,g)=>{
  const body=el(id);if(!body)return;body.replaceChildren();
  const labels=["first_seen","10m","5m","3m","1m","continuous"],data=g.checkpoint_performance||{};
  labels.forEach(label=>{
   const v=data[label]||{},tr=document.createElement("tr");
   const cells=[label,fmt(v.observations??0),fmt(v.pending??0),fmt(v.settled??0),
    num(v.win_rate)===null?"—":pct(v.win_rate),
    num(v.brier_score)===null?"—":Number(v.brier_score).toFixed(3),
    num(v.market_baseline_brier)===null?"—":Number(v.market_baseline_brier).toFixed(3)];
   cells.forEach((value,index)=>{const td=document.createElement("td");td.textContent=String(value);if(index===0)td.style.fontWeight="700";tr.appendChild(td)});
   body.appendChild(tr);
  });
 };
 paintCheckpointTable("decisionCheckpoints",d);paintCheckpointTable("researchCheckpoints",r);
 put("decisionBestCheckpoint",d.recommended_checkpoint||"Awaiting settled snapshots");
 put("researchBestCheckpoint",r.recommended_checkpoint||"Awaiting settled snapshots");
 const trainingBody=el("trainingRows");
 if(trainingBody){
  trainingBody.replaceChildren();
  const names=[["decision","Decision"],["research","Research"],["analysis","Analysis"]];
  let runs=0;
  names.forEach(([key,label])=>{
   const g=graphs&&graphs[key]||{},t=g.training||{},v=t.latest||{};
   runs+=num(t.run_count)||0;
   const tr=document.createElement("tr");
   const values=[label,fmt(t.run_count||0),v.started_at?new Date(v.started_at).toLocaleString("en-US",{timeZone:"UTC"}):"No run",
    fmt(v.details&&v.details.validation_samples||0),
    num(v.baseline_brier)===null?"—":Number(v.baseline_brier).toFixed(4),
    num(v.candidate_brier)===null?"—":Number(v.candidate_brier).toFixed(4),
    fmt(v.changed_edges||0),
    v.accepted===true?"ACCEPTED":v.accepted===false?"REJECTED":"Awaiting run"];
   values.forEach((value,index)=>{const td=document.createElement("td");td.textContent=String(value);if(index===0||index===7)td.style.fontWeight="700";tr.appendChild(td)});
   trainingBody.appendChild(tr);
  });
  put("trainingSummary",runs+" saved walk-forward runs across three graphs");
 }
 const readinessBody=el("readinessRows"),gateBody=el("readinessGateRows");
  const readinessNames=[["decision","Decision"],["research","Research"],["analysis","Analysis"]];
  let readyReports=0,gateCount=0;
  if(readinessBody&&gateBody){
   readinessBody.replaceChildren();gateBody.replaceChildren();
   const statusText=(v)=>String(v??"NOT_MEASURABLE").replaceAll("_"," ");
   const statusCell=(v)=>{const td=document.createElement("td");td.textContent=statusText(v);td.style.fontWeight="700";if(v==="PASS")td.style.color="#54d6a0";else if(v==="FAIL"||v==="NOT_READY"||v==="BLOCKED")td.style.color="#ff8585";else td.style.color="#ffd078";return td};
   readinessNames.forEach(([key,label])=>{
    const g=graphs&&graphs[key]||{},report=g.readiness||{},e=report.evidence||{},checks=report.checks||{},trade=report.trade_metrics||{};
    if(report.generated_at)readyReports++;
    const tr=document.createElement("tr");
    const vals=[label,statusText(report.overall_status||"REPORT UNAVAILABLE"),fmt(e.settled_contracts||0),
      pct(e.contract_forecast_win_rate),num(e.contract_forecast_brier)===null?"—":Number(e.contract_forecast_brier).toFixed(4),
      num(e.market_baseline_brier)===null?"—":Number(e.market_baseline_brier).toFixed(4),
      trade.daily_return===null||trade.daily_return===undefined?"NOT MEASURABLE":pct(trade.daily_return),
      trade.monthly_return===null||trade.monthly_return===undefined?"NOT MEASURABLE":pct(trade.monthly_return),
      trade.max_drawdown===null||trade.max_drawdown===undefined?"NOT MEASURABLE":pct(trade.max_drawdown),
      trade.trades_per_day===null||trade.trades_per_day===undefined?"NOT MEASURABLE":fmt(trade.trades_per_day),
      checks.candidate_model_actively_applied&&checks.candidate_model_actively_applied.actual===true?"YES":"NO"];
    vals.forEach((value,i)=>{const td=document.createElement("td");td.textContent=String(value);if(i===1)td.style.fontWeight="700";tr.appendChild(td)});
    readinessBody.appendChild(tr);
    Object.entries(checks).forEach(([check,v])=>{
     gateCount++;const row=document.createElement("tr");
     const actual=(v.actual===null||v.actual===undefined)?"Not recorded":
       (typeof v.actual==="number"&&check.toLowerCase().includes("rate")?pct(v.actual):
       (typeof v.actual==="number"&&check.toLowerCase().includes("brier")?Number(v.actual).toFixed(4):String(v.actual)));
     const target=v.target!==undefined?pct(v.target):v.required!==undefined?String(v.required):v.target_exclusive_max!==undefined?"< "+pct(v.target_exclusive_max):(v.note||"See report");
     [label,check.replaceAll("_"," "),statusCell(v.status),actual,target].forEach((value,i)=>{if(i===2)row.appendChild(value);else{const td=document.createElement("td");td.textContent=String(value);row.appendChild(td)}});
     gateBody.appendChild(row);
    });
   });
   if(!readyReports){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=11;td.className="empty";td.textContent="No persisted readiness report available yet.";tr.appendChild(td);readinessBody.appendChild(tr)}
   if(!gateCount){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=5;td.className="empty";td.textContent="No readiness checks available.";tr.appendChild(td);gateBody.appendChild(tr)}
   put("readinessSummary",readyReports+" saved readiness reports · "+(readinessNames.length-readyReports)+" unavailable · live trading remains disabled");
  }
  const entryBody=el("entryTimingRows");
 if(entryBody){
  entryBody.replaceChildren();
  const names=[["decision","Decision"],["research","Research"],["analysis","Analysis"]];
  let rowCount=0,settledContracts=0;
  names.forEach(([key,label])=>{
   const timing=((graphs&&graphs[key]||{}).entry_timing)||{};
   settledContracts=Math.max(settledContracts,num(timing.settled_contracts)||0);
   const buckets=Array.isArray(timing.buckets)?timing.buckets:[];
   buckets.forEach(v=>{
    rowCount++;
    const tr=document.createElement("tr");
    const isBest=timing.best_entry_bucket===v.bucket&&v.eligible;
    const ret=num(v.mean_return_per_dollar);
    const vals=[label+(isBest?" · provisional best":""),v.bucket,fmt(v.contracts),pct(v.accuracy),
      num(v.brier)===null?"—":Number(v.brier).toFixed(4),fmt(v.priced_entries),
      ret===null?"—":(ret>=0?"+":"")+(ret*100).toFixed(2)+"%",
      num(v.positive_return_rate)===null?"—":pct(v.positive_return_rate)];
    vals.forEach((value,index)=>{const td=document.createElement("td");td.textContent=String(value);if(index===0)td.style.fontWeight="700";tr.appendChild(td)});
    entryBody.appendChild(tr);
   });
  });
  if(!rowCount){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=8;td.className="empty";td.textContent="No settled entry-timing samples yet.";tr.appendChild(td);entryBody.appendChild(tr)}
  put("entryTimingSummary",settledContracts+" settled contracts per graph · timing rankings require at least 5 contracts per bucket");
 }
 put("connectomeSummary","Checkpoint exploration shows recorded, pending, and settled snapshots separately. Accuracy uses settled snapshots only; internal reference trades are not shown");
}
function tradeTimestamp(t){
 const raw=num(t.executed_at??t.timestamp??t.created_at);
 if(raw===null)return "—";
 const date=new Date(raw<1e12?raw*1000:raw);
 if(!Number.isFinite(date.getTime()))return "—";
 return date.toLocaleString("en-US",{timeZone:"America/New_York",month:"2-digit",day:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:true});
}
function tradeResult(t){
 const status=String(t.status??"").toLowerCase();
 if(status==="failed"||status==="cancelled")return "FAILURE";
 if(t.resolved===true||status==="settled"){
  const pnl=num(t.profit_loss_usd??t.profit_loss);
  if(pnl===null)return "SETTLED";
  return pnl>0.000001?"SUCCESS":pnl< -0.000001?"FAILURE":"BREAK-EVEN";
 }
 return "PENDING";
}
function paintTrades(trades){
 const tbody=el("tradeRows");tbody.replaceChildren();put("tradeSummary",trades.length+" recorded · updates every 5 seconds");
 if(!trades.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=9;td.className="empty";td.textContent="No paper trades recorded yet.";tr.appendChild(td);tbody.appendChild(tr);return}
 trades.forEach((t,i)=>{
  const tr=document.createElement("tr"),result=tradeResult(t);
  const vals=[t.id??(i+1),tradeTimestamp(t),t.action??"—",t.direction??"—",money(t.amount_usd??t.amount),String(t.status??"—").toUpperCase(),result,money(t.profit_loss_usd??t.profit_loss),num(t.confidence)===null?"—":(num(t.confidence)<=1?pct(t.confidence):num(t.confidence).toFixed(1)+"%")];
  vals.forEach((v,j)=>{
   const td=document.createElement("td");td.textContent=String(v);
   if(j===5||j===6){const b=document.createElement("span");b.className="badge "+(j===6?(result==="SUCCESS"?"good":result==="FAILURE"?"bad":"warn"):(/settled/i.test(String(v))?"good":/failed|cancelled/i.test(String(v))?"bad":/executed/i.test(String(v))?"warn":"warn"));b.textContent=String(v);td.replaceChildren(b)}
   tr.appendChild(td)
  });tbody.appendChild(tr)
 })
}
function drawProfitCurve(points){
 const canvas=el("profitChart");if(!canvas)return;
 const width=Math.max(300,canvas.clientWidth||600),height=220,dpr=window.devicePixelRatio||1;
 canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
 const ctx=canvas.getContext("2d");ctx.scale(dpr,dpr);ctx.clearRect(0,0,width,height);
 const pad={l:62,r:14,t:14,b:30},plotW=width-pad.l-pad.r,plotH=height-pad.t-pad.b;
 const vals=points.map(p=>num(p.balance)).filter(v=>v!==null);
 if(!vals.length){ctx.fillStyle="#9aabc0";ctx.font="13px system-ui";ctx.fillText("Waiting for settled paper trades…",pad.l,height/2);put("curveSummary","No settled trades yet");return}
 let lo=Math.min(...vals),hi=Math.max(...vals);if(lo===hi){lo-=1;hi+=1}const extra=(hi-lo)*0.12;lo-=extra;hi+=extra;
 ctx.strokeStyle="#273649";ctx.fillStyle="#9aabc0";ctx.font="11px system-ui";ctx.lineWidth=1;
 for(let i=0;i<4;i++){const y=pad.t+plotH*i/3;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(width-pad.r,y);ctx.stroke();const v=hi-(hi-lo)*i/3;ctx.fillText("$"+Math.round(v).toLocaleString("en-US"),4,y+4)}
 const xy=points.map((p,i)=>({x:pad.l+(points.length===1?0.5:i/(points.length-1))*plotW,y:pad.t+(hi-num(p.balance))/(hi-lo)*plotH}));
 ctx.strokeStyle="#54d6a0";ctx.lineWidth=2.5;ctx.beginPath();xy.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.stroke();
 const last=points[points.length-1];put("curveSummary",Math.max(0,points.length-1)+" settled trades · latest balance "+money(last.balance)+" · realized P/L "+money(last.profit));
 ctx.fillStyle="#9aabc0";ctx.fillText(points[0].label||"Start",pad.l,height-7);const endLabel=points[points.length-1].label||"Latest";ctx.fillText(endLabel,Math.max(pad.l,width-pad.r-ctx.measureText(endLabel).width),height-7);
}
function paintPolymarketQuotes(quotes,forecasts){
 const body=el("polymarketQuoteRows");if(!body)return;body.replaceChildren();
 const horizons=[["15m","polymarket"],["1h","polymarket_1h"]];
 horizons.forEach(([label,key])=>{
  const q=quotes[key],f=forecasts[label],tr=document.createElement("tr");
  const close=q&&num(q.end_time)!==null?new Date(num(q.end_time)*1000).toLocaleString("en-US",{timeZone:"America/New_York",month:"2-digit",day:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:true}):"—";
  const remaining=q?duration(q.remaining_seconds):"—";
  const forecastMatches=!!(q&&f&&f.market_id===q.market_id);
  const vals=[label,q?(String(q.market_id||"—")+" · "+close):"Not currently detected",
   q?pct(q.bid):"—",q?pct(q.ask):"—",q?pct(q.midpoint):"—",
   q&&q.refresh_changes&&num(q.refresh_changes.midpoint_change_refresh)!==null?pct(q.refresh_changes.midpoint_change_refresh):"—",
   q&&num(q.depth_imbalance)!==null?pct(q.depth_imbalance):"Unavailable",
   q&&num(q.bid_depth)!==null?Number(q.bid_depth).toFixed(2):"—",
   q&&num(q.ask_depth)!==null?Number(q.ask_depth).toFixed(2):"—",
   forecastMatches?pct(f.analysis_up_probability):"—",
   forecastMatches?String(f.analysis_direction):"Awaiting snapshot",remaining];
  vals.forEach(v=>{const td=document.createElement("td");td.textContent=String(v);tr.appendChild(td)});body.appendChild(tr);
 });
}
async function refresh(){
 try{
  const response=await fetch("/api/status?ts="+Date.now(),{cache:"no-store"});if(!response.ok)throw new Error("Status endpoint returned HTTP "+response.status);
  const d=await response.json(),s=d.stats||{},p=d.performance||{},prices=d.latest_prices||{},sp=d.price_spreads||{};
  paintPolymarketQuotes(d.latest_polymarket_quotes||{},d.latest_analysis_forecasts||{});
  el("error").style.display="none";put("balance","DISABLED");put("profit","—");
  put("todayProfit","Settled P/L only");put("tradesCount","DISABLED");
  put("winRate","Forecast-only phase · no positions opened");
  put("opportunities",num(s.opportunities_detected)??0);put("scanCount",num(d.scan_count)??0);put("uptime","Uptime: "+duration(s.uptime));
  window._lastEquityCurve=Array.isArray(d.equity_curve)?d.equity_curve:[];drawProfitCurve(window._lastEquityCurve);paintConnectomes(d.connectomes||{});
  put("mode",String(d.mode??"paper").toUpperCase());put("avgProfit","Disabled");put("bestTrade","Disabled");put("worstTrade","Disabled");
  put("binance",price(prices.binance));put("coinbase",price(prices.coinbase));put("kraken",price(prices.kraken));
  put("bcSpread","vs Coinbase: "+pct(sp["binance-coinbase"]));put("ckSpread","vs Kraken: "+pct(sp["coinbase-kraken"]));put("bkSpread","vs Binance: "+pct(sp["binance-kraken"]));
  const running=!!d.bot_running;put("runningBadge",running?"BOT RUNNING":"BOT STOPPED");el("runningBadge").className="badge "+(running?"good":"bad");
  put("updated","Updated "+new Date().toLocaleTimeString());paintTrades(Array.isArray(d.recent_trades)?d.recent_trades:[]);
  if(d.bot_error){el("error").textContent="Bot error: "+d.bot_error;el("error").style.display="block"}
 }catch(e){el("error").textContent="Unable to refresh dashboard data: "+String(e);el("error").style.display="block";put("updated","Refresh failed")}
}
window.addEventListener("resize",()=>{if(window._lastEquityCurve)drawProfitCurve(window._lastEquityCurve)});
refresh();setInterval(refresh,5000);
</script></body></html>"""


@app.get("/health")
def health():
    return jsonify({"ok": True, "live_trading": False})


@app.get("/api/status")
def status():
    _ensure_bot()
    if bot is None:
        return jsonify({
            "mode": "paper", "live_trading": False, "bot_running": False,
            "bot_error": bot_error, "recent_trades": [], "connectomes": {},
            "scan_count": 0,
        })
    try:
        data = bot.get_status()
        data["bot_running"] = any(t.name == "forked-paper-bot" and t.is_alive() for t in threading.enumerate())
        data["bot_error"] = bot_error
        data["live_trading"] = False
        data["scan_count"] = int(getattr(bot.market_monitor, "scan_count", 0))
        settled = sorted(
            (t for t in bot.trade_executor.trades if t.resolved and t.profit_loss is not None),
            key=lambda t: (t.executed_at or t.opportunity.timestamp),
        )
        cumulative = 0.0
        equity_curve = [{"label": "Start", "balance": 10000.0, "profit": 0.0}]
        for trade in settled:
            cumulative += float(trade.profit_loss)
            equity_curve.append({
                "label": datetime.fromtimestamp(trade.executed_at or trade.opportunity.timestamp).strftime("%m/%d %H:%M"),
                "balance": 10000.0 + cumulative,
                "profit": cumulative,
            })
        data["equity_curve"] = equity_curve
        data["recent_trades"] = [
            {
                "id": t.id, "action": t.action, "amount_usd": t.amount, "status": t.status.value,
                "profit_loss_usd": t.profit_loss, "confidence": getattr(t.opportunity, "confidence", None),
                "direction": getattr(t.opportunity, "direction", None), "exchange_moved": getattr(t.opportunity, "exchange_moved", None),
                "market_id": t.market_id, "market_question": getattr(t.opportunity, "market_question", None),
                "executed_at": t.executed_at, "timestamp": t.executed_at or getattr(t.opportunity, "timestamp", None),
                "entry_price": t.executed_price, "shares": t.shares, "resolved": t.resolved, "notes": t.notes,
            }
            for t in bot.trade_executor.get_recent_trades(20)
        ]
        return jsonify(data)
    except Exception as exc:
        logging.exception("Status endpoint failed")
        return jsonify({
            "mode": "paper", "live_trading": False, "bot_running": False,
            "bot_error": str(exc), "recent_trades": [], "connectomes": {},
        }), 500


if __name__ == "__main__":
    _ensure_bot()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
