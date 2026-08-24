#!/usr/bin/env python3
"""Select trading mode and update environment variables.

Usage:
    python scripts/select_mode.py --env paper --strategy mcx_options
    python scripts/select_mode.py --env live --strategy nse_options
    python scripts/select_mode.py --list  # Show available modes

This script updates the .env file with GLASSYTRADE_ENV and GLASSYTRADE_STRATEGY
variables, which control which YAML configuration files are loaded at startup.

Configuration Hierarchy:
    1. base.yaml (all defaults)
    2. environments/{GLASSYTRADE_ENV}.yaml (development/paper/live)
    3. strategies/{GLASSYTRADE_STRATEGY}.yaml (mcx_options/nse_options)
    4. .env (secrets only: API keys, tokens)
"""

import argparse
from pathlib import Path


def list_modes():
    """Show available environments and strategies."""
    config_dir = Path(__file__).parent.parent / "config"
    
    print("=" * 70)
    print("GLASSYTRADE AI - Available Configuration Modes")
    print("=" * 70)
    
    print("\n📦 Available Environments:")
    env_dir = config_dir / "environments"
    if env_dir.exists():
        for f in sorted(env_dir.glob("*.yaml")):
            # Read first comment line for description
            with open(f) as file:
                first_line = file.readline().strip().lstrip("#").strip()
            print(f"  • {f.stem:20s} - {first_line}")
    else:
        print("  (No environment files found)")
    
    print("\n🎯 Available Strategies:")
    strat_dir = config_dir / "strategies"
    if strat_dir.exists():
        for f in sorted(strat_dir.glob("*.yaml")):
            # Read first comment line for description
            with open(f) as file:
                first_line = file.readline().strip().lstrip("#").strip()
            print(f"  • {f.stem:20s} - {first_line}")
    else:
        print("  (No strategy files found)")
    
    print("\n" + "=" * 70)
    print("Usage:")
    print("  python scripts/select_mode.py --env paper --strategy mcx_options")
    print("  python scripts/select_mode.py --env paper --strategy nse_options")
    print("=" * 70)


def select_mode(env: str, strategy: str):
    """Set mode by updating .env file."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    
    if not env_file.exists():
        print(f"❌ .env file not found: {env_file}")
        print("Please create a .env file first")
        return
    
    # Read existing .env
    lines = env_file.read_text().splitlines()
    
    # Update or add GLASSYTRADE_ENV and GLASSYTRADE_STRATEGY
    updated_env = False
    updated_strategy = False
    new_lines = []
    
    for line in lines:
        if line.startswith("GLASSYTRADE_ENV="):
            new_lines.append(f"GLASSYTRADE_ENV={env}")
            updated_env = True
        elif line.startswith("GLASSYTRADE_STRATEGY="):
            new_lines.append(f"GLASSYTRADE_STRATEGY={strategy}")
            updated_strategy = True
        else:
            new_lines.append(line)
    
    # Add if not found
    if not updated_env:
        new_lines.append(f"\n# Mode Selection (set by scripts/select_mode.py)")
        new_lines.append(f"GLASSYTRADE_ENV={env}")
    
    if not updated_strategy:
        if not updated_env:
            new_lines.append(f"GLASSYTRADE_STRATEGY={strategy}")
        else:
            new_lines.append(f"GLASSYTRADE_STRATEGY={strategy}")
    
    # Write back
    env_file.write_text("\n".join(new_lines) + "\n")
    
    print(f"✅ Mode set successfully!")
    print(f"   Environment: {env}")
    print(f"   Strategy:    {strategy}")
    print(f"\n📝 Configuration will be loaded from:")
    print(f"   • backend/config/base.yaml (defaults)")
    print(f"   • backend/config/environments/{env}.yaml")
    print(f"   • backend/config/strategies/{strategy}.yaml")
    print(f"   • .env (secrets only)")
    print(f"\n🚀 Restart backend to apply changes:")
    print(f"   cd backend && ./venv/bin/uvicorn app.main:app --port 9090")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Select trading mode for GlassyTrade AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available modes
  python scripts/select_mode.py --list
  
  # Set MCX paper trading mode
  python scripts/select_mode.py --env paper --strategy mcx_options
  
  # Set NSE live trading mode
  python scripts/select_mode.py --env live --strategy nse_options
        """
    )
    parser.add_argument(
        "--env",
        choices=["development", "paper", "live"],
        help="Environment (development/paper/live)"
    )
    parser.add_argument(
        "--strategy",
        choices=["mcx_options", "nse_options"],
        help="Trading strategy (mcx_options/nse_options)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available environments and strategies"
    )
    
    args = parser.parse_args()
    
    if args.list:
        list_modes()
    elif args.env and args.strategy:
        select_mode(args.env, args.strategy)
    else:
        parser.print_help()
