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
<title>Polymarket Arbitrage Research · Connectomes</title>
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
<header><div><h1>Polymarket Arbitrage Research</h1><p class="subtitle">Two independent Connectomes · paper trading only · live execution hard-blocked</p></div><span class="pill"><span class="dot"></span> PAPER MODE</span></header>
<div id="error" role="alert"></div>
<section class="section">
 <div class="section-head"><h2>Performance overview</h2><span class="updated" id="updated">Waiting for status…</span></div>
 <div class="cards">
  <article class="card"><div class="metric-label">Paper balance</div><div class="metric" id="balance">—</div><div class="metric-sub">Simulation only</div></article>
  <article class="card"><div class="metric-label">Realized profit / loss</div><div class="metric" id="profit">—</div><div class="metric-sub" id="todayProfit">Settled trades only</div></article>
  <article class="card"><div class="metric-label">Settled trades</div><div class="metric" id="tradesCount">—</div><div class="metric-sub" id="winRate">Win rate: —</div></article>
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
 <div class="section-head"><h2>Connectome learning graphs</h2><span class="small" id="connectomeSummary">Learning from settled paper outcomes only</span></div>
 <div class="grid-two">
  <article class="card"><h2>Decision Connectome</h2><div class="metric-label">Active nodes / capacity</div><div class="metric" id="decisionNodes">—</div><div class="metric-label" style="margin-top:12px">Active edges / capacity</div><div class="metric" id="decisionEdges">—</div><div class="metric-label" style="margin-top:12px">Settled observations · win rate</div><div id="decisionLearning" style="font-weight:700">—</div><div class="metric-label" style="margin-top:12px">Checkpoint comparison</div><div id="decisionCheckpoints" class="small">Awaiting settled contracts</div><div class="metric-label" style="margin-top:10px">Best supported checkpoint</div><div id="decisionBestCheckpoint" style="font-weight:700">Not enough samples</div></article>
  <article class="card"><h2>Research Connectome</h2><div class="metric-label">Active nodes / capacity</div><div class="metric" id="researchNodes">—</div><div class="metric-label" style="margin-top:12px">Active edges / capacity</div><div class="metric" id="researchEdges">—</div><div class="metric-label" style="margin-top:12px">Settled observations · win rate</div><div id="researchLearning" style="font-weight:700">—</div><div class="metric-label" style="margin-top:12px">Checkpoint comparison</div><div id="researchCheckpoints" class="small">Awaiting settled contracts</div><div class="metric-label" style="margin-top:10px">Best supported checkpoint</div><div id="researchBestCheckpoint" style="font-weight:700">Not enough samples</div></article>
 </div>
 <p class="small">Each graph supports up to 1,000,000 nodes and 1,000,000 edges. Capacity is a ceiling, not a pre-created graph: active nodes and edges grow with evidence. Learning labels come only from final paper settlements.</p>
</section>
<section class="section">
 <div class="section-head"><h2>Market data</h2><span class="small">Latest observed exchange prices</span></div>
 <div class="feed">
  <div class="feed-item"><div class="feed-name">Binance</div><div class="feed-price" id="binance">—</div><div class="small" id="bcSpread">vs Coinbase: —</div></div>
  <div class="feed-item"><div class="feed-name">Coinbase</div><div class="feed-price" id="coinbase">—</div><div class="small" id="ckSpread">vs Kraken: —</div></div>
  <div class="feed-item"><div class="feed-name">Kraken</div><div class="feed-price" id="kraken">—</div><div class="small" id="bkSpread">vs Binance: —</div></div>
 </div>
