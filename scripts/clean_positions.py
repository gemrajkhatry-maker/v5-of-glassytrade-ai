#!/usr/bin/env python3
"""Clean stale open positions and cached contracts for fresh session startup."""

import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATHS = [
    REPO_ROOT / "backend" / "glassytrade.db",
    REPO_ROOT / "glassytrade.db",
    REPO_ROOT / "data" / "glassytrade.db",
]
CONTRACTS_FILE = REPO_ROOT / "backend" / ".active_contracts.json"

def clean_database(db_path: Path):
    if not db_path.exists():
        return
    print(f"Checking database: {db_path}")
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check open_positions table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='open_positions'")
        if cursor.fetchone():
            cursor.execute("SELECT COUNT(*) FROM open_positions")
            count = cursor.fetchone()[0]
            if count > 0:
                cursor.execute("DELETE FROM open_positions")
                conn.commit()
                print(f"  ✅ Cleared {count} rows from 'open_positions' in {db_path.name}")
            else:
                print(f"  ℹ️  'open_positions' was already empty in {db_path.name}")
        conn.close()
    except Exception as e:
        print(f"  ❌ Error cleaning {db_path}: {e}")

def clean_contracts_file():
    if CONTRACTS_FILE.exists():
        try:
            CONTRACTS_FILE.unlink()
            print(f"  ✅ Removed cached contracts file: {CONTRACTS_FILE.name}")
        except Exception as e:
            print(f"  ❌ Error removing {CONTRACTS_FILE}: {e}")
    else:
        print(f"  ℹ️  No active contracts file found ({CONTRACTS_FILE.name})")

def main():
    print("=== Cleaning Old Position & Contract Data ===")
    for path in DB_PATHS:
        clean_database(path)
    clean_contracts_file()
    print("=== Done ===")

if __name__ == "__main__":
    main()
