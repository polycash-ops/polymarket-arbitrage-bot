"""
AI Pattern Analyzer using Claude
Enhances opportunity detection with advanced pattern recognition
"""
import asyncio
import json
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging

from .opportunity_detector import Opportunity
from .market_monitor import PricePoint

logger = logging.getLogger(__name__)

@dataclass
class MarketPattern:
    pattern_type: str  # 'trend_reversal', 'momentum', 'volatility_spike', etc.
    confidence: float
    description: str
    timeframe: str
    indicators: Dict[str, Any]
    recommendation: str

@dataclass
class AIInsight:
    timestamp: float
    market_sentiment: str  # 'bullish', 'bearish', 'neutral'
    volatility_prediction: float
    key_patterns: List[MarketPattern]
    risk_assessment: str
    trade_recommendations: List[str]
    confidence: float

class AIAnalyzer:
    def __init__(self, config: dict):
        self.config = config
        self.price_buffer: Dict[str, List[PricePoint]] = {}
        self.recent_insights: List[AIInsight] = []
        self.callbacks = []
        
        # Buffer settings
        self.buffer_size = config.get('ai_buffer_size', 100)  # Keep 100 price points
        self.analysis_interval = config.get('ai_analysis_interval', 30)  # Analyze every 30 seconds
        
        # Start analysis loop
        self._analysis_task = None
        
    def add_callback(self, callback):
        """Add callback for AI insights"""
        self.callbacks.append(callback)
        
    async def start(self):
        """Start AI analysis loop"""
        logger.info("🧠 Starting AI Analyzer...")
        self._analysis_task = asyncio.create_task(self._analysis_loop())
        
    async def stop(self):
        """Stop AI analysis"""
        if self._analysis_task:
            self._analysis_task.cancel()
        logger.info("🛑 AI Analyzer stopped")
        
    async def on_price_update(self, exchange: str, price_point: PricePoint):
        """Handle price updates and buffer for analysis"""
        
        if exchange not in self.price_buffer:
            self.price_buffer[exchange] = []
            
        self.price_buffer[exchange].append(price_point)
        
        # Keep buffer size manageable
        if len(self.price_buffer[exchange]) > self.buffer_size:
            self.price_buffer[exchange] = self.price_buffer[exchange][-self.buffer_size:]
            
    async def analyze_opportunity(self, opportunity: Opportunity) -> float:
        """Analyze opportunity using AI and return enhanced confidence score"""
        
        try:
            # Prepare market data for Claude analysis
            market_data = self._prepare_market_data()
            
            if not market_data:
                logger.warning("⚠️ No market data available for AI analysis")
                return opportunity.confidence  # Return original confidence
                
            # Create analysis prompt
            prompt = self._create_analysis_prompt(opportunity, market_data)
            
            # Get Claude analysis (simulated for now)
            ai_response = await self._query_claude(prompt)
            
            if ai_response:
                # Parse Claude response and extract enhanced confidence
                enhanced_confidence = self._parse_claude_response(ai_response, opportunity.confidence)
                logger.info(f"🧠 AI Enhanced confidence: {opportunity.confidence:.3f} → {enhanced_confidence:.3f}")
                return enhanced_confidence
            else:
                return opportunity.confidence
                
        except Exception as e:
            logger.error(f"❌ AI analysis error: {e}")
            return opportunity.confidence  # Fallback to original confidence
            
    async def _analysis_loop(self):
        """Main AI analysis loop - runs periodically"""
        while True:
            try:
                await asyncio.sleep(self.analysis_interval)
                
                if not self.price_buffer:
                    continue
                    
                # Perform periodic market analysis
                insight = await self._analyze_market_patterns()
                
                if insight:
                    self.recent_insights.append(insight)
                    
                    # Keep only recent insights (last 2 hours)
                    cutoff_time = insight.timestamp - 7200
                    self.recent_insights = [i for i in self.recent_insights if i.timestamp >= cutoff_time]
                    
                    await self._notify_callbacks(insight)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ AI analysis loop error: {e}")
                await asyncio.sleep(5)
                
    async def _analyze_market_patterns(self) -> Optional[AIInsight]:
        """Analyze current market patterns using AI"""
        
        try:
            market_data = self._prepare_market_data()
            if not market_data:
                return None
                
            # Create pattern analysis prompt
            prompt = self._create_pattern_analysis_prompt(market_data)
            
            # Query Claude for pattern analysis
            ai_response = await self._query_claude(prompt)
            
            if ai_response:
                return self._parse_pattern_response(ai_response)
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ Pattern analysis error: {e}")
            return None
            
    def _prepare_market_data(self) -> Dict[str, Any]:
        """Prepare market data for Claude analysis"""
        
        data = {}
        
        for exchange, price_points in self.price_buffer.items():
            if len(price_points) < 10:  # Need minimum data
                continue
                
            recent_prices = [p.price for p in price_points[-20:]]  # Last 20 prices
            recent_times = [p.timestamp for p in price_points[-20:]]
            
            # Calculate basic indicators
            data[exchange] = {
                'current_price': recent_prices[-1],
                'prices': recent_prices,
                'timestamps': recent_times,
                'price_change_5m': self._calculate_price_change(price_points, 300),  # 5 minutes
                'price_change_1m': self._calculate_price_change(price_points, 60),   # 1 minute
                'volatility': self._calculate_volatility(recent_prices),
                'volume_trend': getattr(price_points[-1], 'volume', 0)
            }
            
        return data
        
    def _calculate_price_change(self, price_points: List[PricePoint], seconds: int) -> float:
        """Calculate price change over last N seconds"""
        if len(price_points) < 2:
            return 0.0
            
        current_time = price_points[-1].timestamp
        cutoff_time = current_time - seconds
        
        # Find price closest to cutoff time
        old_price = None
        for point in reversed(price_points[:-1]):
            if point.timestamp <= cutoff_time:
                old_price = point.price
                break
                
        if old_price is None:
            old_price = price_points[0].price
            
        current_price = price_points[-1].price
        return (current_price - old_price) / old_price * 100
        
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate price volatility (standard deviation)"""
        if len(prices) < 2:
            return 0.0
            
        mean_price = sum(prices) / len(prices)
        variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
        return (variance ** 0.5) / mean_price * 100  # As percentage
        
    def _create_analysis_prompt(self, opportunity: Opportunity, market_data: Dict) -> str:
        """Create prompt for Claude to analyze opportunity"""
        
        prompt = f"""
