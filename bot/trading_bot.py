"""
🚀 Trading Bot - Main Bot Class

Orchestrates all components for AI-enhanced Polymarket arbitrage
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json

from .monitors.price_monitor import PriceMonitor
from .monitors.polymarket_monitor import PolymarketMonitor
from .detectors.opportunity_detector import OpportunityDetector
from .analyzers.ai_analyzer import AIAnalyzer
from .executors.trade_executor import TradeExecutor
from .improver.self_improver import SelfImprover


logger = logging.getLogger(__name__)


class TradingBot:
    """Main trading bot orchestrating all components"""
    
    def __init__(self, config: dict):
        self.config = config
        self.is_running = False
        
        # Components
        self.price_monitor = PriceMonitor(config)
        self.polymarket_monitor = PolymarketMonitor(config)
        self.opportunity_detector = OpportunityDetector(config)
        self.ai_analyzer = AIAnalyzer(config)
        self.trade_executor = TradeExecutor(config)
        self.self_improver = SelfImprover(config)
        
        # State
        self.trades_executed = 0
        self.total_pnl = 0.0
        self.start_time = None
        self.last_report = None
        
        # Performance tracking
        self.performance_stats = {
            'win_rate': 0.0,
            'total_trades': 0,
            'profitable_trades': 0,
            'average_profit': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0
        }
    
    async def start(self):
        """Start the trading bot"""
        logger.info("🚀 Starting Trading Bot...")
        
        self.is_running = True
        self.start_time = datetime.now()
        self.last_report = datetime.now()
        
        # Start all components
        await self._start_components()
        
        # Start main trading loop
        asyncio.create_task(self._trading_loop())
        asyncio.create_task(self._monitoring_loop())
        asyncio.create_task(self._improvement_loop())
        
        logger.info("✅ Trading Bot started successfully!")
    
    async def stop(self):
        """Stop the trading bot"""
        logger.info("🛑 Stopping Trading Bot...")
        
        self.is_running = False
        
        # Stop all components
        await self._stop_components()
        
        # Generate final report
        await self._generate_final_report()
        
        logger.info("✅ Trading Bot stopped successfully!")
    
    async def _start_components(self):
        """Start all bot components"""
        components = [
            ("Price Monitor", self.price_monitor),
            ("Polymarket Monitor", self.polymarket_monitor),
            ("Opportunity Detector", self.opportunity_detector),
            ("AI Analyzer", self.ai_analyzer),
            ("Trade Executor", self.trade_executor),
            ("Self Improver", self.self_improver)
        ]
        
        for name, component in components:
            try:
                await component.start()
                logger.info(f"✅ {name} started")
            except Exception as e:
                logger.error(f"❌ Failed to start {name}: {e}")
                raise
    
    async def _stop_components(self):
        """Stop all bot components"""
        components = [
            self.self_improver,
            self.trade_executor,
            self.ai_analyzer,
            self.opportunity_detector,
            self.polymarket_monitor,
            self.price_monitor
        ]
        
        for component in components:
            try:
                await component.stop()
            except Exception as e:
                logger.error(f"Error stopping component: {e}")
    
    async def _trading_loop(self):
        """Main trading loop"""
        logger.info("🔄 Trading loop started")
        
        while self.is_running:
            try:
                # Get latest market data
                exchange_prices = await self.price_monitor.get_latest_prices()
                polymarket_prices = await self.polymarket_monitor.get_latest_prices()
                
                if not exchange_prices or not polymarket_prices:
                    await asyncio.sleep(0.1)
                    continue
                
                # Detect opportunities
                opportunities = await self.opportunity_detector.detect_opportunities(
                    exchange_prices, polymarket_prices
                )
                
                if not opportunities:
                    await asyncio.sleep(0.05)  # 50ms when no opportunities
                    continue
                
                # Analyze with AI
                for opportunity in opportunities:
                    analysis = await self.ai_analyzer.analyze_opportunity(opportunity)
                    
                    # Execute trades if analysis is positive
                    if analysis['should_trade']:
                        trade_result = await self.trade_executor.execute_trade(
                            opportunity, analysis
                        )
                        
                        if trade_result:
                            await self._process_trade_result(trade_result)
                
                await asyncio.sleep(0.02)  # 20ms loop for high frequency
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(1)  # Longer delay on error
    
    async def _monitoring_loop(self):
        """Monitoring and reporting loop"""
        while self.is_running:
            try:
                # Generate hourly reports
                if datetime.now() - self.last_report > timedelta(hours=1):
                    await self._generate_performance_report()
                    self.last_report = datetime.now()
                
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)
    
    async def _improvement_loop(self):
        """Self-improvement loop"""
        if not self.config.get('improvement', {}).get('enabled', False):
            return
            
        while self.is_running:
            try:
                # Run self-improvement every hour
                await asyncio.sleep(3600)  # 1 hour
                
                if self.performance_stats['total_trades'] > 100:
                    improvements = await self.self_improver.analyze_performance(
                        self.performance_stats
                    )
                    
                    if improvements:
                        await self._apply_improvements(improvements)
                        
            except Exception as e:
                logger.error(f"Error in improvement loop: {e}")
                await asyncio.sleep(3600)
    
    async def _process_trade_result(self, trade_result: dict):
        """Process completed trade result"""
        self.trades_executed += 1
        
        pnl = trade_result.get('pnl', 0.0)
        self.total_pnl += pnl
        
        # Update performance stats
        self.performance_stats['total_trades'] += 1
        
        if pnl > 0:
            self.performance_stats['profitable_trades'] += 1
        
        self.performance_stats['win_rate'] = (
            self.performance_stats['profitable_trades'] / 
            self.performance_stats['total_trades']
        )
        
        # Log trade
        logger.info(
            f"💰 Trade #{self.trades_executed}: "
            f"PnL: ${pnl:.2f}, "
            f"Total PnL: ${self.total_pnl:.2f}, "
            f"Win Rate: {self.performance_stats['win_rate']:.1%}"
        )
        
        # Notify if significant trade
        if abs(pnl) > 100:  # $100+ trade
            await self._notify_trade(trade_result)
    
    async def _generate_performance_report(self):
        """Generate and log performance report"""
        uptime = datetime.now() - self.start_time
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'uptime_hours': uptime.total_seconds() / 3600,
            'total_trades': self.trades_executed,
            'total_pnl': self.total_pnl,
            'win_rate': self.performance_stats['win_rate'],
            'avg_profit_per_hour': self.total_pnl / (uptime.total_seconds() / 3600),
            'trades_per_hour': self.trades_executed / (uptime.total_seconds() / 3600)
        }
        
        logger.info(f"📊 Performance Report: {json.dumps(report, indent=2)}")
        
        # Save to file
        with open('logs/performance.jsonl', 'a') as f:
            f.write(json.dumps(report) + '\n')
    
    async def _generate_final_report(self):
        """Generate final performance report"""
        uptime = datetime.now() - self.start_time if self.start_time else timedelta(0)
        
        report = f"""
        🏁 FINAL TRADING REPORT
        
        ⏰ Total Runtime: {uptime}
        💰 Total P&L: ${self.total_pnl:.2f}
        📈 Total Trades: {self.trades_executed}
        🎯 Win Rate: {self.performance_stats['win_rate']:.1%}
        💵 Avg Profit/Hour: ${self.total_pnl / max(uptime.total_seconds() / 3600, 1):.2f}
        ⚡ Trades/Hour: {self.trades_executed / max(uptime.total_seconds() / 3600, 1):.1f}
        """
        
        logger.info(report)
    
    async def _notify_trade(self, trade_result: dict):
        """Send trade notification"""
        # TODO: Implement Discord/Telegram notifications
        pass
    
    async def _apply_improvements(self, improvements: dict):
        """Apply self-improvement suggestions"""
        logger.info(f"🔧 Applying improvements: {improvements}")
        
        # Update configuration dynamically
        for key, value in improvements.items():
            if key in self.config['trading']:
                old_value = self.config['trading'][key]
                self.config['trading'][key] = value
                logger.info(f"📝 Updated {key}: {old_value} → {value}")
    
    def get_status(self) -> dict:
        """Get current bot status"""
        return {
            'is_running': self.is_running,
            'uptime': (datetime.now() - self.start_time).total_seconds() if self.start_time else 0,
            'trades_executed': self.trades_executed,
            'total_pnl': self.total_pnl,
            'performance_stats': self.performance_stats
        }