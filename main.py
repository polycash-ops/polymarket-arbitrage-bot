"""
Connectome Polymarket Arbitrage Research Bot
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
from bot.connectome import Connectome

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
        connectome_config = self.config.get('connectomes', {})
        # Separate databases, feature representations, and edge weights.
        self.decision_connectome = Connectome('decision', connectome_config.get('decision', {}))
        self.research_connectome = Connectome('research', connectome_config.get('research', {}))
        
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
            'connectomes': {
                'decision': self.decision_connectome.stats(),
                'research': self.research_connectome.stats(),
            },
            'recent_opportunities': len(self.opportunity_detector.get_recent_opportunities(60))
        }

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Connectome Polymarket Arbitrage Research Bot')
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
    logger.info("⚔️ Powered by two independent outcome-trained Connectome graphs")
    
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())