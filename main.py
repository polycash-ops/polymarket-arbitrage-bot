"""
AI-Enhanced Polymarket Arbitrage Bot
Main entry point - Orchestrates all components for 24/7 trading
"""
import asyncio
import argparse
import logging
from pathlib import Path
import yaml
import json
import time
from typing import Dict, Any

# Bot components
from bot.market_monitor import MarketMonitor, PricePoint
from bot.opportunity_detector import OpportunityDetector, Opportunity
from bot.trade_executor import TradeExecutor, Trade
from bot.ai_analyzer import AIAnalyzer, AIInsight
from bot.self_improvement import SelfImprovement

# Ensure the log directory exists before FileHandler is constructed.
Path('logs').mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TradingBot:
    def __init__(self, config_path: str = 'config.yaml', paper_trading: bool = True):
        self.config = self._load_config(config_path)
        self.paper_trading = paper_trading
        
        # Initialize components
        self.market_monitor = MarketMonitor(self.config.get('market_monitor', {}))
        self.opportunity_detector = OpportunityDetector(self.config.get('opportunity_detection', {}))
        self.trade_executor = TradeExecutor(self.config.get('trade_execution', {}), paper_trading)
        self.ai_analyzer = AIAnalyzer(self.config.get('ai_analysis', {}))
        self.self_improvement = SelfImprovement(self.config.get('self_improvement', {}))
        
        # Statistics
        self.stats = {
            'start_time': time.time(),
            'opportunities_detected': 0,
            'trades_executed': 0,
            'total_profit': 0.0,
            'uptime': 0
        }
        
        # Connect components
        self._setup_callbacks()
        
        logger.info(f"🤖 Trading Bot initialized - Mode: {'PAPER' if paper_trading else 'LIVE'}")
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"✅ Configuration loaded from {config_path}")
            return config
        except FileNotFoundError:
            logger.warning(f"⚠️ Config file {config_path} not found, using defaults")
            return self._default_config()
        except Exception as e:
            logger.error(f"❌ Error loading config: {e}")
            return self._default_config()
            
    def _default_config(self) -> Dict[str, Any]:
        """Default configuration"""
        return {
            'market_monitor': {
                'exchanges': ['binance', 'coinbase', 'kraken'],
                'update_interval': 0.1
            },
            'opportunity_detection': {
                'min_price_difference': 0.3,
                'min_confidence': 0.7,
                'max_delay_seconds': 15
            },
            'trade_execution': {
                'max_position_size': 1000,
                'min_position_size': 100,
                'risk_per_trade': 0.02,
                'max_daily_trades': 50
            },
            'ai_analysis': {
                'ai_buffer_size': 100,
                'ai_analysis_interval': 30
            },
            'self_improvement': {
                'improvement_analysis_interval': 3600,
                'min_trades_for_analysis': 20
            }
        }
        
    def _setup_callbacks(self):
        """Setup callbacks between components"""
        
        # Market monitor -> Opportunity detector & AI analyzer
        self.market_monitor.add_callback(self.opportunity_detector.on_price_update)
        self.market_monitor.add_callback(self.ai_analyzer.on_price_update)
        
        # Opportunity detector -> Trade executor (with AI enhancement)
        self.opportunity_detector.add_callback(self._on_opportunity_detected)
        
        # Trade executor -> Statistics & Self improvement
        self.trade_executor.add_callback(self._on_trade_executed)
        
        # AI analyzer -> Logging
        self.ai_analyzer.add_callback(self._on_ai_insight)
        
        # Self improvement -> Logging
        self.self_improvement.add_callback(self._on_improvement_event)
        
    async def _on_opportunity_detected(self, opportunity: Opportunity):
        """Handle detected opportunities"""
        logger.info(
            f"💡 OPPORTUNITY: {opportunity.exchange_moved} moved {opportunity.direction} "
            f"{opportunity.price_difference:.2f}% (confidence: {opportunity.confidence:.3f})"
        )
        
        self.stats['opportunities_detected'] += 1
        
        # The bundled AI analyzer is a mock, not a validated model. Do not let its
        # hard-coded response alter confidence or cause paper fills.
        minimum = self.config.get('opportunity_detection', {}).get('min_confidence', 0.7)
        if opportunity.confidence >= minimum:
            trade = await self.trade_executor.execute_opportunity(opportunity)
            if trade:
                logger.info(
                    "Paper position opened id=%s market=%s entry=%.4f stake=$%.2f; "
                    "realized P/L waits for final market settlement",
                    trade.id, trade.market_id, trade.executed_price or trade.expected_price, trade.amount
                )
        else:
            logger.info(
                "Opportunity rejected before execution: confidence %.3f below %.3f",
                opportunity.confidence, minimum
            )
            
    async def _on_trade_executed(self, trade: Trade):
        """Handle executed trades"""
        # This callback runs on both fill and settlement. Count fills once,
        # and only add realized P/L after the market outcome is final.
        if trade.executed_at is not None and not trade.resolved:
            self.stats['trades_executed'] += 1

        if trade.resolved and trade.profit_loss is not None:
            self.stats['total_profit'] = self.trade_executor.stats.total_profit
            
        pnl_text = (
            f"${trade.profit_loss:.2f}"
            if trade.resolved and trade.profit_loss is not None
            else "unsettled"
        )
        logger.info(
            "PAPER TRADE UPDATE id=%s status=%s P/L=%s realized_total=$%.2f",
            trade.id, trade.status.value, pnl_text, self.stats["total_profit"]
        )
        
        # Trigger self-improvement analysis with recent trades
        recent_trades = self.trade_executor.get_recent_trades(24)
        if len(recent_trades) >= self.config.get('self_improvement', {}).get('min_trades_for_analysis', 20):
            await self.self_improvement.force_analysis(recent_trades)
            
    async def _on_ai_insight(self, insight: AIInsight):
        """Handle AI insights"""
        logger.info(
            f"🧠 AI INSIGHT: Sentiment {insight.market_sentiment}, "
            f"Volatility {insight.volatility_prediction:.2f}, "
            f"Patterns: {len(insight.key_patterns)}"
        )
        
    async def _on_improvement_event(self, event_data: Dict[str, Any]):
        """Handle self-improvement events"""
        if event_data.get('type') == 'improvement_implemented':
            suggestion = event_data.get('suggestion', {})
            logger.info(f"🚀 IMPROVEMENT: {suggestion.get('description', 'Unknown improvement')}")
            
    async def start(self):
        """Start the trading bot"""
        logger.info("🚀 Starting AI-Enhanced Trading Bot...")
        
        try:
            # Start all components
            await asyncio.gather(
                self.market_monitor.start(),
                self.trade_executor.start(),
                self.ai_analyzer.start(),
                self.self_improvement.start(),
                self._status_loop()
            )
        except KeyboardInterrupt:
            logger.info("⚠️ Shutdown requested by user")
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
        finally:
            await self.stop()
            
    async def stop(self):
        """Stop the trading bot"""
        logger.info("🛑 Stopping Trading Bot...")
        
        await asyncio.gather(
            self.market_monitor.stop(),
            self.trade_executor.stop(),
            self.ai_analyzer.stop(),
            self.self_improvement.stop(),
            return_exceptions=True
        )
        
        logger.info("✅ Trading Bot stopped")
        
    async def _status_loop(self):
        """Periodic status updates"""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                
                # Update uptime
                self.stats['uptime'] = time.time() - self.stats['start_time']
                
                # Log status
                uptime_hours = self.stats['uptime'] / 3600
                logger.info(
                    f"📊 STATUS: {uptime_hours:.1f}h uptime, "
                    f"{self.stats['opportunities_detected']} opportunities, "
                    f"{self.stats['trades_executed']} trades, "
                    f"${self.stats['total_profit']:.2f} profit"
                )
                
                # Log detailed performance
                performance = self.trade_executor.get_performance_report()
                logger.info(
                    f"📈 PERFORMANCE: {performance['win_rate']:.1%} win rate, "
                    f"${performance['avg_profit_per_trade']:.2f} avg/trade"
                )
                
            except Exception as e:
                logger.error(f"❌ Status loop error: {e}")
                
    def get_status(self) -> Dict[str, Any]:
        """Get current bot status"""
        performance = self.trade_executor.get_performance_report()
        latest_prices = self.market_monitor.get_latest_prices()
        spreads = self.market_monitor.get_price_spread()
        
        return {
            'uptime_hours': (time.time() - self.stats['start_time']) / 3600,
            'mode': 'paper' if self.paper_trading else 'live',
            'stats': self.stats,
            'performance': performance,
            'latest_prices': {ex: p.price for ex, p in latest_prices.items()},
            'price_spreads': spreads,
            'ai_sentiment': self.ai_analyzer.get_market_sentiment(),
            'recent_opportunities': len(self.opportunity_detector.get_recent_opportunities(60))
        }

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='AI-Enhanced Polymarket Arbitrage Bot')
    parser.add_argument('--config', default='config.yaml', help='Configuration file path')
    parser.add_argument('--paper-trading', action='store_true', 
                       help='Run in paper trading mode (recommended)')
    parser.add_argument('--live-trading', action='store_true',
                       help='Run in live trading mode (DANGEROUS)')
    
    args = parser.parse_args()
    
    # Safety check
    if args.live_trading and args.paper_trading:
        logger.error("❌ Cannot specify both --paper-trading and --live-trading")
        return
        
    if not args.paper_trading and not args.live_trading:
        logger.info("⚠️ No trading mode specified, defaulting to paper trading")
        args.paper_trading = True
        
    if args.live_trading:
        logger.error("LIVE TRADING IS HARD-BLOCKED IN THIS REPOSITORY. Use paper mode only.")
        return
            
        # Initialize and start bot
    bot = TradingBot(args.config, paper_trading=args.paper_trading)
    
    logger.info("🎯 Starting temporal arbitrage bot based on 0x8dxd strategy")
    logger.info("⚔️ Enhanced with AI analysis and self-improvement")
    
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())