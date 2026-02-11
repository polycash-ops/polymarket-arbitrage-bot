"""
Self-Improvement System
Continuously optimizes trading strategies based on performance data
"""
import asyncio
import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import logging
import statistics

from .trade_executor import Trade, TradeStatus

logger = logging.getLogger(__name__)

@dataclass
class PerformanceMetrics:
    win_rate: float
    avg_profit: float
    max_drawdown: float
    sharpe_ratio: float
    total_trades: int
    profit_factor: float
    avg_trade_duration: float

@dataclass
class StrategyAdjustment:
    parameter: str
    old_value: Any
    new_value: Any
    reason: str
    expected_improvement: str
    timestamp: float

@dataclass
class ImprovementSuggestion:
    category: str  # 'risk_management', 'opportunity_detection', 'execution'
    description: str
    implementation: str
    expected_impact: float
    confidence: float
    priority: int  # 1-5, 5 is highest

class SelfImprovement:
    def __init__(self, config: dict):
        self.config = config
        self.performance_history: List[PerformanceMetrics] = []
        self.strategy_adjustments: List[StrategyAdjustment] = []
        self.current_parameters = self._load_initial_parameters()
        self.callbacks = []
        
        # Improvement settings
        self.analysis_interval = config.get('improvement_analysis_interval', 3600)  # 1 hour
        self.min_trades_for_analysis = config.get('min_trades_for_analysis', 20)
        self.improvement_threshold = config.get('improvement_threshold', 0.05)  # 5% improvement needed
        
        # Performance tracking
        self.last_analysis_time = 0
        self.improvement_task = None
        
    def _load_initial_parameters(self) -> Dict[str, Any]:
        """Load initial trading parameters"""
        return {
            'min_confidence': 0.7,
            'min_price_difference': 0.3,
            'max_delay_seconds': 15,
            'position_size_multiplier': 1.0,
            'risk_per_trade': 0.02,
            'max_daily_trades': 50,
            'volatility_threshold': 2.0,
            'momentum_weight': 1.0,
            'delay_penalty_factor': 0.1
        }
        
    def add_callback(self, callback):
        """Add callback for improvement events"""
        self.callbacks.append(callback)
        
    async def start(self):
        """Start self-improvement system"""
        logger.info("🚀 Starting Self-Improvement System...")
        self.improvement_task = asyncio.create_task(self._improvement_loop())
        
    async def stop(self):
        """Stop self-improvement system"""
        if self.improvement_task:
            self.improvement_task.cancel()
        logger.info("🛑 Self-Improvement System stopped")
        
    async def _improvement_loop(self):
        """Main improvement analysis loop"""
        while True:
            try:
                await asyncio.sleep(self.analysis_interval)
                
                # Analyze performance and suggest improvements
                await self._analyze_and_improve()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Improvement loop error: {e}")
                await asyncio.sleep(60)
                
    async def analyze_trades(self, trades: List[Trade]) -> PerformanceMetrics:
        """Analyze trade performance and calculate metrics"""
        
        if len(trades) < 5:
            return PerformanceMetrics(0, 0, 0, 0, 0, 0, 0)
            
        executed_trades = [t for t in trades if t.status == TradeStatus.EXECUTED]
        
        if not executed_trades:
            return PerformanceMetrics(0, 0, 0, 0, len(trades), 0, 0)
            
        # Calculate metrics
        win_rate = len([t for t in executed_trades if (t.profit_loss or 0) > 0]) / len(executed_trades)
        
        profits = [t.profit_loss or 0 for t in executed_trades]
        avg_profit = statistics.mean(profits)
        
        # Calculate drawdown
        cumulative_profits = []
        running_total = 0
        for profit in profits:
            running_total += profit
            cumulative_profits.append(running_total)
            
        peak = cumulative_profits[0]
        max_drawdown = 0
        for value in cumulative_profits:
            if value > peak:
                peak = value
            drawdown = (peak - value) / abs(peak) if peak != 0 else 0
            max_drawdown = max(max_drawdown, drawdown)
            
        # Calculate Sharpe ratio (simplified)
        if len(profits) > 1:
            std_dev = statistics.stdev(profits)
            sharpe_ratio = avg_profit / std_dev if std_dev != 0 else 0
        else:
            sharpe_ratio = 0
            
        # Profit factor
        winning_trades = [p for p in profits if p > 0]
        losing_trades = [abs(p) for p in profits if p < 0]
        
        total_wins = sum(winning_trades) if winning_trades else 0
        total_losses = sum(losing_trades) if losing_trades else 1
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Average trade duration (simplified - assume 15 minutes average)
        avg_duration = 15 * 60  # 15 minutes in seconds
        
        return PerformanceMetrics(
            win_rate=win_rate,
            avg_profit=avg_profit,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            total_trades=len(executed_trades),
            profit_factor=profit_factor,
            avg_trade_duration=avg_duration
        )
        
    async def _analyze_and_improve(self):
        """Analyze performance and implement improvements"""
        
        # This would be called with actual trade data
        # For now, simulate the improvement process
        
        current_time = time.time()
        
        if current_time - self.last_analysis_time < self.analysis_interval:
            return
            
        self.last_analysis_time = current_time
        
        logger.info("🔍 Analyzing performance for improvements...")
        
        # Generate improvement suggestions
        suggestions = await self._generate_improvement_suggestions()
        
        if suggestions:
            # Implement the highest priority suggestion
            best_suggestion = max(suggestions, key=lambda s: s.priority * s.confidence)
            
            if best_suggestion.confidence > 0.7 and best_suggestion.priority >= 3:
                await self._implement_suggestion(best_suggestion)
                
    async def _generate_improvement_suggestions(self) -> List[ImprovementSuggestion]:
        """Generate improvement suggestions based on recent performance"""
        
        suggestions = []
        
        # Example suggestions (would be based on actual performance analysis)
        
        # Risk management improvement
        if len(self.performance_history) >= 3:
            recent_drawdown = statistics.mean([m.max_drawdown for m in self.performance_history[-3:]])
            
            if recent_drawdown > 0.1:  # 10% drawdown
                suggestions.append(ImprovementSuggestion(
                    category='risk_management',
                    description='Reduce position sizes due to high drawdown',
                    implementation='Decrease risk_per_trade from {:.3f} to {:.3f}'.format(
                        self.current_parameters['risk_per_trade'],
                        self.current_parameters['risk_per_trade'] * 0.8
                    ),
                    expected_impact=0.15,
                    confidence=0.8,
                    priority=4
                ))
                
        # Opportunity detection improvement
        suggestions.append(ImprovementSuggestion(
            category='opportunity_detection',
            description='Increase minimum confidence threshold for better win rate',
            implementation='Increase min_confidence from {:.2f} to {:.2f}'.format(
                self.current_parameters['min_confidence'],
                min(self.current_parameters['min_confidence'] + 0.05, 0.9)
            ),
            expected_impact=0.1,
            confidence=0.7,
            priority=3
        ))
        
        # Execution timing improvement
        suggestions.append(ImprovementSuggestion(
            category='execution',
            description='Optimize delay threshold based on recent market conditions',
            implementation='Adjust max_delay_seconds based on volatility',
            expected_impact=0.08,
            confidence=0.6,
            priority=2
        ))
        
        return suggestions
        
    async def _implement_suggestion(self, suggestion: ImprovementSuggestion):
        """Implement an improvement suggestion"""
        
        logger.info(f"🔧 Implementing improvement: {suggestion.description}")
        
        # Record the adjustment
        adjustment = StrategyAdjustment(
            parameter=suggestion.category,
            old_value=str(self.current_parameters.get(suggestion.category, 'N/A')),
            new_value=suggestion.implementation,
            reason=suggestion.description,
            expected_improvement=f"{suggestion.expected_impact:.1%}",
            timestamp=time.time()
        )
        
        self.strategy_adjustments.append(adjustment)
        
        # Actually implement the change (example)
        if suggestion.category == 'risk_management' and 'risk_per_trade' in suggestion.implementation:
            # Extract new value (simplified)
            if 'Decrease risk_per_trade' in suggestion.implementation:
                self.current_parameters['risk_per_trade'] *= 0.8
                
        elif suggestion.category == 'opportunity_detection' and 'min_confidence' in suggestion.implementation:
            if 'Increase min_confidence' in suggestion.implementation:
                self.current_parameters['min_confidence'] = min(
                    self.current_parameters['min_confidence'] + 0.05, 0.9
                )
                
        # Notify callbacks
        await self._notify_callbacks({
            'type': 'improvement_implemented',
            'suggestion': asdict(suggestion),
            'adjustment': asdict(adjustment)
        })
        
        logger.info(f"✅ Improvement implemented: {suggestion.description}")
        
    async def get_improvement_report(self) -> Dict[str, Any]:
        """Get detailed improvement report"""
        
        return {
            'current_parameters': self.current_parameters,
            'recent_adjustments': [asdict(adj) for adj in self.strategy_adjustments[-10:]],
            'performance_trend': self._calculate_performance_trend(),
            'improvement_opportunities': await self._generate_improvement_suggestions(),
            'total_adjustments': len(self.strategy_adjustments),
            'last_analysis': self.last_analysis_time
        }
        
    def _calculate_performance_trend(self) -> Dict[str, float]:
        """Calculate performance trend over time"""
        
        if len(self.performance_history) < 2:
            return {'trend': 'insufficient_data'}
            
        recent_metrics = self.performance_history[-5:]  # Last 5 analysis periods
        
        win_rates = [m.win_rate for m in recent_metrics]
        profits = [m.avg_profit for m in recent_metrics]
        
        win_rate_trend = (win_rates[-1] - win_rates[0]) / len(win_rates) if len(win_rates) > 1 else 0
        profit_trend = (profits[-1] - profits[0]) / len(profits) if len(profits) > 1 else 0
        
        return {
            'win_rate_trend': win_rate_trend,
            'profit_trend': profit_trend,
            'overall_trend': 'improving' if win_rate_trend > 0 and profit_trend > 0 else 'declining'
        }
        
    async def _notify_callbacks(self, event_data: Dict[str, Any]):
        """Notify callbacks about improvement events"""
        for callback in self.callbacks:
            try:
                await callback(event_data)
            except Exception as e:
                logger.error(f"❌ Improvement callback error: {e}")
                
    def get_current_parameters(self) -> Dict[str, Any]:
        """Get current trading parameters"""
        return self.current_parameters.copy()
        
    def update_parameter(self, parameter: str, value: Any, reason: str = "Manual adjustment"):
        """Manually update a trading parameter"""
        
        old_value = self.current_parameters.get(parameter)
        self.current_parameters[parameter] = value
        
        adjustment = StrategyAdjustment(
            parameter=parameter,
            old_value=old_value,
            new_value=value,
            reason=reason,
            expected_improvement="Manual override",
            timestamp=time.time()
        )
        
        self.strategy_adjustments.append(adjustment)
        
        logger.info(f"🔧 Parameter updated: {parameter} = {value} (was {old_value})")
        
    async def force_analysis(self, trades: List[Trade]):
        """Force an immediate analysis with provided trades"""
        
        logger.info("🔍 Forcing immediate performance analysis...")
        
        metrics = await self.analyze_trades(trades)
        self.performance_history.append(metrics)
        
        # Generate and potentially implement improvements
        await self._analyze_and_improve()
        
        return metrics