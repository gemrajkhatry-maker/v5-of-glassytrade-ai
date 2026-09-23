"""
OHLC Data Validator

Validates OHLC (Open, High, Low, Close) data integrity with comprehensive checks.

CRITICAL: Prevents corrupt data from entering trading decisions.
PRODUCTION-SAFE: Explicit failures, no silent corruption.
"""

from typing import List

import numpy as np
import pandas as pd

from brokers.broker.logging import get_logger

logger = get_logger("validation")


class DataIntegrityError(Exception):
    """Raised when OHLC data fails validation checks."""

    pass


class OHLCValidator:
    """
    Validates OHLC data integrity.

    Performs comprehensive sanity checks:
    - Required columns present
    - High >= Low, Open, Close
    - Low <= Open, High, Close
    - Volume >= 0
    - No duplicate timestamps
    - No NaN/inf values

    FAIL LOUDLY: Production-safe validation.
    """

    @staticmethod
    def validate(df: pd.DataFrame, symbol: str) -> List[str]:
        """
        Validate OHLC data and return list of errors.

        Args:
            df: DataFrame with OHLC data
            symbol: Symbol name for error messages

        Returns:
            List of validation error messages (empty if valid)

        Example:
            errors = OHLCValidator.validate(df, "RELIANCE")
            if errors:
                print(f"Validation failed: {errors}")
        """
        errors = []

        # Check 1: Required columns
        required_columns = ["open", "high", "low", "close", "volume"]
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            errors.append(f"Missing required columns: {missing_columns}")
            logger.error(
                f"OHLC validation failed for {symbol}: missing columns {missing_columns}"
            )
            return errors  # Cannot validate further without required columns

        # Check 2: Non-empty DataFrame
        if len(df) == 0:
            errors.append("DataFrame is empty")
            return errors

        # Check 3: OHLC sanity checks
        for idx, row in df.iterrows():
            row_errors = []

            # High must be >= Low
            if row["high"] < row["low"]:
                row_errors.append(f"High ({row['high']:.2f}) < Low ({row['low']:.2f})")

            # High must be >= Open
            if row["high"] < row["open"]:
                row_errors.append(
                    f"High ({row['high']:.2f}) < Open ({row['open']:.2f})"
                )

            # High must be >= Close
            if row["high"] < row["close"]:
                row_errors.append(
                    f"High ({row['high']:.2f}) < Close ({row['close']:.2f})"
                )

            # Low must be <= Open
            if row["low"] > row["open"]:
                row_errors.append(f"Low ({row['low']:.2f}) > Open ({row['open']:.2f})")

            # Low must be <= Close
            if row["low"] > row["close"]:
                row_errors.append(
                    f"Low ({row['low']:.2f}) > Close ({row['close']:.2f})"
                )

            # Volume must be non-negative
            if row["volume"] < 0:
                row_errors.append(f"Negative volume ({row['volume']})")

            # Check for NaN or inf values
            for col in ["open", "high", "low", "close", "volume"]:
                if pd.isna(row[col]):
                    row_errors.append(f"{col} is NaN")
                elif np.isinf(row[col]):
                    row_errors.append(f"{col} is inf")

            # Aggregate row errors
            if row_errors:
                timestamp = row.get("timestamp", idx)
                errors.append(
                    f"Row {idx} (timestamp={timestamp}): {'; '.join(row_errors)}"
                )

        # Check 4: Duplicate timestamps
        if "timestamp" in df.columns:
            duplicate_count = df["timestamp"].duplicated().sum()
            if duplicate_count > 0:
                duplicates = df[df["timestamp"].duplicated(keep=False)][
                    "timestamp"
                ].tolist()
                errors.append(
                    f"Found {duplicate_count} duplicate timestamps: {duplicates[:5]}{'...' if len(duplicates) > 5 else ''}"
                )

        # Check 5: Chronological order (if timestamp present)
        if "timestamp" in df.columns and len(df) > 1:
            df_sorted = df.sort_values("timestamp")
            if not df.index.equals(df_sorted.index):
                errors.append("Timestamps are not in chronological order")

        # Log results
        if errors:
            logger.warning(
                f"OHLC validation found {len(errors)} issues for {symbol}",
                extra={"symbol": symbol, "error_count": len(errors)},
            )
        else:
            logger.debug(
                f"OHLC validation passed for {symbol} ({len(df)} candles)",
                extra={"symbol": symbol, "candle_count": len(df)},
            )

        return errors

    @staticmethod
    def validate_or_raise(df: pd.DataFrame, symbol: str) -> None:
        """
        Validate OHLC data and raise DataIntegrityError if invalid.

        FAIL LOUDLY: Production-safe - raises exception on corrupt data.

        Args:
            df: DataFrame with OHLC data
            symbol: Symbol name for error messages

        Raises:
            DataIntegrityError: If validation fails

        Example:
            try:
                OHLCValidator.validate_or_raise(df, "RELIANCE")
                # Safe to use df for trading decisions
            except DataIntegrityError as e:
                logger.error(f"Corrupt OHLC data: {e}")
        """
        errors = OHLCValidator.validate(df, symbol)

        if errors:
            error_msg = (
                f"OHLC validation failed for {symbol}. "
                f"Found {len(errors)} integrity issues:\n"
                + "\n".join(f"  {i + 1}. {err}" for i, err in enumerate(errors[:10]))
            )

            if len(errors) > 10:
                error_msg += f"\n  ... and {len(errors) - 10} more errors"

            logger.error(
                f"Data integrity check failed for {symbol}",
                extra={"symbol": symbol, "errors": errors},
            )

            raise DataIntegrityError(error_msg)

    @staticmethod
    def is_valid(df: pd.DataFrame, symbol: str) -> bool:
        """
        Check if OHLC data is valid (returns boolean).

        Args:
            df: DataFrame with OHLC data
            symbol: Symbol name for error messages

        Returns:
            True if valid, False otherwise

        Example:
            if OHLCValidator.is_valid(df, "RELIANCE"):
                # Process data
            else:
                # Handle invalid data
        """
        errors = OHLCValidator.validate(df, symbol)
        return len(errors) == 0

    @staticmethod
    def fix_common_issues(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Attempt to fix common OHLC data issues.

        Fixes applied:
        - Remove duplicate timestamps (keep first)
        - Sort by timestamp
        - Replace NaN values with forward fill
        - Replace inf values with NaN, then forward fill

        Args:
            df: DataFrame with OHLC data
            symbol: Symbol name for logging

        Returns:
            Fixed DataFrame (may still have issues)

        Example:
            df_fixed = OHLCValidator.fix_common_issues(df, "RELIANCE")
            # Check if fixes resolved all issues
            if not OHLCValidator.is_valid(df_fixed, "RELIANCE"):
                logger.error("Could not fix all data issues")
        """
        df = df.copy()
        fixes_applied = []

        # Fix 1: Remove duplicates
        if "timestamp" in df.columns:
            before_count = len(df)
            df = df.drop_duplicates(subset=["timestamp"], keep="first")
            if len(df) < before_count:
                fixes_applied.append(
                    f"Removed {before_count - len(df)} duplicate timestamps"
                )

        # Fix 2: Sort by timestamp
        if "timestamp" in df.columns:
            df = df.sort_values("timestamp")
            fixes_applied.append("Sorted by timestamp")

        # Fix 3: Handle NaN/inf values
        required_columns = ["open", "high", "low", "close", "volume"]
        for col in required_columns:
            if col in df.columns:
                # Replace inf with NaN
                inf_count = np.isinf(df[col]).sum()
                if inf_count > 0:
                    df[col] = df[col].replace([np.inf, -np.inf], np.nan)
                    fixes_applied.append(f"Replaced {inf_count} inf values in {col}")

                # Forward fill NaN values
                nan_count = df[col].isna().sum()
                if nan_count > 0:
                    df[col] = df[col].ffill()
                    fixes_applied.append(
                        f"Forward-filled {nan_count} NaN values in {col}"
                    )

        if fixes_applied:
            logger.info(f"Applied fixes to {symbol} data: {', '.join(fixes_applied)}")

        return df