Analyze this temporal arbitrage trading opportunity:

OPPORTUNITY DETAILS:
- Exchange that moved: {opportunity.exchange_moved}
- Direction: {opportunity.direction}
- Price difference: {opportunity.price_difference:.2f}%
- Polymarket delay: {opportunity.polymarket_delay:.1f} seconds
- Current confidence: {opportunity.confidence:.3f}
- Recommended action: {opportunity.recommended_action}

MARKET DATA:
{json.dumps(market_data, indent=2)}

Please analyze:
1. Market momentum and trend strength
2. Volatility levels and risk factors  
3. Cross-exchange price divergences
4. Timing factors (is the delay optimal?)
5. Overall market sentiment

Provide:
- Enhanced confidence score (0.0-1.0)
- Key risk factors
- Recommended position sizing adjustment
- Brief reasoning (2-3 sentences)

Respond in JSON format:
{{
  "enhanced_confidence": 0.85,
  "risk_factors": ["high volatility", "late in session"],
  "position_adjustment": 1.2,
  "reasoning": "Strong momentum confirmed across exchanges..."
}}
"""
        return prompt
        
    def _create_pattern_analysis_prompt(self, market_data: Dict) -> str:
        """Create prompt for general pattern analysis"""
        
        prompt = f"""
Analyze current market patterns across exchanges:

