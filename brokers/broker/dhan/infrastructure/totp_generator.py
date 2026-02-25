"""
TOTP Generator for Dhan Authentication

Handles Time-based One-Time Password (TOTP) generation for Dhan API authentication.

Example:
    >>> from brokers.broker.dhan.infrastructure import TOTPGenerator
    >>> 
    >>> # Initialize with TOTP secret
    >>> generator = TOTPGenerator("your-totp-secret")
    >>> 
    >>> # Generate current TOTP code
    >>> code = generator.generate()
    >>> print(f"TOTP: {code}")
    >>> 
    >>> # Verify a TOTP code
    >>> is_valid = generator.verify(code)
"""

import time
from typing import Optional

try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False

from brokers.broker.dhan.domain import TOTP_TIME_WINDOW_SECONDS


class TOTPGenerationError(Exception):
    """Exception raised when TOTP generation fails."""
    pass


class TOTPGenerator:
    """
    Generates TOTP codes for Dhan authentication.
    
    Uses the TOTP secret key to generate time-based one-time passwords
    with support for time window offsets (for clock drift tolerance).
    
    Attributes:
        totp_secret: The TOTP secret key from Dhan.
    
    Example:
        >>> generator = TOTPGenerator("YBLE2EI76XJPILRA4W5UC6PAEXR2YK54")
        >>> code = generator.generate()  # Current time window
        >>> prev_code = generator.generate(window_offset=-1)  # Previous window
    """
    
    def __init__(self, totp_secret: str):
        """
        Initialize TOTP generator.
        
        Args:
            totp_secret: TOTP secret key from Dhan.
            
        Raises:
            ValueError: If totp_secret is empty or pyotp is not installed.
        """
        if not PYOTP_AVAILABLE:
            raise ImportError(
                "pyotp is required for TOTP generation. "
                "Install it with: pip install pyotp"
            )
        
        if not totp_secret or not totp_secret.strip():
            raise ValueError("TOTP secret cannot be empty")
        
        self.totp_secret = totp_secret
        self._totp = pyotp.TOTP(totp_secret)
    
    def generate(self, window_offset: int = 0) -> str:
        """
        Generate TOTP code from secret.
        
        Args:
            window_offset: Time window offset (-1 for previous, 0 for current, 1 for next).
                          Used for clock drift tolerance.
        
        Returns:
            TOTP code as string (6 digits).
            
        Raises:
            TOTPGenerationError: If TOTP generation fails.
            
        Example:
            >>> generator = TOTPGenerator("YBLE2EI76XJPILRA4W5UC6PAEXR2YK54")
            >>> code = generator.generate()  # Current time window
            >>> prev_code = generator.generate(window_offset=-1)  # Previous window
        """
        try:
            if window_offset == 0:
                return self._totp.now()
            else:
                time_window = int(time.time() // TOTP_TIME_WINDOW_SECONDS) + window_offset
                return self._totp.at(time_window)
        except Exception as e:
            raise TOTPGenerationError(f"Failed to generate TOTP code: {e}") from e
    
    def verify(self, code: str, window: int = 1) -> bool:
        """
        Verify a TOTP code.
        
        Args:
            code: TOTP code to verify.
            window: Number of time windows to check (default: 1).
        
        Returns:
            True if code is valid, False otherwise.
        """
        try:
            return self._totp.verify(code, valid_window=window)
        except Exception:
            return False
    
    def __repr__(self) -> str:
        """Return string representation."""
        return f"TOTPGenerator(secret='***')"
