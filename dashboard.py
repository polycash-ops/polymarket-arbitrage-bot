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
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#101722">
<title>Polymarket Arbitrage Bot · Paper Dashboard</title>
<style>
:root{color-scheme:dark;--bg:#0b111a;--panel:#141e2b;--panel2:#101925;--line:#273649;--text:#edf3fa;--muted:#9aabc0;--green:#54d6a0;--red:#ff8585;--amber:#ffd078;--blue:#84baff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#17283a 0,#0b111a 55%);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:clamp(16px,4vw,34px)}header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px}
h1{font-size:clamp(1.5rem,4vw,2.2rem);line-height:1.15;margin:0 0 8px;letter-spacing:-.03em}h2{font-size:1.05rem;margin:0 0 16px}.subtitle{color:var(--muted);margin:0}.pill{display:inline-flex;align-items:center;gap:8px;border:1px solid #24664e;background:#123327;color:#a8f0cf;border-radius:999px;padding:7px 12px;font-size:.83rem;font-weight:700;white-space:nowrap}.dot{width:7px;height:7px;border-radius:50%;background:var(--green)}
.section{margin-top:22px}.section-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}.section-head h2{margin:0}.updated{font-size:.8rem;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.card{min-width:0;background:linear-gradient(145deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 8px 24px #00000018}.metric-label{color:var(--muted);font-size:.82rem;margin-bottom:8px}.metric{font-size:clamp(1.25rem,3vw,1.8rem);font-weight:750;letter-spacing:-.035em;overflow-wrap:anywhere}.metric-sub{font-size:.8rem;color:var(--muted);margin-top:5px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden}.panel-inner{padding:18px}.statusline{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.badge{border-radius:8px;padding:4px 8px;font-size:.78rem;font-weight:750;background:#263449;color:#dce8f8}.badge.good{background:#123327;color:#a8f0cf}.badge.warn{background:#392d17;color:var(--amber)}.badge.bad{background:#3a2026;color:#ffb4b4}
.grid-two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:480px}th,td{text-align:left;padding:12px 16px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.06em;font-weight:700;background:#111a26}tbody tr:last-child td{border-bottom:0}.empty{text-align:center;color:var(--muted);padding:24px 16px}.feed{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.feed-item{background:#101925;border:1px solid var(--line);border-radius:12px;padding:14px;min-width:0}.feed-name{color:var(--muted);font-size:.82rem}.feed-price{font-size:1.2rem;font-weight:750;margin-top:4px}.small{color:var(--muted);font-size:.83rem}#error{display:none;margin:12px 0;background:#3a2026;border:1px solid #71404a;color:#ffd6d6;border-radius:12px;padding:12px}.foot{color:var(--muted);font-size:.8rem;margin:22px 2px 0}
@media(max-width:800px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.grid-two{grid-template-columns:1fr}}
@media(max-width:440px){main{padding:14px}.card{padding:14px}.feed{grid-template-columns:1fr}.metric{font-size:1.45rem}.pill{font-size:.76rem}}
</style>
</head>
<body><main>
<header>
  <div><h1>Polymarket Arbitrage Bot</h1><p class="subtitle">Forked strategy · paper trading only · live execution hard-blocked</p></div>
  <span class="pill"><span class="dot"></span> PAPER MODE</span>
</header>
<div id="error" role="alert"></div>
<section class="section">
  <div class="section-head"><h2>Performance overview</h2><span class="updated" id="updated">Waiting for status…</span></div>
  <div class="cards">
    <article class="card"><div class="metric-label">Paper balance</div><div class="metric" id="balance">—</div><div class="metric-sub">Simulation only</div></article>
    <article class="card"><div class="metric-label">Total profit / loss</div><div class="metric" id="profit">—</div><div class="metric-sub" id="todayProfit">Today: —</div></article>
    <article class="card"><div class="metric-label">Completed trades</div><div class="metric" id="tradesCount">—</div><div class="metric-sub" id="winRate">Win rate: —</div></article>
    <article class="card"><div class="metric-label">Opportunities detected</div><div class="metric" id="opportunities">—</div><div class="metric-sub" id="uptime">Uptime: —</div></article>
  </div>
</section>
<section class="section panel"><div class="panel-inner">
  <div class="section-head"><h2>Bot status</h2><div class="statusline"><span id="runningBadge" class="badge">Checking…</span><span id="liveBadge" class="badge good">LIVE TRADING BLOCKED</span></div></div>
  <div class="grid-two">
    <div><div class="metric-label">Mode</div><div id="mode" style="font-weight:700">—</div></div>
    <div><div class="metric-label">Average profit per trade</div><div id="avgProfit" style="font-weight:700">—</div></div>
    <div><div class="metric-label">Best trade</div><div id="bestTrade" style="font-weight:700">—</div></div>
    <div><div class="metric-label">Worst trade</div><div id="worstTrade" style="font-weight:700">—</div></div>
  </div>
</div></section>
<section class="section">
  <div class="section-head"><h2>Market data</h2><span class="small">Latest reported exchange prices</span></div>
  <div class="feed">
    <div class="feed-item"><div class="feed-name">Binance</div><div class="feed-price" id="binance">—</div><div class="small" id="bcSpread">vs Coinbase: —</div></div>
    <div class="feed-item"><div class="feed-name">Coinbase</div><div class="feed-price" id="coinbase">—</div><div class="small" id="ckSpread">vs Kraken: —</div></div>
    <div class="feed-item"><div class="feed-name">Kraken</div><div class="feed-price" id="kraken">—</div><div class="small" id="bkSpread">vs Binance: —</div></div>
  </div>
</section>
<section class="section panel">
  <div class="panel-inner section-head"><h2>Recent paper trades</h2><span class="small" id="tradeSummary">0 recorded</span></div>
  <div class="table-wrap"><table><thead><tr><th>Trade</th><th>Action</th><th>Direction</th><th>Amount</th><th>Status</th><th>P/L</th><th>Confidence</th></tr></thead><tbody id="tradeRows"><tr><td class="empty" colspan="7">No paper trades recorded yet.</td></tr></tbody></table></div>
</section>
<p class="foot">This dashboard reports the forked strategy's paper simulation. Market spreads are observations, not guaranteed executable arbitrage profits. Live execution remains disabled.</p>
</main>
<script>
const el=id=>document.getElementById(id);
const num=v=>typeof v==='number'&&Number.isFinite(v)?v:(v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))?Number(v):null);
const money=v=>{const n=num(v);return n===null?'—':(n<0?'−':'')+'$'+Math.abs(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})};
const pct=v=>{const n=num(v);return n===null?'—':(n*100).toFixed(2)+'%'};
const price=v=>{const n=num(v);return n===null?'—':'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})};
const duration=v=>{const n=Math.max(0,Math.floor(num(v)||0));const h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;return h?h+'h '+m+'m':m?m+'m '+s+'s':s+'s'};
function put(id,value){el(id).textContent=value}
function paintTrades(trades){
 const tbody=el('tradeRows');tbody.replaceChildren();put('tradeSummary',trades.length+' recorded');
 if(!trades.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=7;td.className='empty';td.textContent='No paper trades recorded yet.';tr.appendChild(td);tbody.appendChild(tr);return}
 trades.forEach((t,i)=>{const tr=document.createElement('tr');const vals=[t.id??(i+1),t.action??'—',t.direction??'—',money(t.amount_usd??t.amount),t.status??'—',money(t.profit_loss_usd??t.profit_loss),num(t.confidence)===null?'—':(num(t.confidence)<=1?pct(t.confidence):num(t.confidence).toFixed(1)+'%')];vals.forEach((v,j)=>{const td=document.createElement('td');td.textContent=String(v);if(j===4){const b=document.createElement('span');b.className='badge '+(/completed|closed|won|success/i.test(String(v))?'good':/fail|error|lost/i.test(String(v))?'bad':'warn');b.textContent=String(v);td.replaceChildren(b)}tr.appendChild(td)});tbody.appendChild(tr)})
}
async function refresh(){
 try{
  const response=await fetch('/api/status?ts='+Date.now(),{cache:'no-store'});if(!response.ok)throw new Error('Status endpoint returned HTTP '+response.status);
  const d=await response.json(),s=d.stats||{},p=d.performance||{},prices=d.latest_prices||{},sp=d.price_spreads||{};
  el('error').style.display='none';
  put('balance',money(p.current_balance));put('profit',money(p.total_profit??s.total_profit));put('todayProfit','Today: '+money(p.profit_today));
  put('tradesCount',num(p.total_trades??s.trades_executed)??0);put('winRate','Win rate: '+(num(p.win_rate)===null?'—':(num(p.win_rate)>1?num(p.win_rate).toFixed(1)+'%':pct(p.win_rate))));
  put('opportunities',num(s.opportunities_detected)??0);put('uptime','Uptime: '+duration(s.uptime));
  put('mode',String(d.mode??'paper').toUpperCase());put('avgProfit',money(p.avg_profit_per_trade));put('bestTrade',money(p.best_trade));put('worstTrade',money(p.worst_trade));
  put('binance',price(prices.binance));put('coinbase',price(prices.coinbase));put('kraken',price(prices.kraken));
  put('bcSpread', 'vs Coinbase: '+pct(sp['binance-coinbase']));put('ckSpread','vs Kraken: '+pct(sp['coinbase-kraken']));put('bkSpread','vs Binance: '+pct(sp['binance-kraken']));
  const running=!!d.bot_running;put('runningBadge',running?'BOT RUNNING':'BOT STOPPED');el('runningBadge').className='badge '+(running?'good':'bad');
  put('updated','Updated '+new Date().toLocaleTimeString());
  paintTrades(Array.isArray(d.recent_trades)?d.recent_trades:[]);
  if(d.bot_error){el('error').textContent='Bot error: '+d.bot_error;el('error').style.display='block'}
 }catch(e){el('error').textContent='Unable to refresh dashboard data: '+String(e);el('error').style.display='block';put('updated','Refresh failed')}
}
refresh();setInterval(refresh,5000);
</script></body></html>"""


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
             "direction": getattr(t.opportunity, "direction", None), "exchange_moved": getattr(t.opportunity, "exchange_moved", None),
             "market_id": t.market_id, "market_question": getattr(t.opportunity, "market_question", None),
             "entry_price": t.executed_price, "shares": t.shares, "resolved": t.resolved, "notes": t.notes}
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