MARKET DATA:
{json.dumps(market_data, indent=2)}

Identify:
1. Trend patterns (momentum, reversal, consolidation)
2. Volatility patterns (spikes, calm periods)
3. Cross-exchange arbitrage opportunities
4. Market sentiment indicators

Provide analysis in JSON format:
{{
  "market_sentiment": "bullish|bearish|neutral",
  "volatility_prediction": 0.75,
  "key_patterns": [
    {{
      "type": "momentum_build",
      "confidence": 0.8,
      "description": "Building upward momentum across exchanges"
    }}
  ],
  "trade_recommendations": ["watch for breakout", "expect volatility spike"],
  "overall_confidence": 0.85
}}
"""
        return prompt
        
    async def _query_claude(self, prompt: str) -> Optional[Dict]:
        """Query Claude API for analysis (mock implementation)"""
        
        # TODO: Implement actual Claude API integration
        # For now, return mock analysis to test the framework
        
        # Simulate API delay
        await asyncio.sleep(0.1)
        
        # Mock response based on prompt content
        if "enhanced_confidence" in prompt:
            return {
                "enhanced_confidence": 0.82,
                "risk_factors": ["moderate_volatility"],
                "position_adjustment": 1.1,
                "reasoning": "Market shows consistent momentum with low cross-exchange divergence"
            }
        else:
            return {
                "market_sentiment": "neutral",
                "volatility_prediction": 0.6,
                "key_patterns": [
                    {
                        "type": "consolidation",
                        "confidence": 0.7,
                        "description": "Price consolidating in narrow range"
                    }
                ],
                "trade_recommendations": ["wait for clear direction"],
                "overall_confidence": 0.75
            }
            
    def _parse_claude_response(self, response: Dict, original_confidence: float) -> float:
        """Parse Claude response and extract enhanced confidence"""
        
        try:
            enhanced = response.get('enhanced_confidence', original_confidence)
            
            # Apply bounds and sanity checks
            enhanced = max(0.0, min(1.0, enhanced))
            
            # Don't allow AI to boost confidence by more than 50%
            max_boost = original_confidence * 1.5
            enhanced = min(enhanced, max_boost)
            
            # Don't allow AI to reduce confidence by more than 30%
            min_confidence = original_confidence * 0.7
            enhanced = max(enhanced, min_confidence)
            
            return enhanced
            
        except Exception as e:
            logger.error(f"❌ Error parsing Claude response: {e}")
            return original_confidence
            
    def _parse_pattern_response(self, response: Dict) -> AIInsight:
        """Parse Claude pattern analysis response"""
        
        patterns = []
        for pattern_data in response.get('key_patterns', []):
            pattern = MarketPattern(
                pattern_type=pattern_data.get('type', 'unknown'),
                confidence=pattern_data.get('confidence', 0.5),
                description=pattern_data.get('description', ''),
                timeframe='current',
                indicators={},
                recommendation=''
            )
            patterns.append(pattern)
            
        return AIInsight(
            timestamp=time.time(),
            market_sentiment=response.get('market_sentiment', 'neutral'),
            volatility_prediction=response.get('volatility_prediction', 0.5),
            key_patterns=patterns,
            risk_assessment='medium',
            trade_recommendations=response.get('trade_recommendations', []),
            confidence=response.get('overall_confidence', 0.5)
        )
        
    async def _notify_callbacks(self, insight: AIInsight):
        """Notify callbacks about new AI insights"""
        for callback in self.callbacks:
            try:
                await callback(insight)
            except Exception as e:
                logger.error(f"❌ AI insight callback error: {e}")
                
    def get_latest_insight(self) -> Optional[AIInsight]:
        """Get the most recent AI insight"""
        return self.recent_insights[-1] if self.recent_insights else None
        
    def get_market_sentiment(self) -> str:
        """Get current market sentiment from latest analysis"""
        latest = self.get_latest_insight()
        return latest.market_sentiment if latest else 'unknown'