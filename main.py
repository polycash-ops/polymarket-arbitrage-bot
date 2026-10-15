"""Connectome-driven Polymarket arbitrage research bot. Paper-only by design."""
import argparse
import asyncio
import logging
import time
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Dict

import yaml

from bot.connectome import Connectome
from bot.market_monitor import MarketMonitor
from bot.opportunity_detector import Opportunity, OpportunityDetector
from bot.trade_executor import Trade, TradeExecutor

Path("logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/trading_bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, config_path: str = "config.example.yaml", paper_trading: bool = True):
        if not paper_trading:
            raise RuntimeError("Live trading is hard-blocked in this repository; paper mode only.")
        self.config = self._load_config(config_path)
        self.paper_trading = True
        self.market_monitor = MarketMonitor(self.config.get("market_monitor", {}))
        self.opportunity_detector = OpportunityDetector(self.config.get("opportunity_detection", {}))
        self.trade_executor = TradeExecutor(self.config.get("trade_execution", {}), paper_trading=True)
        graph_config = self.config.get("connectomes", {})
        self.decision_connectome = Connectome("decision", graph_config.get("decision", {}))
        self.research_connectome = Connectome("research", graph_config.get("research", {}))
        self.scan_checkpoints_seen = {}
        self.stats = {
            "start_time": time.time(),
            "opportunities_detected": 0,
            "trades_executed": 0,
            "total_profit": 0.0,
            "uptime": 0,
        }
        self._setup_callbacks()
        logger.info("Connectome bot initialized; mode=PAPER; live_trading=false")

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                config = yaml.safe_load(handle) or {}
            logger.info("Configuration loaded from %s", config_path)
            return config
        except FileNotFoundError:
            logger.warning("Config %s not found; using safe defaults", config_path)
            return self._default_config()
        except Exception:
            logger.exception("Could not load config; using safe defaults")
            return self._default_config()

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "market_monitor": {"exchanges": ["binance", "coinbase", "kraken"], "update_interval": 0.1},
            "opportunity_detection": {
                "min_price_difference": 0.03,
                "min_confidence": 0.7,
                "max_delay_seconds": 15,
                "min_probability_lag": 0.01,
                "max_probability_followthrough": 0.01,
                "min_consensus_exchanges": 2,
            },
            "trade_execution": {
                "max_position_size": 100,
                "min_position_size": 5,
                "risk_per_trade": 0.02,
                "max_daily_trades": 50,
                "min_confidence": 0.7,
            },
            "connectomes": {
                "decision": {
                    "max_nodes": 1_000_000, "max_edges": 1_000_000,
                    "min_samples_for_gate": 20, "min_learned_probability": 0.50,
                    "learning_rate": 0.03,
                },
                "research": {
                    "max_nodes": 1_000_000, "max_edges": 1_000_000,
                    "min_samples_for_gate": 20, "learning_rate": 0.03,
                },
            },
        }

    def _setup_callbacks(self):
        self.market_monitor.add_callback(self.opportunity_detector.on_price_update)
        self.market_monitor.add_callback(self._on_market_scan)
        self.market_monitor.add_settlement_callback(self._on_contract_settled)
        self.opportunity_detector.add_callback(self._on_opportunity_detected)
        self.trade_executor.add_callback(self._on_trade_executed)

    async def _on_market_scan(self, exchange, point):
        if exchange != "polymarket" or not point.market_id or not point.end_time:
            return
        now = float(point.timestamp)
        remaining = max(0.0, float(point.end_time) - now)
        market_id = str(point.market_id)
        seen = self.scan_checkpoints_seen.setdefault(market_id, set())
        checkpoints = []
        first_seen_now = "first_seen" not in seen
        if first_seen_now:
            checkpoints.append("first_seen")
            seen.add("first_seen")
            # A horizon already passed at discovery is recorded as missed, not
            # falsely represented as an observation from that time.
            for label, seconds in (("10m", 600), ("5m", 300), ("3m", 180), ("1m", 60)):
                if remaining <= seconds:
                    seen.add(label)
        else:
            for label, seconds in (("10m", 600), ("5m", 300), ("3m", 180), ("1m", 60)):
                if label not in seen and remaining <= seconds:
                    checkpoints.append(label)
        if not checkpoints:
            return
        move, exchanges = self.opportunity_detector._consensus_move()
        polymarket_history = self.opportunity_detector.price_history.get("polymarket")
        odds_change = float(polymarket_history.get_probability_change(10) or 0.0) if polymarket_history else 0.0
        prediction_source = "btc_consensus" if move is not None and len(exchanges) >= 2 else "market_midpoint"
        if move is not None and abs(move) >= 0.001:
            direction = "up" if move > 0 else "down"
        else:
            direction = "up" if float(point.price) >= 0.5 else "down"
        move_abs = abs(float(move or 0.0))
        midpoint = float(point.price)
        odds_history = self.opportunity_detector.price_history.get("polymarket")
        odds_change = odds_history.get_probability_change(10) if odds_history else 0.0
        prediction_source = "btc_consensus" if move is not None and abs(move) >= 0.001 else "market_implied"
        confidence = min(0.99, max(0.01,
            0.50 + min(move_abs / 0.20, 1.0) * 0.20
            + min(abs(midpoint - 0.5) / 0.5, 1.0) * 0.20
            + (0.10 if len(exchanges) >= 2 else 0.0)))
        quote_midpoint = (float(point.bid) + float(point.ask)) / 2.0 if point.bid is not None and point.ask is not None and 0 < point.bid <= point.ask < 1 else float(point.price)
        midpoint = quote_midpoint
        for checkpoint in checkpoints:
            seen.add(checkpoint)
            snapshot = SimpleNamespace(
                timestamp=now, market_id=market_id, checkpoint=checkpoint,
                time_remaining=remaining, minutes_remaining=remaining / 60.0,
                midpoint=midpoint, market_up_probability=midpoint, depth_imbalance=None,
                market_probability_change=float(odds_change or 0.0),
                btc_consensus_move=float(move or 0.0), agreeing_exchange_count=len(exchanges),
                prediction_source=prediction_source,
                exchange_moved=",".join(exchanges) if exchanges else "none",
                agreeing_exchange_count=len(exchanges),
                prediction_source="btc_consensus" if move is not None and len(exchanges) >= 2 else "market_midpoint",
                market_probability_change=(self.opportunity_detector.price_history.get("polymarket").get_probability_change(10)
                    if self.opportunity_detector.price_history.get("polymarket") else 0.0),
                polymarket_delay=max(0.0, now - self.opportunity_detector.last_polymarket_change),
                price_difference=move_abs, confidence=confidence, direction=direction,
                recommended_action="buy_yes" if direction == "up" else "buy_no",
                yes_bid=point.bid, yes_ask=point.ask, market_question=point.question,
                market_end_time=point.end_time, expected_profit=0.0,
                connectome_event_id=f"scan:{market_id}:{checkpoint}",
            )
            d = self.decision_connectome.predict(snapshot, role="decision")
            r = self.research_connectome.predict(snapshot, role="research")
            self.decision_connectome.record_scan_observation(snapshot, role="decision", forecast_probability=d["probability"])
            self.research_connectome.record_scan_observation(snapshot, role="research", forecast_probability=r["probability"])
            logger.info(
                "CONNECTOME_SCAN market=%s checkpoint=%s remaining=%.1fs midpoint=%.4f "
                "btc_move_pct=%.4f direction=%s raw_score=%.3f decision_p=%.3f "
                "decision_samples=%d research_p=%.3f research_samples=%d",
                market_id, checkpoint, remaining, midpoint, move_abs, direction, confidence,
                d["probability"], d["samples"], r["probability"], r["samples"],
            )

    async def _on_contract_settled(self, market_id: str, actual_up: bool):
        d_count = self.decision_connectome.settle_market(market_id, actual_up)
        r_count = self.research_connectome.settle_market(market_id, actual_up)
        self.scan_checkpoints_seen.pop(market_id, None)
        logger.info(
            "CONNECTOME_MARKET_LABEL market=%s actual_up=%s decision_labels=%d research_labels=%d",
            market_id, actual_up, d_count, r_count,
        )

    async def _on_opportunity_detected(self, opportunity: Opportunity):
        self.stats["opportunities_detected"] += 1
        remaining = max(0.0, float(opportunity.market_end_time or time.time()) - time.time())
        opportunity.time_remaining = remaining
        opportunity.minutes_remaining = remaining / 60.0
        opportunity.checkpoint = (
            "first_seen" if remaining > 600 else
            "10m" if remaining > 300 else
            "5m" if remaining > 180 else
            "3m" if remaining > 60 else "1m"
        )
        if opportunity.yes_bid is not None and opportunity.yes_ask is not None:
            opportunity.midpoint = (float(opportunity.yes_bid) + float(opportunity.yes_ask)) / 2.0
        else:
            opportunity.midpoint = 0.5
        opportunity.depth_imbalance = None
        odds_history = self.opportunity_detector.price_history.get("polymarket")
        opportunity.market_probability_change = odds_history.get_probability_change(10) if odds_history else 0.0
        consensus_move, agreeing_exchanges = self.opportunity_detector._consensus_move()
        opportunity.btc_consensus_move = float(consensus_move or 0.0)
        opportunity.agreeing_exchange_count = len(agreeing_exchanges)
        opportunity.prediction_source = "btc_consensus"
        logger.info(
            "OPPORTUNITY market=%s direction=%s move=%.4f%% detector_confidence=%.3f",
            opportunity.market_id, opportunity.direction, opportunity.price_difference, opportunity.confidence,
        )
        decision = self.decision_connectome.predict(opportunity, role="decision")
        research = self.research_connectome.predict(opportunity, role="research")
        logger.info(
            "CONNECTOME_SIGNAL decision_probability=%.3f decision_samples=%d "
            "research_probability=%.3f research_samples=%d",
            decision["probability"], decision["samples"], research["probability"], research["samples"],
        )
        settings = self.config.get("connectomes", {}).get("decision", {})
        learned_floor = float(settings.get("min_learned_probability", 0.50))
        minimum = float(self.config.get("opportunity_detection", {}).get("min_confidence", 0.7))
        if decision["ready_for_gate"]:
            opportunity.confidence = 0.5 * float(opportunity.confidence) + 0.5 * float(decision["probability"])
            if decision["probability"] < learned_floor:
                logger.info(
                    "Paper signal rejected by decision Connectome: %.3f < %.3f",
                    decision["probability"], learned_floor,
                )
                return
        if opportunity.confidence < minimum:
            logger.info("Paper signal rejected: confidence %.3f < %.3f", opportunity.confidence, minimum)
            return

        # The executor uses only the observed Polymarket quote for a simulated fill.
        trade = await self.trade_executor.execute_opportunity(opportunity)
        if not trade:
            return
        logger.info(
            "PAPER_POSITION_OPEN id=%s market=%s entry=%.4f stake=$%.2f; settlement pending",
            trade.id, trade.market_id, trade.executed_price or trade.expected_price, trade.amount,
        )

    async def _on_trade_executed(self, trade: Trade):
        if trade.executed_at is not None and not trade.resolved:
            self.stats["trades_executed"] += 1
        if trade.resolved and trade.profit_loss is not None:
            self.stats["total_profit"] = self.trade_executor.stats.total_profit
        pnl = f"${trade.profit_loss:.2f}" if trade.resolved and trade.profit_loss is not None else "unsettled"
        logger.info(
            "PAPER_TRADE_UPDATE id=%s status=%s pnl=%s realized_total=$%.2f",
            trade.id, trade.status.value, pnl, self.stats["total_profit"],
        )

    async def start(self):
        logger.info("Starting Connectome paper research bot")
        try:
            await asyncio.gather(
                self.market_monitor.start(),
                self.trade_executor.start(),
                self._status_loop(),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Fatal bot error")
        finally:
            await self.stop()

    async def stop(self):
        await asyncio.gather(self.market_monitor.stop(), self.trade_executor.stop(), return_exceptions=True)
        logger.info("Connectome bot stopped")

    async def _status_loop(self):
        while True:
            await asyncio.sleep(300)
            self.stats["uptime"] = time.time() - self.stats["start_time"]
            performance = self.trade_executor.get_performance_report()
            logger.info(
                "STATUS uptime_hours=%.1f opportunities=%d trades=%d realized_pnl=$%.2f win_rate=%.1f%%",
                self.stats["uptime"] / 3600,
                self.stats["opportunities_detected"],
                self.stats["trades_executed"],
                self.stats["total_profit"],
                100 * float(performance.get("win_rate", 0.0) or 0.0),
            )

    def get_status(self) -> Dict[str, Any]:
        performance = self.trade_executor.get_performance_report()
        latest_prices = self.market_monitor.get_latest_prices()
        return {
            "uptime_hours": (time.time() - self.stats["start_time"]) / 3600,
            "mode": "paper",
            "live_trading": False,
            "stats": self.stats,
            "performance": performance,
            "latest_prices": {exchange: point.price for exchange, point in latest_prices.items()},
            "price_spreads": self.market_monitor.get_price_spread(),
            "connectomes": {
                "decision": self.decision_connectome.stats(),
                "research": self.research_connectome.stats(),
            },
            "recent_opportunities": len(self.opportunity_detector.get_recent_opportunities(60)),
        }


async def main():
    parser = argparse.ArgumentParser(description="Connectome Polymarket Arbitrage Research Bot")
    parser.add_argument("--config", default="config.example.yaml")
    parser.add_argument("--paper-trading", action="store_true")
    parser.add_argument("--live-trading", action="store_true")
    args = parser.parse_args()
    if args.live_trading:
        logger.error("LIVE TRADING IS HARD-BLOCKED IN THIS REPOSITORY. Use paper mode only.")
        return
    bot = TradingBot(args.config, paper_trading=True)
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
