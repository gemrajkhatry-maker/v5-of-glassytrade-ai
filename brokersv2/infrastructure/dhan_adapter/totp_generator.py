"""
TOTP Generator - Time-based One-Time Password generation.

Implements RFC 6238 standard for TOTP using pyotp library.
Used for Dhan API authentication.
"""

from __future__ import annotations

import time
from typing import Optional

import pyotp


class TOTPGenerationError(Exception):
    """Raised when TOTP generation fails."""
    
    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.__cause__ = cause


class TOTPGenerator:
    """
    Generates Time-based One-Time Passwords (TOTP) for Dhan authentication.
    
    TOTP codes are 6-digit codes that change every 30 seconds based on
    a shared secret and current time (RFC 6238).
    
    Example:
        >>> generator = TOTPGenerator("JBSWY3DPEHPK3PXP")
        >>> code = generator.generate_code()
        >>> print(code)  # "123456"
    """
    
    # TOTP interval in seconds (standard is 30 seconds)
    INTERVAL = 30
    
    def __init__(self, secret: str):
        """
        Initialize TOTP generator.
        
        Args:
            secret: Base32-encoded secret key (from Dhan TOTP setup)
            
        Raises:
            TOTPGenerationError: If secret is invalid
        """
        # Validate and normalize secret
        if not secret or not secret.strip():
            raise TOTPGenerationError("TOTP secret cannot be empty")
        
        self.secret = secret.strip()
        
        # Validate it's a valid Base32 secret by attempting to create TOTP
        try:
            self._totp = pyotp.TOTP(self.secret, interval=self.INTERVAL)
        except Exception as e:
            raise TOTPGenerationError(f"Invalid TOTP secret: {e}", cause=e)
    
    def generate_code(self) -> str:
        """
        Generate current TOTP code.
        
        Returns:
            6-digit TOTP code as string (preserves leading zeros)
            
        Raises:
            TOTPGenerationError: If code generation fails
        """
        try:
            code = self._totp.now()
            return code
        except Exception as e:
            raise TOTPGenerationError(f"Failed to generate TOTP code: {e}", cause=e)
    
    def get_current_window(self) -> int:
        """
        Get current time window number.
        
        Returns:
            Integer window number (floor(current_time / 30))
        """
        return int(time.time() // self.INTERVAL)
    
    def verify_code(self, code: str, valid_windows: int = 1) -> bool:
        """
        Verify a TOTP code with drift tolerance.
        
        Args:
            code: 6-digit code to verify
            valid_windows: Number of time windows to check (±drift)
                          0 = exact match only
                          1 = allow ±1 window (30s drift)
                          
        Returns:
            True if code is valid
        """
        try:
            return self._totp.verify(code, valid_window=valid_windows)
        except Exception:
            return False
