"""Connectome-driven Polymarket arbitrage research bot. Paper-only by design."""
import argparse
import asyncio
import logging
import time
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
        self.opportunity_detector.add_callback(self._on_opportunity_detected)
        self.trade_executor.add_callback(self._on_trade_executed)

    async def _on_opportunity_detected(self, opportunity: Opportunity):
        self.stats["opportunities_detected"] += 1
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
        event_id = self.decision_connectome.record_signal(opportunity, role="decision")
        opportunity.connectome_event_id = event_id
        self.research_connectome.record_signal(opportunity, role="research")
        logger.info(
            "PAPER_POSITION_OPEN id=%s market=%s entry=%.4f stake=$%.2f; settlement pending",
            trade.id, trade.market_id, trade.executed_price or trade.expected_price, trade.amount,
        )

    async def _on_trade_executed(self, trade: Trade):
        if trade.executed_at is not None and not trade.resolved:
            self.stats["trades_executed"] += 1
        if trade.resolved and trade.profit_loss is not None:
            self.stats["total_profit"] = self.trade_executor.stats.total_profit
            event_id = getattr(trade.opportunity, "connectome_event_id", None)
            if event_id:
                # Final binary settlement only; never train from an open/pending trade.
                won = float(trade.profit_loss) > 0.0
                self.decision_connectome.settle(event_id, won)
                self.research_connectome.settle(event_id, won)
                logger.info(
                    "CONNECTOME_SETTLED event=%s won=%s decision=%s research=%s",
                    event_id, won,
                    self.decision_connectome.stats()["settled_observations"],
                    self.research_connectome.stats()["settled_observations"],
                )
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
