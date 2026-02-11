"""
Configuration management for the trading bot
"""

import yaml
from dataclasses import dataclass, field
from typing import List, Dict, Any
from pathlib import Path


@dataclass
class TradingConfig:
    """Trading-specific configuration"""
    paper_mode: bool = True
    initial_capital: float = 10000.0
    daily_target: float = 98000.0  # Target $98K/day like 0x8dxd
    max_position_size: float = 5000.0  # Max $5K per trade
    min_edge_threshold: float = 0.02  # Minimum 2% edge to trade
    max_trades_per_hour: int = 50
    risk_per_trade: float = 0.01  # 1% of capital per trade
    
    # Polymarket specific
    polymarket_delay_threshold: float = 2.0  # Seconds of delay to exploit
    bitcoin_market_focus: bool = True
    market_timeframes: List[str] = field(default_factory=lambda: ["15min", "1hour"])


@dataclass  
class DataConfig:
    """Data source configuration"""
    exchanges: List[str] = field(default_factory=lambda: [
        "binance", "coinbase", "kraken", "bybit"
    ])
    prediction_markets: List[str] = field(default_factory=lambda: [
        "polymarket", "kalshi", "manifold"
    ])
    update_interval: float = 0.1  # 100ms updates
    
    # API Keys (loaded from env)
    coinbase_api_key: str = ""
    binance_api_key: str = ""
    polymarket_api_key: str = ""


@dataclass
class AIConfig:
    """AI/ML configuration"""
    claude_model: str = "claude-3-sonnet-20240229"
    openai_model: str = "gpt-4-turbo-preview"
    prediction_confidence_threshold: float = 0.8
    pattern_analysis_enabled: bool = True
    sentiment_analysis_enabled: bool = True
    
    # Feature flags
    use_claude_for_patterns: bool = True
    use_gpt4_for_sentiment: bool = True
    enable_cross_market_analysis: bool = True


@dataclass
class MonitoringConfig:
    """Monitoring and alerting configuration"""
    enable_prometheus: bool = True
    enable_discord_alerts: bool = True
    log_level: str = "INFO"
    max_log_files: int = 10
    
    # Alert thresholds
    max_drawdown_alert: float = 0.05  # 5% drawdown alert
    win_rate_alert_threshold: float = 0.8  # Alert if win rate < 80%


@dataclass
class BotConfig:
    """Main bot configuration"""
    trading: TradingConfig = field(default_factory=TradingConfig)
    data: DataConfig = field(default_factory=DataConfig) 
    ai: AIConfig = field(default_factory=AIConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    
    @classmethod
    def from_file(cls, path: str) -> "BotConfig":
        """Load configuration from YAML file"""
        config_path = Path(path)
        
        if not config_path.exists():
            # Create default config if it doesn't exist
            default_config = cls()
            default_config.save(path)
            return default_config
            
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
            
        return cls(
            trading=TradingConfig(**data.get('trading', {})),
            data=DataConfig(**data.get('data', {})),
            ai=AIConfig(**data.get('ai', {})),
            monitoring=MonitoringConfig(**data.get('monitoring', {}))
        )
    
    def save(self, path: str):
        """Save configuration to YAML file"""
        config_path = Path(path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'trading': self.trading.__dict__,
            'data': self.data.__dict__,
            'ai': self.ai.__dict__,
            'monitoring': self.monitoring.__dict__
        }
        
        with open(config_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, indent=2)