</section>
<section class="section panel"><div class="panel-inner section-head"><h2>Recent paper trades</h2><span class="small" id="tradeSummary">0 recorded</span></div>
 <div class="table-wrap"><table><thead><tr><th>Trade</th><th>Action</th><th>Direction</th><th>Stake</th><th>Status</th><th>P/L</th><th>Signal score</th></tr></thead><tbody id="tradeRows"><tr><td class="empty" colspan="7">No paper trades recorded yet.</td></tr></tbody></table></div>
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
 const d=graphs&&graphs.decision||{},r=graphs&&graphs.research||{};
 put("decisionNodes",fmt(d.nodes_active)+" / "+fmt(d.node_capacity));put("decisionEdges",fmt(d.edges_active)+" / "+fmt(d.edge_capacity));
 put("decisionLearning",fmt(d.settled_observations)+" settled · "+rate(d));
 put("researchNodes",fmt(r.nodes_active)+" / "+fmt(r.node_capacity));put("researchEdges",fmt(r.edges_active)+" / "+fmt(r.edge_capacity));
 put("researchLearning",fmt(r.settled_observations)+" settled · "+rate(r));
 const checkpointLine=g=>Object.entries(g.checkpoint_performance||{}).filter(([k,v])=>["first_seen","10m","5m","1m"].includes(k)).map(([k,v])=>k+": "+fmt(v.settled)+" settled, "+(num(v.win_rate)===null?"—":pct(v.win_rate))).join(" · ")||"Awaiting settled contracts";
 put("decisionCheckpoints",checkpointLine(d));put("researchCheckpoints",checkpointLine(r));
 put("decisionBestCheckpoint",d.recommended_checkpoint||"Not enough samples (20 per checkpoint)");
 put("researchBestCheckpoint",r.recommended_checkpoint||"Not enough samples (20 per checkpoint)");
 put("connectomeSummary","Checkpoint accuracy measured against verified closed-contract outcomes");
}
function paintTrades(trades){
 const tbody=el("tradeRows");tbody.replaceChildren();put("tradeSummary",trades.length+" recorded");
 if(!trades.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=7;td.className="empty";td.textContent="No paper trades recorded yet.";tr.appendChild(td);tbody.appendChild(tr);return}
 trades.forEach((t,i)=>{const tr=document.createElement("tr"),vals=[t.id??(i+1),t.action??"—",t.direction??"—",money(t.amount_usd??t.amount),t.status??"—",money(t.profit_loss_usd??t.profit_loss),num(t.confidence)===null?"—":(num(t.confidence)<=1?pct(t.confidence):num(t.confidence).toFixed(1)+"%")];vals.forEach((v,j)=>{const td=document.createElement("td");td.textContent=String(v);if(j===4){const b=document.createElement("span");b.className="badge "+(/settled|completed|closed|won|success/i.test(String(v))?"good":/fail|error|lost/i.test(String(v))?"bad":"warn");b.textContent=String(v);td.replaceChildren(b)}tr.appendChild(td)});tbody.appendChild(tr)})
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
async function refresh(){
 try{
  const response=await fetch("/api/status?ts="+Date.now(),{cache:"no-store"});if(!response.ok)throw new Error("Status endpoint returned HTTP "+response.status);
  const d=await response.json(),s=d.stats||{},p=d.performance||{},prices=d.latest_prices||{},sp=d.price_spreads||{};
  el("error").style.display="none";put("balance",money(p.current_balance));put("profit",money(p.total_profit??s.total_profit));
  put("todayProfit","Settled P/L only");put("tradesCount",num(p.total_trades??s.trades_executed)??0);
  put("winRate","Win rate: "+(num(p.win_rate)===null?"—":(num(p.win_rate)>1?num(p.win_rate).toFixed(1)+"%":pct(p.win_rate))));
  put("opportunities",num(s.opportunities_detected)??0);put("scanCount",num(d.scan_count)??0);put("uptime","Uptime: "+duration(s.uptime));
  window._lastEquityCurve=Array.isArray(d.equity_curve)?d.equity_curve:[];drawProfitCurve(window._lastEquityCurve);paintConnectomes(d.connectomes||{});
  put("mode",String(d.mode??"paper").toUpperCase());put("avgProfit",money(p.avg_profit_per_trade));put("bestTrade",money(p.best_trade));put("worstTrade",money(p.worst_trade));
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
