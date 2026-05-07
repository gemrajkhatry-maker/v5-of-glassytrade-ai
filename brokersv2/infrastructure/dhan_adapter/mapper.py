"""
Instrument Mapper - Core domain infrastructure for symbol translation.

This is NOT a utility - it's core domain infrastructure that:
- Acts as exchange symbology engine
- Provides OMS identity layer
- Maintains hot-path low latency lookups
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, List
from threading import RLock

from brokersv2.core.types import (
    Exchange,
    SecurityId,
    InternalUid,
    IInstrumentMapper,
)
from brokersv2.domain.instrument.models import CanonicalInstrument


@dataclass
class BrokerInstrumentMapping:
    """Broker-specific mapping for a canonical instrument."""
    security_id: SecurityId
    exchange_segment: str
    broker_symbol: Optional[str] = None
    lot_size: Optional[int] = None
    tick_size: Optional[float] = None


class InstrumentMapper(IInstrumentMapper):
    """
    O(1) bidirectional instrument mapper.
    
    Core responsibilities:
    - security_id ↔ CanonicalInstrument translation
    - symbol + exchange → CanonicalInstrument
    - CanonicalInstrument → broker mappings
    
    All lookups are O(1) with lock-efficient access.
    """
    
    def __init__(self):
        # Primary bidirectional maps for O(1) lookups
        self._security_id_to_canonical: Dict[SecurityId, CanonicalInstrument] = {}
        self._canonical_to_security_id: Dict[InternalUid, SecurityId] = {}
        
        # Symbol-based lookup (exchange:symbol)
        self._symbol_to_canonical: Dict[str, CanonicalInstrument] = {}
        
        # Broker-specific mappings
        self._canonical_to_broker_mapping: Dict[InternalUid, BrokerInstrumentMapping] = {}
        
        # Reverse: WS symbol → canonical (for packet decoding)
        self._ws_symbol_to_canonical: Dict[str, CanonicalInstrument] = {}
        
        # Lock for thread-safe updates
        self._lock = RLock()
    
    def register(
        self,
        canonical: CanonicalInstrument,
        security_id: SecurityId,
        exchange_segment: str,
        broker_symbol: Optional[str] = None,
    ) -> None:
        """
        Register a canonical instrument with its broker mapping.
        
        This should be called during startup when loading the instrument master.
        """
        with self._lock:
            # Primary mappings
            self._security_id_to_canonical[security_id] = canonical
            self._canonical_to_security_id[canonical.internal_uid] = security_id
            
            # Symbol lookup
            self._symbol_to_canonical[f"{canonical.exchange.value}:{canonical.symbol}"] = canonical
            
            # Broker mapping
            self._canonical_to_broker_mapping[canonical.internal_uid] = BrokerInstrumentMapping(
                security_id=security_id,
                exchange_segment=exchange_segment,
                broker_symbol=broker_symbol or canonical.symbol,
                lot_size=canonical.lot_size,
            )
    
    def register_ws_symbol(
        self,
        ws_symbol: str,
        canonical: CanonicalInstrument,
    ) -> None:
        """Register websocket symbol to canonical mapping."""
        with self._lock:
            self._ws_symbol_to_canonical[ws_symbol] = canonical
    
    def canonical_to_security_id(self, instrument: CanonicalInstrument) -> Optional[SecurityId]:
        """Translate canonical instrument to broker security ID."""
        return self._canonical_to_security_id.get(instrument.internal_uid)
    
    def security_id_to_canonical(self, security_id: SecurityId) -> Optional[CanonicalInstrument]:
        """Translate broker security ID to canonical instrument."""
        return self._security_id_to_canonical.get(security_id)
    
    def symbol_to_canonical(self, symbol: str, exchange: Exchange) -> Optional[CanonicalInstrument]:
        """Translate symbol/exchange to canonical instrument."""
        return self._symbol_to_canonical.get(f"{exchange.value}:{symbol.upper()}")
    
    def canonical_to_broker_mapping(self, instrument: CanonicalInstrument) -> Optional[BrokerInstrumentMapping]:
        """Get full broker-specific mapping for instrument."""
        return self._canonical_to_broker_mapping.get(instrument.internal_uid)
    
    def ws_symbol_to_canonical(self, ws_symbol: str) -> Optional[CanonicalInstrument]:
        """Translate websocket symbol to canonical instrument."""
        return self._ws_symbol_to_canonical.get(ws_symbol)
    
    def get_all_instruments(self) -> List[CanonicalInstrument]:
        """Get all registered instruments."""
        return list(self._security_id_to_canonical.values())
    
    def clear(self) -> None:
        """Clear all mappings (for testing/reinitialization)."""
        with self._lock:
            self._security_id_to_canonical.clear()
            self._canonical_to_security_id.clear()
            self._symbol_to_canonical.clear()
            self._canonical_to_broker_mapping.clear()
            self._ws_symbol_to_canonical.clear()


class InstrumentRegistry:
    """
    Instrument registry for managing master instrument list.
    
    Handles loading from CSV, NSE/BSE file, or API.
    """
    
    def __init__(self, mapper: InstrumentMapper):
        self._mapper = mapper
        self._loaded = False
    
    def load_from_csv(self, csv_path: str) -> int:
        """
        Load instruments from CSV file.
        
        Expected CSV format:
        security_id,symbol,exchange,segment,instrument_type,expiry,strike,option_type,lot_size,tick_size
        """
        import csv
        from datetime import datetime
        from decimal import Decimal
        from brokersv2.core.types import Segment, InstrumentType, OptionType
        
        count = 0
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                canonical = CanonicalInstrument(
                    internal_uid=InternalUid(f"csv-{row['security_id']}"),
                    symbol=row['symbol'],
                    exchange=Exchange(row['exchange']),
                    segment=Segment(row['segment']),
                    instrument_type=InstrumentType(row['instrument_type']),
                    lot_size=int(row.get('lot_size', 1)),
                    tick_size=Decimal(row.get('tick_size', '0.01')),
                    expiry=datetime.strptime(row['expiry'], '%Y-%m-%d').date() if row.get('expiry') else None,
                    strike=Decimal(row['strike']) if row.get('strike') else None,
                    option_type=OptionType(row['option_type']) if row.get('option_type') else None,
                )
                
                self._mapper.register(
                    canonical=canonical,
                    security_id=SecurityId(row['security_id']),
                    exchange_segment=row.get('exchange_segment', ''),
                    broker_symbol=row.get('broker_symbol'),
                )
                count += 1
        
        self._loaded = True
        return count
    
    def load_static_nse(self) -> int:
        """Load static NSE instrument list."""
        from decimal import Decimal
        
        count = 0
        # Common NSE equities
        equities = [
            ("RELIANCE", 1, Decimal("0.01")),
            ("TCS", 1, Decimal("0.01")),
            ("INFY", 1, Decimal("0.01")),
            ("HDFCBANK", 1, Decimal("0.01")),
            ("ICICIBANK", 1, Decimal("0.01")),
            ("KOTAKBANK", 1, Decimal("0.01")),
            ("AXISBANK", 1, Decimal("0.01")),
            ("SBIN", 1, Decimal("0.01")),
            ("NIFTY", 25, Decimal("0.01")),
            ("BANKNIFTY", 15, Decimal("0.01")),
        ]
        
        for symbol, lot_size, tick_size in equities:
            canonical = CanonicalInstrument.create_equity(
                symbol=symbol,
                exchange=Exchange.NSE,
                lot_size=lot_size,
                tick_size=tick_size,
            )
            
            # Security IDs would come from actual master
            # Using placeholder for demonstration
            security_id = SecurityId(f"NSE_EQ_{symbol}")
            self._mapper.register(
                canonical=canonical,
                security_id=security_id,
                exchange_segment="NSE_EQ" if symbol not in ("NIFTY", "BANKNIFTY") else "NSE_INDEX",
            )
            count += 1
        
        self._loaded = True
        return count