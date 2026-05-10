"""
DhanHQ v2 Factory - Auto-loads credentials from environment and creates connections.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

from brokersv2.infrastructure.dhan_adapter.client import DhanConfig, DhanHttpClient
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
from brokersv2.infrastructure.rate_limiter.token_bucket import RateLimiter

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """Auto-load .env file from project root."""
    try:
        from dotenv import load_dotenv
        # Walk up from current directory to find .env
        cwd = Path.cwd()
        for path in [cwd] + list(cwd.parents):
            env_file = path / ".env"
            if env_file.exists():
                load_dotenv(env_file)
                logger.debug(f"Loaded .env from {env_file}")
                return
    except ImportError:
        pass  # dotenv not installed, use system env only


@dataclass
class DhanGatewayConfig:
    """Gateway configuration with defaults from environment."""
    client_id: str
    access_token: str
    base_url: str = "https://api.dhan.co"
    ws_url: str = "wss://api.dhan.co/ws"
    timeout: int = 30
    enable_ws: bool = True
    rate_limits: Optional[Dict[str, float]] = None
    
    @classmethod
    def from_env(cls, prefix: str = "DHAN_") -> DhanGatewayConfig:
        """Create config from environment variables."""
        _load_dotenv()
        
        client_id = os.environ.get(f"{prefix}CLIENT_ID")
        access_token = os.environ.get(f"{prefix}ACCESS_TOKEN")
        
        if not client_id:
            raise ValueError(f"Missing required environment variable: {prefix}CLIENT_ID")
        if not access_token:
            # Check for TOTP+PIN fallback
            totp_secret = os.environ.get(f"{prefix}TOTP_SECRET") or os.environ.get("TOTP_SECRET", "")
            pin = os.environ.get(f"{prefix}PIN") or os.environ.get("PIN", "")
            if not (totp_secret and pin):
                raise ValueError(
                    f"Missing required environment variable: {prefix}ACCESS_TOKEN. "
                    f"Either set it or provide {prefix}TOTP_SECRET + {prefix}PIN for auto-generation."
                )
            # Could auto-generate token, but for now use empty
            access_token = ""
        
        return cls(
            client_id=client_id,
            access_token=access_token,
            base_url=os.environ.get(f"{prefix}BASE_URL", "https://api.dhan.co"),
            ws_url=os.environ.get(f"{prefix}WS_URL", "wss://api.dhan.co/ws"),
            timeout=int(os.environ.get(f"{prefix}TIMEOUT", "30")),
            enable_ws=os.environ.get(f"{prefix}ENABLE_WS", "true").lower() == "true",
        )


class DhanFactory:
    """
    Factory for creating DhanHQ connections with auto-loaded credentials.
    
    Usage:
        factory = DhanFactory.from_env()  # Auto-load from .env
        gateway = factory.create_gateway()
        async with gateway:
            quote = await gateway.get_quote("NSE:RELIANCE")
    """
    
    def __init__(self, config: DhanGatewayConfig):
        self._config = config
        self._rate_limiter = RateLimiter()
        self._mapper: Optional[InstrumentMapper] = None
    
    @classmethod
    def from_env(cls, prefix: str = "DHAN_", **kwargs) -> DhanFactory:
        """
        Create factory with credentials auto-loaded from environment.
        
        Args:
            prefix: Environment variable prefix (default: DHAN_)
            **kwargs: Override config values
        
        Returns:
            Configured DhanFactory instance
        """
        config = DhanGatewayConfig.from_env(prefix=prefix)
        return cls(config)
    
    def with_config(self, **overrides) -> DhanFactory:
        """Return new factory with config overrides."""
        new_config = DhanGatewayConfig(
            client_id=overrides.get("client_id", self._config.client_id),
            access_token=overrides.get("access_token", self._config.access_token),
            base_url=overrides.get("base_url", self._config.base_url),
            ws_url=overrides.get("ws_url", self._config.ws_url),
            timeout=overrides.get("timeout", self._config.timeout),
            enable_ws=overrides.get("enable_ws", self._config.enable_ws),
        )
        return DhanFactory(new_config)
    
    async def create_gateway(self, enable_ws: Optional[bool] = None) -> DhanGateway:
        """
        Create a DhanGateway with configured connection.
        
        Args:
            enable_ws: Override websocket enabled flag
        
        Returns:
            DhanGateway instance ready for use
        """
        use_ws = enable_ws if enable_ws is not None else self._config.enable_ws
        
        # NEW: Check if we need to auto-generate token
        access_token = self._config.access_token
        auth_provider = None
        
        if not access_token:
            # Try to get TOTP credentials from environment
            totp_secret = os.environ.get("DHAN_TOTP_SECRET") or os.environ.get("TOTP_SECRET", "")
            pin = os.environ.get("DHAN_PIN") or os.environ.get("PIN", "")
            
            if totp_secret and pin:
                # Create auth provider and generate token
                from brokersv2.infrastructure.dhan_adapter.auth_provider import DhanAuthProvider
                auth_provider = DhanAuthProvider(
                    client_id=self._config.client_id,
                    env_file=str(Path.cwd() / ".env"),
                )
                auth_provider.set_totp_secret(totp_secret)
                auth_provider.set_pin(pin)
                
                # Generate token
                access_token = await auth_provider.generate_token(pin, totp_secret)
                logger.info("Auto-generated Dhan access token via TOTP")
            else:
                raise ValueError(
                    f"No access token available. Set DHAN_ACCESS_TOKEN or "
                    f"DHAN_TOTP_SECRET + DHAN_PIN for auto-generation."
                )
        
        # Create gateway with (possibly) new token and auth provider
        gateway = DhanGateway(
            config=self._config,
            rate_limiter=self._rate_limiter,
            enable_ws=use_ws,
            access_token_override=access_token,  # NEW: Pass generated token
            auth_provider=auth_provider,  # NEW: Pass auth provider
        )
        
        return gateway
    
    async def gateway(self, **kw) -> DhanGateway:
        """Async context manager for gateway."""
        gw = self.create_gateway(**kw)
        return gw


class DhanGateway:
    """
    Gateway for DhanHQ v2 API operations.
    
    Provides a clean interface for all broker operations with automatic
    connection management and credential handling.
    
    Usage:
        async with DhanGateway.from_env() as gw:
            df = await gw.historical("NSE:RELIANCE", "2024-01-01", "2024-01-31")
    """
    
    def __init__(
        self,
        config: DhanGatewayConfig,
        rate_limiter: Optional[RateLimiter] = None,
        enable_ws: bool = True,
        access_token_override: Optional[str] = None,  # NEW: Generated token
        auth_provider=None,  # NEW: Auth provider for token refresh
    ):
        self._config = config
        self._auth_provider = auth_provider  # NEW: Store auth provider
        
        # NEW: Use generated token if provided
        final_token = access_token_override or config.access_token
        
        self._client = DhanHttpClient(
            DhanConfig(
                client_id=config.client_id,
                access_token=final_token,
                base_url=config.base_url,
                ws_url=config.ws_url,
                timeout=config.timeout,
            ),
            rate_limiter=rate_limiter,
            auth_provider=auth_provider,  # NEW: Wire auth provider into client
        )
        self._rate_limiter = rate_limiter or RateLimiter()
        self._mapper = InstrumentMapper()
        self._ws_manager = None
        self._enable_ws = enable_ws
        self._initialized = False
    
    @classmethod
    async def from_env(cls, prefix: str = "DHAN_") -> DhanGateway:
        """Create gateway with auto-loaded credentials from environment."""
        factory = DhanFactory.from_env(prefix=prefix)
        return await factory.create_gateway()
    
    async def __aenter__(self) -> DhanGateway:
        """Initialize connection on context entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Clean up connection on context exit."""
        await self.close()
    
    async def initialize(self) -> None:
        """Initialize mapper and websocket connection."""
        if self._initialized:
            return
        
        # Initialize instrument mapper with broker data
        # This would load the master contract file
        logger.info(f"DhanGateway initialized for client {self._config.client_id[:4]}...")
        self._initialized = True
    
    async def close(self) -> None:
        """Close all connections."""
        await self._client.close()
        if self._ws_manager:
            await self._ws_manager.close()
        self._initialized = False
    
    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get quote for a symbol.
        
        Args:
            symbol: Canonical symbol (e.g., "NSE:RELIANCE")
        
        Returns:
            Quote data dict with LTP, bid, ask, volume, etc.
        """
        from brokersv2.domain.instrument.models import CanonicalInstrument
        
        # Parse canonical symbol
        instrument = CanonicalInstrument.from_symbol(symbol)
        
        # Use HTTP client to fetch real quote
        quote = await self._client.get_quote(
            instrument=instrument,
            mapper=self._mapper,
        )
        
        # Convert Quote object to dict for compatibility
        return {
            "symbol": symbol,
            "security_id": self._mapper.canonical_to_broker_mapping(instrument).security_id,
            "ltp": quote.ltp,
            "bid": quote.bid,
            "ask": quote.ask,
            "volume": quote.volume,
            "open": quote.open,
            "high": quote.high,
            "low": quote.low,
            "close": quote.close,
            "oi": quote.oi,
            "timestamp": quote.timestamp.isoformat() if quote.timestamp else None,
        }
    
    async def historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> list:
        """
        Get historical data.
        
        Args:
            symbol: Symbol (e.g., "TCS", "NIFTY", "CRUDEOIL")
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            interval: "1m", "5m", "15m", "25m", "60", "1d"
        
        Returns:
            List of candle dicts
        """
        from brokersv2.domain.instrument.models import CanonicalInstrument
        
        # Parse symbol to instrument
        instrument = CanonicalInstrument.from_symbol(symbol)
        
        # Map interval format: "1m"->"1", "5m"->"5", "15m"->"15", "1h"->"60", "1d"->"1d"
        interval_map = {
            "1m": "1", "5m": "5", "15m": "15", "25m": "25", 
            "1h": "60", "60": "60", "1d": "1d"
        }
        dhan_interval = interval_map.get(interval, interval)
        
        # Call the HTTP client
        candles = await self._client.get_historical(
            instrument=instrument,
            from_date=from_date,
            to_date=to_date,
            interval=dhan_interval,
            mapper=self._mapper,
        )
        
        # Convert Candle objects to dicts for CLI
        return [
            {
                "timestamp": c.timestamp,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
            }
            for c in candles
        ]
    
    async def option_chain(
        self,
        underlying: str,
        expiry_index: int = 0,
    ) -> Dict[str, Any]:
        """Get option chain for underlying.
        
        Args:
            underlying: Underlying symbol (e.g., "NIFTY")
            expiry_index: Expiry index (0=current, 1=near, 2=far)
        
        Returns:
            Option chain data with strikes, Greeks, OI, etc.
        """
        # Call real client method to fetch option chain
        chain_data = await self._client.get_option_chain(
            symbol=underlying,
            exchange="NSE",  # Default exchange
            expiry_index=expiry_index,
            mapper=self._mapper,
        )
        
        return chain_data
    
    async def get_expiry_list(self, underlying: str) -> list:
        """Get list of expiry dates for an underlying.
        
        Args:
            underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
        
        Returns:
            List of expiry date strings (e.g., ["2024-01-25", "2024-02-22"])
        """
        from brokersv2.domain.instrument.models import CanonicalInstrument
        
        # Resolve security ID via mapper
        instrument = CanonicalInstrument.from_symbol(underlying)
        mapping = self._mapper.canonical_to_broker_mapping(instrument)
        
        if not mapping:
            raise ValueError(f"Cannot resolve security_id for {underlying}")
        
        # Call expiry list endpoint directly
        expiry_payload = {
            "UnderlyingScrip": int(mapping.security_id) if mapping.security_id.isdigit() else mapping.security_id,
            "UnderlyingSeg": mapping.exchange_segment,
        }
        
        expiry_data = await self._client._request(
            "POST",
            "/optionchain/expirylist",
            bucket="non_trading",
            json=expiry_payload,
        )
        
        # Parse expiry list from response
        expiries = expiry_data.get("data", [])
        if isinstance(expiries, dict):
            expiries = expiries.get("data", [])
        
        return expiries

    async def quote(self, symbol: str) -> Dict[str, Any]:
        """
        Alias for get_quote() — matches CLI call pattern.

        Args:
            symbol: Canonical symbol string (e.g. "NSE:RELIANCE" or bare "RELIANCE")
        """
        return await self.get_quote(symbol)