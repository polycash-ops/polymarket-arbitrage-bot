#!/usr/bin/env python3
"""
AI-Enhanced Polymarket Arbitrage Bot
Replicating and improving 0x8dxd's $313→$438K strategy
"""

import asyncio
import argparse
import logging
from pathlib import Path

from core.bot import TradingBot
from core.config import BotConfig
from utils.logger import setup_logger


async def main():
    """Main entry point for the trading bot."""
    
    parser = argparse.ArgumentParser(description="AI-Enhanced Trading Bot")
    parser.add_argument("--paper-trading", action="store_true", 
                       help="Run in paper trading mode (no real money)")
    parser.add_argument("--config", type=str, default="config/bot.yaml",
                       help="Path to configuration file")
    parser.add_argument("--log-level", type=str, default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logger(level=args.log_level)
    
    try:
        # Load configuration
        config = BotConfig.from_file(args.config)
        
        if args.paper_trading:
            config.trading.paper_mode = True
            logger.info("🧪 Running in PAPER TRADING mode - No real money at risk!")
        else:
            logger.info("💰 Running in LIVE TRADING mode - Real money at risk!")
        
        # Initialize and start bot
        bot = TradingBot(config)
        
        logger.info("🚀 Starting AI-Enhanced Trading Bot...")
        logger.info(f"📊 Target: Replicate 0x8dxd's ${config.trading.daily_target:,.0f}/day strategy")
        
        await bot.start()
        
    except KeyboardInterrupt:
        logger.info("👋 Shutting down bot gracefully...")
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())