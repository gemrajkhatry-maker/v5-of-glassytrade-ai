"""
Idempotency Manager for OMS.

Prevents duplicate order submissions:
- Idempotency key tracking
- Request deduplication
- Response caching
- TTL-based cleanup
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from brokersv2.core.constants import Idempotency

logger = logging.getLogger(__name__)


class IdempotencyStatus(Enum):
    """Status of an idempotent request."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IdempotencyRecord:
    """Record of an idempotent request."""
    
    idempotency_key: str
    request_hash: str
    status: IdempotencyStatus = IdempotencyStatus.PENDING
    response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    request_count: int = 1
    
    @property
    def age(self) -> float:
        """Age of record in seconds."""
        return time.time() - self.created_at
    
    @property
    def is_stale(self) -> bool:
        """Check if record is stale (> 1 hour)."""
        return self.age > Idempotency.DEFAULT_TTL


class IdempotencyManager:
    """
    Manages idempotency for order operations.
    
    Prevents duplicate order submissions when:
    - Network timeout causes retry
    - User clicks submit multiple times
    - System retries failed requests
    
    Usage:
        manager = IdempotencyManager()
        
        # Before submitting order
        if manager.is_duplicate(idempotency_key, request_data):
            # Return cached response
            return manager.get_cached_response(idempotency_key)
        
        # Submit order
        result = await submit_order(request_data)
        
        # Record result
        manager.record_completion(idempotency_key, result)
    """
    
    def __init__(self, max_records: int = None):
        self._records: Dict[str, IdempotencyRecord] = {}
        self._max_records = max_records or Idempotency.DEFAULT_MAX_RECORDS
    
    def generate_idempotency_key(
        self,
        user_id: str,
        symbol: str,
        side: str,
        quantity: int,
        timestamp: Optional[float] = None,
    ) -> str:
        """
        Generate idempotency key from order parameters.
        
        Args:
            user_id: User identifier
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Order quantity
            timestamp: Optional timestamp
            
        Returns:
            Unique idempotency key
        """
        if timestamp is None:
            timestamp = time.time()
        
        # Create deterministic string
        key_string = f"{user_id}:{symbol}:{side}:{quantity}:{int(timestamp)}"
        
        # Hash it
        return hashlib.sha256(key_string.encode()).hexdigest()[:16]
    
    def is_duplicate(
        self,
        idempotency_key: str,
        request_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Check if request is a duplicate.
        
        Args:
            idempotency_key: Unique key for request
            request_data: Optional request data for hash verification
            
        Returns:
            True if duplicate and completed
        """
        record = self._records.get(idempotency_key)
        
        if not record:
            return False
        
        # Check if request completed
        if record.status == IdempotencyStatus.COMPLETED:
            record.request_count += 1
            logger.info(
                f"Duplicate request detected: {idempotency_key} "
                f"(request #{record.request_count})"
            )
            return True
        
        # If pending, check if it's a concurrent duplicate
        if record.status == IdempotencyStatus.PENDING:
            # First check (request_count == 1) is the original request
            if record.request_count == 1:
                return False
            # Subsequent checks are duplicates
            record.request_count += 1
            logger.warning(
                f"Concurrent duplicate request: {idempotency_key} "
                f"(request #{record.request_count})"
            )
            return True
        
        return False
    
    def record_pending(self, idempotency_key: str, request_data: Optional[Dict[str, Any]] = None) -> None:
        """
        Record a pending request.
        
        Args:
            idempotency_key: Unique key for request
            request_data: Optional request data
        """
        request_hash = ""
        if request_data:
            request_hash = hashlib.md5(
                str(request_data).encode()
            ).hexdigest()
        
        self._records[idempotency_key] = IdempotencyRecord(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status=IdempotencyStatus.PENDING,
        )
        
        # Enforce max records
        if len(self._records) > self._max_records:
            self._cleanup_stale()
    
    def record_completion(
        self,
        idempotency_key: str,
        response: Dict[str, Any],
    ) -> None:
        """
        Record successful completion.
        
        Args:
            idempotency_key: Unique key for request
            response: Response data to cache
        """
        record = self._records.get(idempotency_key)
        if not record:
            logger.warning(
                f"Completing unknown idempotency key: {idempotency_key}"
            )
            # Create record anyway
            self.record_pending(idempotency_key)
            record = self._records[idempotency_key]
        
        record.status = IdempotencyStatus.COMPLETED
        record.response = response
        record.completed_at = time.time()
        
        logger.debug(
            f"Request completed: {idempotency_key} "
            f"response_keys={list(response.keys())}"
        )
    
    def record_failure(
        self,
        idempotency_key: str,
        error: str,
    ) -> None:
        """
        Record failed request.
        
        Args:
            idempotency_key: Unique key for request
            error: Error message
        """
        record = self._records.get(idempotency_key)
        if not record:
            logger.warning(
                f"Failing unknown idempotency key: {idempotency_key}"
            )
            self.record_pending(idempotency_key)
            record = self._records[idempotency_key]
        
        record.status = IdempotencyStatus.FAILED
        record.error = error
        record.completed_at = time.time()
    
    def get_cached_response(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """
        Get cached response for duplicate request.
        
        Args:
            idempotency_key: Unique key for request
            
        Returns:
            Cached response or None
        """
        record = self._records.get(idempotency_key)
        if not record:
            return None
        
        if record.status != IdempotencyStatus.COMPLETED:
            return None
        
        return record.response
    
    def get_record(self, idempotency_key: str) -> Optional[IdempotencyRecord]:
        """Get idempotency record."""
        return self._records.get(idempotency_key)
    
    def cleanup_stale(self) -> int:
        """
        Remove stale records.
        
        Returns:
            Number of records removed
        """
        return self._cleanup_stale()
    
    def _cleanup_stale(self) -> int:
        """Internal cleanup of stale records."""
        stale_keys = [
            key
            for key, record in self._records.items()
            if record.is_stale or record.status == IdempotencyStatus.FAILED
        ]
        
        for key in stale_keys:
            del self._records[key]
        
        if stale_keys:
            logger.debug(f"Cleaned up {len(stale_keys)} stale idempotency records")
        
        return len(stale_keys)
    
    def get_status(self) -> Dict[str, Any]:
        """Get idempotency manager status."""
        return {
            "total_records": len(self._records),
            "pending": sum(
                1 for r in self._records.values()
                if r.status == IdempotencyStatus.PENDING
            ),
            "completed": sum(
                1 for r in self._records.values()
                if r.status == IdempotencyStatus.COMPLETED
            ),
            "failed": sum(
                1 for r in self._records.values()
                if r.status == IdempotencyStatus.FAILED
            ),
        }
