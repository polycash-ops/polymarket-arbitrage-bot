"""Connectome-driven Polymarket arbitrage research bot. Paper-only by design."""
import argparse
import asyncio
import json
import logging
import time
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Dict

import aiohttp
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
        self.analysis_connectome = Connectome("analysis", graph_config.get("analysis", {}))
        self.scan_checkpoints_seen = {}
        self.last_market_quote_by_id = {}
        self.last_connectome_snapshot_at = {}
        self.last_connectome_remaining = {}
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
                    "min_samples_for_gate": 1, "min_learned_probability": 0.50,
                    "learning_rate": 0.03,
                },
                "research": {
                    "max_nodes": 1_000_000, "max_edges": 1_000_000,
                    "min_samples_for_gate": 1, "learning_rate": 0.03,
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
        """Continuously snapshot live contract conditions, independently of paper trades."""
        if exchange not in {"polymarket", "polymarket_1h"} or not point.market_id or not point.end_time:
            return
        if point.bid is None or point.ask is None or not (0 < float(point.bid) <= float(point.ask) < 1):
            return
        now = float(point.timestamp)
        remaining = max(0.0, float(point.end_time) - now)
        horizon_seconds = 3600 if exchange == "polymarket_1h" else 900
        market_horizon = "1h" if exchange == "polymarket_1h" else "15m"
        if not (0 < remaining <= horizon_seconds):
            return
        market_id = str(point.market_id)
        # Load persisted checkpoint history once per market per worker process.
        # The SQLite observation rows remain the source of truth after restarts.
        if market_id not in self.scan_checkpoints_seen:
            seen = self.decision_connectome.observed_checkpoints(market_id)
            seen.update(self.research_connectome.observed_checkpoints(market_id))
            seen.update(self.analysis_connectome.observed_checkpoints(market_id))
            self.scan_checkpoints_seen[market_id] = seen
        seen = self.scan_checkpoints_seen[market_id]
        previous_snapshot = self.last_connectome_snapshot_at.get(market_id, 0.0)
        previous_remaining = self.last_connectome_remaining.get(market_id, remaining)
        threshold_candidates = []
        # A 45-second tolerance handles delayed first discovery/restarts while
        # keeping the four named checkpoint windows non-overlapping.
        for label, seconds in (("10m", 600), ("5m", 300), ("3m", 180), ("1m", 60)):
            crossed = previous_remaining > seconds >= remaining
            inside_window = seconds - 45.0 < remaining <= seconds
            if label not in seen and (crossed or inside_window):
                threshold_candidates.append((label, abs(remaining - seconds)))
        # Dashboard refreshes / market quote snapshots are sampled at 5 seconds.
        # The Polymarket poll is faster, so this de-duplicates to that cadence.
        continuous_due = now - previous_snapshot >= 5.0
        self.last_connectome_remaining[market_id] = remaining
        checkpoint = None
        checkpoint_labels = []
        first_observation = "first_seen" not in seen
        if threshold_candidates:
            # Prefer the actual threshold for graph features; first_seen remains
            # an additional reporting label when this is the contract's first scan.
            checkpoint = min(threshold_candidates, key=lambda candidate: candidate[1])[0]
            checkpoint_labels.append(checkpoint)
            if first_observation:
                checkpoint_labels.insert(0, "first_seen")
        elif first_observation:
            checkpoint = "first_seen"
            checkpoint_labels.append("first_seen")
        if checkpoint is None and not continuous_due:
            return
        for label in checkpoint_labels:
            seen.add(label)
        if checkpoint is None:
            checkpoint = "continuous"
            checkpoint_labels = ["continuous"]
        self.last_connectome_snapshot_at[market_id] = now

        # Preserve each venue as an independent signal; the graph learns which
        # cross-exchange relationships are predictive instead of hard-coding trust.
        exchange_moves = {}
        for venue in ("binance", "coinbase", "kraken"):
            venue_history = self.opportunity_detector.price_history.get(venue)
            venue_move = venue_history.get_change_pct(30) if venue_history else None
            exchange_moves[venue] = float(venue_move) if venue_move is not None else None
        move, exchanges = self.opportunity_detector._consensus_move()
        move = float(move or 0.0)
        active_signs = [1 if value > 0 else -1 if value < 0 else 0
                        for value in exchange_moves.values() if value is not None]
        positive_count = sum(sign > 0 for sign in active_signs)
        negative_count = sum(sign < 0 for sign in active_signs)
        if len(active_signs) < 3:
            exchange_relationship = "incomplete"
        elif positive_count == 3:
            exchange_relationship = "all_up"
        elif negative_count == 3:
            exchange_relationship = "all_down"
        elif positive_count == 2:
            exchange_relationship = "two_up_one_down"
        elif negative_count == 2:
            exchange_relationship = "two_down_one_up"
        else:
            exchange_relationship = "flat_or_mixed"
        def pair_relationship(left, right):
            if left is None or right is None:
                return "missing"
            left_sign = 1 if left > 0.005 else -1 if left < -0.005 else 0
            right_sign = 1 if right > 0.005 else -1 if right < -0.005 else 0
            if left_sign == right_sign:
                return "agree_up" if left_sign > 0 else "agree_down" if left_sign < 0 else "both_flat"
            return "bin_disagree" if left_sign == 0 or right_sign == 0 else "opposed"
        pair_relationships = {
            "binance_coinbase": pair_relationship(exchange_moves["binance"], exchange_moves["coinbase"]),
            "binance_kraken": pair_relationship(exchange_moves["binance"], exchange_moves["kraken"]),
            "coinbase_kraken": pair_relationship(exchange_moves["coinbase"], exchange_moves["kraken"]),
        }
        history = self.opportunity_detector.price_history.get(exchange)
        odds_change = float(history.get_probability_change(10) or 0.0) if history else 0.0
        midpoint = (float(point.bid) + float(point.ask)) / 2.0
        prediction_source = "btc_consensus" if abs(move) >= 0.001 and len(exchanges) >= 2 else "market_implied"
        direction = ("up" if move > 0 else "down") if prediction_source == "btc_consensus" else ("up" if midpoint >= 0.5 else "down")
        delay = max(0.0, now - self.opportunity_detector.last_polymarket_change)
        confidence = (
            self.opportunity_detector._calculate_confidence(abs(move), delay, odds_change, len(exchanges))
            if exchanges else 0.50
        )
        confidence = min(0.99, max(0.01, float(confidence)))
        previous_quote = self.last_market_quote_by_id.get(market_id)
        quote_changes = {}
        if previous_quote:
            elapsed = max(0.001, now - previous_quote["timestamp"])
            for field, value in (("bid", float(point.bid)), ("ask", float(point.ask)), ("midpoint", midpoint)):
                quote_changes[field + "_change_refresh"] = value - previous_quote[field]
                quote_changes[field + "_change_per_second"] = (value - previous_quote[field]) / elapsed
        else:
            quote_changes = {
                "bid_change_refresh": None, "ask_change_refresh": None,
                "midpoint_change_refresh": None, "bid_change_per_second": None,
                "ask_change_per_second": None, "midpoint_change_per_second": None,
            }
        self.last_market_quote_by_id[market_id] = {
            "timestamp": now, "bid": float(point.bid), "ask": float(point.ask), "midpoint": midpoint
        }
        # Read recent stored observations to derive same-contract movement windows.
        # Read prior snapshots for this exact contract. Two hours of lookback is
        # required to find a quote at least one hour old without mixing contracts.
        analysis_history = self.analysis_connectome.recent_market_observations(market_id, now - 7200.0)
        def movement_from_history(field, horizon_seconds, current_value):
            eligible = [row for row in analysis_history if now - float(row.get("timestamp", now)) >= horizon_seconds]
            if not eligible:
                return None
            # Use the closest prior quote at/before the requested horizon.
            prior = max(eligible, key=lambda row: float(row.get("timestamp", 0.0)))
            previous_value = prior.get(field)
            return None if previous_value is None else current_value - float(previous_value)
        def average_depth(horizon_seconds):
            values = [
                float(row["depth_imbalance"]) for row in analysis_history
                if row.get("depth_imbalance") is not None
                and 0 <= now - float(row.get("timestamp", now)) <= horizon_seconds
            ]
            return sum(values) / len(values) if values else getattr(point, "depth_imbalance", None)
        bid_move_15m = movement_from_history("bid", 900.0, float(point.bid))
        ask_move_15m = movement_from_history("ask", 900.0, float(point.ask))
        midpoint_move_15m = movement_from_history("midpoint", 900.0, midpoint)
        bid_move_1h = movement_from_history("bid", 3600.0, float(point.bid))
        ask_move_1h = movement_from_history("ask", 3600.0, float(point.ask))
        midpoint_move_1h = movement_from_history("midpoint", 3600.0, midpoint)
        depth_15m = average_depth(900.0)
        depth_1h = average_depth(3600.0)
        snapshot = SimpleNamespace(
            timestamp=now, market_id=market_id, checkpoint=checkpoint,
            checkpoint_labels=checkpoint_labels or [checkpoint],
            time_remaining=remaining, minutes_remaining=remaining / 60.0,
            midpoint=midpoint, market_up_probability=midpoint,
            depth_imbalance=getattr(point, "depth_imbalance", None),
            bid_depth=getattr(point, "bid_depth", None), ask_depth=getattr(point, "ask_depth", None),
            market_probability_change=odds_change,
            btc_consensus_move=move, agreeing_exchange_count=len(exchanges),
            exchange_binance_move=exchange_moves["binance"],
            exchange_coinbase_move=exchange_moves["coinbase"],
            exchange_kraken_move=exchange_moves["kraken"],
            exchange_relationship=exchange_relationship,
            exchange_pair_relationships=pair_relationships,
            exchange_positive_count=positive_count, exchange_negative_count=negative_count,
            prediction_source=prediction_source,
            exchange_moved=",".join(exchanges) if exchanges else "none",
            polymarket_delay=delay, price_difference=abs(move), confidence=confidence,
            direction=direction, recommended_action="buy_yes" if direction == "up" else "buy_no",
            yes_bid=float(point.bid), yes_ask=float(point.ask), market_question=point.question,
            market_horizon=market_horizon, market_contract_end_time=float(point.end_time),
            bid_change_refresh=quote_changes["bid_change_refresh"],
            ask_change_refresh=quote_changes["ask_change_refresh"],
            midpoint_change_refresh=quote_changes["midpoint_change_refresh"],
            bid_change_15m=bid_move_15m, ask_change_15m=ask_move_15m,
            midpoint_change_15m=midpoint_move_15m,
            bid_change_1h=bid_move_1h, ask_change_1h=ask_move_1h,
            midpoint_change_1h=midpoint_move_1h,
            order_depth_imbalance_15m=depth_15m, order_depth_imbalance_1h=depth_1h,
            market_end_time=point.end_time, expected_profit=0.0,
            yes_outcome_index=int(getattr(point, "yes_outcome_index", 0) or 0),
            connectome_event_id=f"scan:{market_id}:{int(now * 1000)}",
        )
        decision = self.decision_connectome.predict(snapshot, role="decision")
        research = self.research_connectome.predict(snapshot, role="research")
        self.decision_connectome.record_scan_observation(
            snapshot, role="decision", forecast_probability=decision["probability"],
            forecast_up_probability=decision["up_probability"],
        )
        self.research_connectome.record_scan_observation(
            snapshot, role="research", forecast_probability=research["probability"],
            forecast_up_probability=research["up_probability"],
        )
        analysis = self.analysis_connectome.predict(snapshot, role="analysis")
        self.analysis_connectome.record_scan_observation(
            snapshot, role="analysis", forecast_probability=analysis["probability"],
            forecast_up_probability=analysis["up_probability"],
        )
        logger.info(
            "CONNECTOME_SCAN horizon=%s market=%s checkpoint=%s remaining=%.1fs midpoint=%.4f "
            "odds_change_10s=%.4f btc_move_pct=%.4f direction=%s exchanges=%s "
            "relationship=%s raw_score=%.3f decision_confidence=%.3f decision_up_p=%.3f decision_samples=%d "
            "research_confidence=%.3f research_up_p=%.3f research_samples=%d "
            "analysis_up_p=%.3f analysis_samples=%d paper_trade=not_required",
            market_horizon, market_id, checkpoint, remaining, midpoint, odds_change, abs(move), direction,
            ",".join(f"{venue}:{value:+.4f}" if value is not None else f"{venue}:missing"
                     for venue, value in exchange_moves.items()),
            exchange_relationship, confidence, decision["probability"], decision["up_probability"], decision["samples"],
            research["probability"], research["up_probability"], research["samples"],
            analysis["up_probability"], analysis["samples"],
        )

    async def _on_contract_settled(self, market_id: str, actual_up: bool):
        d_count = self.decision_connectome.settle_market(market_id, actual_up)
        r_count = self.research_connectome.settle_market(market_id, actual_up)
        a_count = self.analysis_connectome.settle_market(market_id, actual_up)
        self.scan_checkpoints_seen.pop(market_id, None)
        self.last_market_quote_by_id.pop(market_id, None)
        logger.info(
            "CONNECTOME_MARKET_LABEL market=%s actual_up=%s decision_labels=%d research_labels=%d analysis_labels=%d",
            market_id, actual_up, d_count, r_count, a_count,
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
        remaining = max(0.0, float(opportunity.market_end_time or time.time()) - time.time())
        opportunity.time_remaining = remaining
        point = self.market_monitor.get_latest_prices().get("polymarket")
        if point and point.market_id == opportunity.market_id:
            opportunity.midpoint = ((float(point.bid) + float(point.ask)) / 2.0
                                    if point.bid is not None and point.ask is not None and
                                    0 < point.bid <= point.ask < 1 else float(point.price))
            opportunity.yes_outcome_index = int(point.yes_outcome_index)
        else:
            opportunity.midpoint = 0.5
        history = self.opportunity_detector.price_history.get("polymarket")
        opportunity.market_probability_change = float(history.get_probability_change(10) or 0.0) if history else 0.0
        move, agreeing = self.opportunity_detector._consensus_move()
        opportunity.btc_consensus_move = float(move or 0.0)
        opportunity.agreeing_exchange_count = len(agreeing)
        opportunity.prediction_source = "btc_consensus" if move is not None and len(agreeing) >= 2 else "market_midpoint"
        if remaining >= 840:
            opportunity.checkpoint = "first_seen"
        else:
            opportunity.checkpoint = next((label for seconds, label in ((600, "10m"), (300, "5m"), (180, "3m"), (60, "1m"))
                                           if abs(remaining - seconds) <= 30), "between")
        decision = self.decision_connectome.predict(opportunity, role="decision")
        research = self.research_connectome.predict(opportunity, role="research")
        logger.info(
            "CONNECTOME_SIGNAL decision_probability=%.3f decision_samples=%d "
            "research_probability=%.3f research_samples=%d",
            decision["probability"], decision["samples"], research["probability"], research["samples"],
        )
        # Forecast-only research phase: agents collect observations and score
        # forecasts after authoritative settlement. No paper or live positions
        # are opened while the agents are building their accuracy history.
        logger.info(
            "FORECAST_ONLY market=%s checkpoint=%s direction=%s "
            "decision_p=%.3f decision_up_p=%.3f decision_settled_samples=%d "
            "research_p=%.3f research_up_p=%.3f research_settled_samples=%d "
            "trade_execution=disabled",
            opportunity.market_id, opportunity.checkpoint, opportunity.direction,
            decision["probability"], decision["up_probability"], decision["samples"],
            research["probability"], research["up_probability"], research["samples"],
        )
        return

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
                self._checkpoint_settlement_loop(),
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

    async def _checkpoint_settlement_loop(self):
        """Recover unresolved scan labels after worker restarts using Gamma's final outcomes."""
        url = "https://gamma-api.polymarket.com/markets"
        async with aiohttp.ClientSession() as session:
            while True:
                await asyncio.sleep(30)
                pending = set(self.decision_connectome.pending_markets())
                pending.update(self.research_connectome.pending_markets())
                for market_id in pending:
                    try:
                        async with session.get(f"{url}/slug/{market_id}", timeout=aiohttp.ClientTimeout(total=10)) as response:
                            if response.status != 200:
                                continue
                            payload = await response.json()
                        market = payload[0] if isinstance(payload, list) and payload else payload
                        if not isinstance(market, dict) or not market.get("closed"):
                            continue
                        outcomes = market.get("outcomes", [])
                        prices = market.get("outcomePrices", [])
                        if isinstance(outcomes, str):
                            outcomes = json.loads(outcomes)
                        if isinstance(prices, str):
                            prices = json.loads(prices)
                        if not isinstance(outcomes, list) or not isinstance(prices, list) or len(outcomes) < 2 or len(prices) < 2:
                            continue
                        parsed = [float(prices[0]), float(prices[1])]
                        winner_index = 0 if parsed[0] >= 0.99 else 1 if parsed[1] >= 0.99 else None
                        if winner_index is None:
                            continue
                        winner = str(outcomes[winner_index]).lower()
                        if "up" in winner:
                            actual_up = True
                        elif "down" in winner:
                            actual_up = False
                        else:
                            continue
                        await self._on_contract_settled(market_id, actual_up)
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, json.JSONDecodeError) as exc:
                        logger.warning("Checkpoint settlement recovery failed for %s: %s", market_id, exc)
                    except Exception:
                        logger.exception("Unexpected checkpoint settlement recovery error for %s", market_id)

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
            "latest_polymarket_quotes": {
                exchange: {
                    "market_id": point.market_id, "question": point.question,
                    "bid": point.bid, "ask": point.ask,
                    "midpoint": ((float(point.bid) + float(point.ask)) / 2.0
                                 if point.bid is not None and point.ask is not None else point.price),
                    "price": point.price, "timestamp": point.timestamp,
                    "end_time": point.end_time,
                    "remaining_seconds": max(0.0, float(point.end_time) - time.time()) if point.end_time else None,
                }
                for exchange, point in latest_prices.items()
                if exchange in {"polymarket", "polymarket_1h"}
            },
            "snapshot_cadence_seconds": 5,
            "price_spreads": self.market_monitor.get_price_spread(),
            "connectomes": {
                "decision": self.decision_connectome.stats(),
                "research": self.research_connectome.stats(),
                "analysis": self.analysis_connectome.stats(),
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
