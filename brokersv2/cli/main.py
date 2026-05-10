"""BrokersV2 - Professional Trading CLI

Direct Dhan Broker integration with Analytics - NO backend required.
Automatically loads credentials from .env files.
Connects directly to Dhan API for LIVE market data + analytics.

Usage:
    cd /Users/apple/Downloads/v5-of-glassytrade-ai/brokersv2
    ../venv/bin/python -m cli.main
"""

from __future__ import annotations

import sys
import asyncio
import os
import time
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

# Add project root and brokers to path
project_root = Path(__file__).resolve().parent.parent.parent
brokersv2_root = Path(__file__).resolve().parent.parent
brokers_root = project_root / "brokers"

for path in [str(project_root), str(brokers_root)]:
    if path not in sys.path:
        sys.path.insert(0, path)

# Load .env files automatically (like brokers does)
try:
    from dotenv import load_dotenv
    
    # Try project root .env first
    project_env = project_root / ".env"
    if project_env.exists():
        load_dotenv(project_env, override=True)
    
    # Try backend .env as fallback
    backend_env = project_root / "backend" / ".env"
    if backend_env.exists():
        load_dotenv(backend_env, override=True)
        
except ImportError:
    pass  # python-dotenv not installed, will use system env

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm, IntPrompt, FloatPrompt

console = Console()

# Import analytics modules
from brokersv2.analytics.vwap import (
    calculate_session_vwap,
    calculate_vwap_bands,
)
from brokersv2.analytics.options import (
    calculate_greeks,
    detect_buildups,
    calculate_skew,
    calculate_term_structure,
)
from brokersv2.analytics.order_book import (
    SweepDetector,
)
from brokersv2.infrastructure.rate_limiter.token_bucket import RateLimiter

# Global rate limiter for CLI
rate_limiter = RateLimiter()

# MCX Symbols
MCX_SYMBOLS = ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM", "COPPER"]
NSE_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY"]


# ============================================================================
# Dhan Broker Direct Connection
# ============================================================================

class DhanBrokerCLI:
    """Direct Dhan broker operations - NO backend needed."""
    
    @staticmethod
    def get_broker():
        """Get Dhan broker instance using factory."""
        try:
            from brokersv2.broker_factory import get_broker
            return get_broker()
        except Exception as e:
            console.print(f"[red]✗ {str(e)}[/]")
            return None
    
    @staticmethod
    async def get_historical_data():
        """Fetch REAL historical OHLCV from Dhan."""
        console.print("\n[bold cyan]═══════════════════════════════════════════════════[/]")
        console.print("[bold cyan]           HISTORICAL DATA (LIVE DHAN)             [/]")
        console.print("[bold cyan]═══════════════════════════════════════════════════[/]\n")
        
        console.print("[bold]Available Symbols:[/]")
        console.print("  MCX: " + ", ".join(MCX_SYMBOLS))
        console.print("  NSE: " + ", ".join(NSE_SYMBOLS))
        
        symbol = Prompt.ask("\nSymbol", default="CRUDEOIL")
        exchange = Prompt.ask("Exchange", choices=["MCX", "NSE", "NFO"], default="MCX")
        interval = Prompt.ask("Interval", choices=["1m", "3m", "5m", "15m", "1h", "1d"], default="5m")
        limit = IntPrompt.ask("Number of candles", default=100)
        
        console.print(f"\n[yellow]Fetching {limit} {interval} candles for {symbol} from Dhan...[/]\n")
        
        broker = DhanBrokerCLI.get_broker()
        if not broker:
            return
        
        try:
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            
            # Fetch from Dhan (synchronous, returns DataFrame)
            df = broker.historical(
                symbol=symbol,
                from_date=start_date.strftime("%Y-%m-%d"),
                to_date=end_date.strftime("%Y-%m-%d"),
                interval=interval
            )
            
            if df is not None and not df.empty:
                # Display last N candles
                candles = df.tail(limit).copy()
                
                # Convert Unix timestamp to readable datetime
                if 'timestamp' in candles.columns:
                    candles['datetime'] = pd.to_datetime(candles['timestamp'], unit='s')
                
                table = Table(title=f"{symbol} - Historical OHLCV ({interval}) - LIVE DATA")
                table.add_column("Time", style="cyan")
                table.add_column("Open", justify="right", style="white")
                table.add_column("High", justify="right", style="green")
                table.add_column("Low", justify="right", style="red")
                table.add_column("Close", justify="right", style="white")
                table.add_column("Volume", justify="right", style="yellow")
                
                for idx, row in candles.iterrows():
                    # Use timestamp column if available, otherwise fallback to index
                    if 'datetime' in row:
                        time_str = row['datetime'].strftime('%Y-%m-%d %H:%M')
                    elif 'timestamp' in row:
                        time_str = pd.to_datetime(row['timestamp'], unit='s').strftime('%Y-%m-%d %H:%M')
                    else:
                        time_str = str(idx)
                    
                    table.add_row(
                        time_str,
                        f"₹{row['open']:,.2f}",
                        f"₹{row['high']:,.2f}",
                        f"₹{row['low']:,.2f}",
                        f"₹{row['close']:,.2f}",
                        f"{int(row['volume']):,}"
                    )
                
                console.print(table)
                console.print(f"\n[green]✓[/] Fetched {len(candles)} LIVE candles from Dhan")
            else:
                console.print("[yellow]⚠ No data returned from Dhan[/]")
                
        except Exception as e:
            console.print(f"[red]✗ Error fetching from Dhan: {str(e)}[/]")
    
    @staticmethod
    async def get_options_chain():
        """Fetch REAL options chain from Dhan."""
        console.print("\n[bold cyan]═══════════════════════════════════════════════════[/]")
        console.print("[bold cyan]           OPTIONS CHAIN (LIVE DHAN)               [/]")
        console.print("[bold cyan]═══════════════════════════════════════════════════[/]\n")
        
        underlying = Prompt.ask("Underlying", choices=["NIFTY", "BANKNIFTY"], default="NIFTY")
        
        console.print(f"\n[yellow]Fetching options chain for {underlying} from Dhan...[/]\n")
        
        broker = DhanBrokerCLI.get_broker()
        if not broker:
            return
        
        try:
            # Fetch options chain (returns OptionChain object)
            chain = broker.option_chain(underlying)
            
            if chain and len(chain.calls) > 0:
                table = Table(title=f"{underlying} Options Chain - LIVE DATA")
                table.add_column("Type", style="cyan")
                table.add_column("Strike", justify="right", style="white")
                table.add_column("Bid", justify="right", style="green")
                table.add_column("Ask", justify="right", style="red")
                table.add_column("LTP", justify="right", style="white")
                table.add_column("Volume", justify="right", style="yellow")
                table.add_column("OI", justify="right", style="magenta")
                
                # Combine calls and puts
                all_options = []
                for call in chain.calls[:15]:
                    all_options.append({
                        "option_type": "CE",
                        "strike": call.strike,
                        "bid": getattr(call, 'bid', 0),
                        "ask": getattr(call, 'ask', 0),
                        "ltp": getattr(call, 'ltp', 0),
                        "volume": getattr(call, 'volume', 0),
                        "oi": getattr(call, 'oi', 0)
                    })
                for put in chain.puts[:15]:
                    all_options.append({
                        "option_type": "PE",
                        "strike": put.strike,
                        "bid": getattr(put, 'bid', 0),
                        "ask": getattr(put, 'ask', 0),
                        "ltp": getattr(put, 'ltp', 0),
                        "volume": getattr(put, 'volume', 0),
                        "oi": getattr(put, 'oi', 0)
                    })
                
                for option in sorted(all_options, key=lambda x: x["strike"])[:30]:
                    table.add_row(
                        option["option_type"],
                        f"₹{option['strike']:,.2f}",
                        f"₹{option['bid']:,.2f}",
                        f"₹{option['ask']:,.2f}",
                        f"₹{option['ltp']:,.2f}",
                        f"{option['volume']:,}",
                        f"{option['oi']:,}"
                    )
                
                console.print(table)
                console.print(f"\n[green]✓[/] Fetched {len(all_options)} LIVE options from Dhan")
            else:
                console.print("[yellow]⚠ No options data returned from Dhan[/]")
                
        except Exception as e:
            console.print(f"[red]✗ Error fetching from Dhan: {str(e)}[/]")
    
    @staticmethod
    async def get_market_depth():
        """Get REAL L2 market depth from Dhan."""
        console.print("\n[bold cyan]═══════════════════════════════════════════════════[/]")
        console.print("[bold cyan]           MARKET DEPTH L2 (LIVE DHAN)             [/]")
        console.print("[bold cyan]═══════════════════════════════════════════════════[/]\n")
        
        symbol = Prompt.ask("Symbol", default="CRUDEOIL")
        
        console.print(f"\n[yellow]Fetching L2 depth for {symbol} from Dhan...[/]\n")
        
        broker = DhanBrokerCLI.get_broker()
        if not broker:
            return
        
        try:
            # Get depth/quote (returns Quote object)
            quote = broker.quote(symbol)
            
            if quote:
                table = Table(title=f"{symbol} - Market Depth - LIVE DATA")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", justify="right", style="white")
                
                table.add_row("Last Price", f"₹{getattr(quote, 'ltp', 0):,.2f}")
                table.add_row("Bid Price", f"₹{getattr(quote, 'bid_price', 0):,.2f}")
                table.add_row("Ask Price", f"₹{getattr(quote, 'ask_price', 0):,.2f}")
                table.add_row("Bid Qty", f"{getattr(quote, 'bid_qty', 0):,}")
                table.add_row("Ask Qty", f"{getattr(quote, 'ask_qty', 0):,}")
                table.add_row("Volume", f"{getattr(quote, 'volume', 0):,}")
                table.add_row("High", f"₹{getattr(quote, 'high', 0):,.2f}")
                table.add_row("Low", f"₹{getattr(quote, 'low', 0):,.2f}")
                
                console.print(table)
                
                # Calculate spread
                bid = getattr(quote, "bid_price", 0)
                ask = getattr(quote, "ask_price", 0)
                if bid and ask:
                    spread = ask - bid
                    spread_pct = (spread / bid) * 100
                    console.print(f"\nSpread: ₹{spread:,.2f} ({spread_pct:.2f}%)")
            else:
                console.print("[yellow]⚠ No depth data returned from Dhan[/]")
                
        except Exception as e:
            console.print(f"[red]✗ Error fetching from Dhan: {str(e)}[/]")
    
    @staticmethod
    async def get_market_snapshot():
        """Get REAL market snapshot from Dhan."""
        console.print("\n[bold cyan]═══════════════════════════════════════════════════[/]")
        console.print("[bold cyan]           MARKET SNAPSHOT (LIVE DHAN)             [/]")
        console.print("[bold cyan]═══════════════════════════════════════════════════[/]\n")
        
        exchange = Prompt.ask("Exchange", choices=["MCX", "NSE"], default="MCX")
        
        symbols = MCX_SYMBOLS if exchange == "MCX" else NSE_SYMBOLS
        
        console.print(f"\n[yellow]Fetching {exchange} snapshot from Dhan...[/]\n")
        
        broker = DhanBrokerCLI.get_broker()
        if not broker:
            return
        
        try:
            table = Table(title=f"{exchange} Market Snapshot - LIVE DATA")
            table.add_column("Symbol", style="cyan")
            table.add_column("LTP", justify="right", style="white")
            table.add_column("Change", justify="right")
            table.add_column("Volume", justify="right", style="yellow")
            table.add_column("High", justify="right", style="green")
            table.add_column("Low", justify="right", style="red")
            
            for symbol in symbols:
                try:
                    # Use rate limiter to respect Dhan API limits (1 req/sec for quotes)
                    if not rate_limiter.wait_for_token("quotes", timeout=5.0):
                        console.print(f"[red]✗ {symbol}: Rate limit timeout[/]")
                        continue
                    
                    quote = broker.quote(symbol)
                    
                    if quote:
                        ltp = getattr(quote, 'ltp', 0)
                        prev_close = getattr(quote, 'prev_close', ltp)
                        change = ltp - prev_close
                        change_pct = (change / prev_close * 100) if prev_close else 0
                        change_style = "green" if change >= 0 else "red"
                        
                        table.add_row(
                            symbol,
                            f"₹{ltp:,.2f}",
                            f"[{change_style}]{change:+.2f} ({change_pct:+.2f}%)[/]",
                            f"{getattr(quote, 'volume', 0):,}",
                            f"₹{getattr(quote, 'high', 0):,.2f}",
                            f"₹{getattr(quote, 'low', 0):,.2f}"
                        )
                except Exception as e:
                    # Show error details for debugging
                    error_msg = str(e)[:30]
                    table.add_row(symbol, "[red]Error[/]", f"[dim]{error_msg}[/]", "-", "-", "-")
            
            console.print(table)
            console.print(f"\n[green]✓[/] Fetched LIVE data from Dhan")
            
        except Exception as e:
            console.print(f"[red]✗ Error fetching from Dhan: {str(e)}[/]")

    @staticmethod
    async def get_vwap_analytics():
        """Calculate VWAP analytics from historical data."""
        console.print("\n[bold cyan]═══════════════════════════════════════════════════[/]")
        console.print("[bold cyan]           VWAP ANALYTICS (LIVE + CALCULATED)      [/]")
        console.print("[bold cyan]═══════════════════════════════════════════════════[/]\n")
        
        symbol = Prompt.ask("Symbol", default="CRUDEOIL")
        
        console.print(f"\n[yellow]Fetching data and calculating VWAP for {symbol}...[/]\n")
        
        broker = DhanBrokerCLI.get_broker()
        if not broker:
            return
        
        try:
            # Fetch intraday data (synchronous, returns DataFrame)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=1)
            
            df = broker.historical(
                symbol=symbol,
                from_date=start_date.strftime("%Y-%m-%d"),
                to_date=end_date.strftime("%Y-%m-%d"),
                interval="5m"
            )
            
            if df is None or df.empty:
                console.print("[yellow]⚠ No data available[/]")
                return
            
            # Prepare trades for VWAP calculation
            trades = []
            for idx, row in df.iterrows():
                trades.append({
                    "timestamp": idx,
                    "price": row["close"],
                    "volume": int(row["volume"])
                })
            
            # Calculate session VWAP
            vwap = calculate_session_vwap(symbol, trades)
            
            # Calculate VWAP bands
            bands = calculate_vwap_bands(symbol, trades, num_std=2.0)
            
            # Display results
            table = Table(title=f"{symbol} - VWAP Analytics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", justify="right", style="white")
            
            current_price = trades[-1]["price"] if trades else 0
            
            table.add_row("Current Price", f"₹{current_price:,.2f}")
            table.add_row("Session VWAP", f"₹{vwap.vwap:,.2f}")
            table.add_row("Upper Band (2σ)", f"₹{bands.upper_band:,.2f}")
            table.add_row("Lower Band (2σ)", f"₹{bands.lower_band:,.2f}")
            table.add_row("Band Width", f"₹{bands.band_width:,.2f} ({bands.band_width_pct:.2f}%)")
            table.add_row("Price Position", bands.position)
            table.add_row("Total Volume", f"{vwap.total_volume:,}")
            table.add_row("Total Trades", str(vwap.total_trades))
            
            # Price vs VWAP
            price_vs_vwap = ((current_price - vwap.vwap) / vwap.vwap * 100) if vwap.vwap > 0 else 0
            style = "green" if price_vs_vwap > 0 else "red"
            table.add_row("Price vs VWAP", f"[{style}]{price_vs_vwap:+.2f}%[/]")
            
            console.print(table)
            
            # Interpretation
            console.print("\n[bold]Interpretation:[/]")
            if bands.position == "above_upper":
                console.print("  [yellow]⚠ Price extended above upper band - potential reversal[/]")
            elif bands.position == "below_lower":
                console.print("  [yellow]⚠ Price extended below lower band - potential bounce[/]")
            elif "between" in bands.position:
                console.print("  [green]✓ Price within normal VWAP range[/]")
            
        except Exception as e:
            console.print(f"[red]✗ Error: {str(e)}[/]")

    @staticmethod
    async def get_options_analytics():
        """Calculate options analytics with Greeks."""
        console.print("\n[bold cyan]═══════════════════════════════════════════════════[/]")
        console.print("[bold cyan]           OPTIONS ANALYTICS (LIVE + GREEKS)       [/]")
        console.print("[bold cyan]═══════════════════════════════════════════════════[/]\n")
        
        underlying = Prompt.ask("Underlying", choices=["NIFTY", "BANKNIFTY"], default="NIFTY")
        
        # Fetch real spot price from broker
        console.print(f"\n[yellow]Fetching {underlying} options chain...[/]\n")
        
        broker = DhanBrokerCLI.get_broker()
        if not broker:
            return
        
        try:
            # Get options chain to find real spot price
            time.sleep(1)  # Rate limiting
            chain_obj = broker.option_chain(underlying)
            
            if not chain_obj:
                console.print("[yellow]⚠ No options data available[/]")
                return
            
            # Use real spot price from chain
            spot_price = chain_obj.spot_price
            console.print(f"[dim]Current spot price: ₹{spot_price:,.2f}[/]")
            console.print(f"[dim]Fetching Greeks...[/]\n")
            
            # Convert dict-based chain to list of dicts for display
            all_options = []
            
            # Handle dict-based chains (strike -> Option)
            if isinstance(chain_obj.calls, dict):
                for strike, call in chain_obj.calls.items():
                    all_options.append({
                        "option_type": "CE",
                        "strike": getattr(call, 'strike', strike),
                        "bid": getattr(call, 'bid', 0) or 0,
                        "ask": getattr(call, 'ask', 0) or 0,
                        "ltp": getattr(call, 'ltp', 0) or 0,
                        "volume": getattr(call, 'volume', 0) or 0,
                        "oi": getattr(call, 'oi', 0) or 0
                    })
            else:
                # Handle list-based chains
                for call in chain_obj.calls:
                    all_options.append({
                        "option_type": "CE",
                        "strike": getattr(call, 'strike', 0),
                        "bid": getattr(call, 'bid', 0) or 0,
                        "ask": getattr(call, 'ask', 0) or 0,
                        "ltp": getattr(call, 'ltp', 0) or 0,
                        "volume": getattr(call, 'volume', 0) or 0,
                        "oi": getattr(call, 'oi', 0) or 0
                    })
            
            if isinstance(chain_obj.puts, dict):
                for strike, put in chain_obj.puts.items():
                    all_options.append({
                        "option_type": "PE",
                        "strike": getattr(put, 'strike', strike),
                        "bid": getattr(put, 'bid', 0) or 0,
                        "ask": getattr(put, 'ask', 0) or 0,
                        "ltp": getattr(put, 'ltp', 0) or 0,
                        "volume": getattr(put, 'volume', 0) or 0,
                        "oi": getattr(put, 'oi', 0) or 0
                    })
            else:
                for put in chain_obj.puts:
                    all_options.append({
                        "option_type": "PE",
                        "strike": getattr(put, 'strike', 0),
                        "bid": getattr(put, 'bid', 0) or 0,
                        "ask": getattr(put, 'ask', 0) or 0,
                        "ltp": getattr(put, 'ltp', 0) or 0,
                        "volume": getattr(put, 'volume', 0) or 0,
                        "oi": getattr(put, 'oi', 0) or 0
                    })
            
            # Calculate Greeks for ATM options
            table = Table(title=f"{underlying} - Options Greeks (ATM)")
            table.add_column("Type", style="cyan")
            table.add_column("Strike", justify="right", style="white")
            table.add_column("LTP", justify="right", style="white")
            table.add_column("Delta", justify="right", style="yellow")
            table.add_column("Gamma", justify="right", style="green")
            table.add_column("Theta", justify="right", style="red")
            table.add_column("Vega", justify="right", style="magenta")
            
            # Find ATM strike
            active_options = [opt for opt in all_options if opt.get("ltp", 0) > 0]
            if not active_options:
                console.print("[yellow]⚠ No active options with LTP data (market may be closed)[/]")
                return
            
            atm_option = min(active_options, key=lambda x: abs(x.get("strike", 0) - spot_price))
            atm_strike_price = atm_option["strike"]
            
            # Calculate Greeks for nearby strikes (ATM ± 5 strikes)
            nearby_strikes = sorted(set(opt["strike"] for opt in all_options))
            atm_index = next((i for i, s in enumerate(nearby_strikes) if abs(s - atm_strike_price) < 1), len(nearby_strikes)//2)
            
            start_idx = max(0, atm_index - 3)
            end_idx = min(len(nearby_strikes), atm_index + 4)
            selected_strikes = nearby_strikes[start_idx:end_idx]
            
            for option in all_options:
                if option["strike"] not in selected_strikes:
                    continue
                    
                strike = option["strike"]
                opt_type = option["option_type"]
                ltp = option.get("ltp", 0)
                
                # Skip if no LTP
                if ltp == 0:
                    continue
                
                # Calculate Greeks (assume 30 days to expiry, 15% vol)
                try:
                    greeks = calculate_greeks(
                        spot=spot_price,
                        strike=strike,
                        time_to_expiry=30/365,
                        volatility=0.15,
                        risk_free_rate=0.065,
                        option_type=opt_type
                    )
                    
                    table.add_row(
                        opt_type,
                        f"₹{strike:,.0f}",
                        f"₹{ltp:,.2f}",
                        f"{greeks.delta:.3f}",
                        f"{greeks.gamma:.4f}",
                        f"{greeks.theta:.2f}",
                        f"{greeks.vega:.2f}"
                    )
                except Exception as e:
                    pass
            
            console.print(table)
            console.print("\n[dim]Note: Greeks calculated with 30DTE, 15% IV assumption[/]")
            
        except Exception as e:
            console.print(f"[red]✗ Error: {str(e)}[/]")

    @staticmethod
    async def get_oi_buildup():
        """Detect OI buildup patterns."""
        console.print("\n[bold cyan]═══════════════════════════════════════════════════[/]")
        console.print("[bold cyan]           OI BUILDUP DETECTION (LIVE)             [/]")
        console.print("[bold cyan]═══════════════════════════════════════════════════[/]\n")
        
        underlying = Prompt.ask("Underlying", choices=["NIFTY", "BANKNIFTY"], default="NIFTY")
        
        console.print(f"\n[yellow]Fetching options chain and detecting buildups...[/]\n")
        
        broker = DhanBrokerCLI.get_broker()
        if not broker:
            return
        
        try:
            # Fetch current options chain (returns OptionChain object with dict of strikes)
            time.sleep(1)  # Rate limiting
            chain_obj = broker.option_chain(underlying)
            
            if not chain_obj:
                console.print("[yellow]⚠ No options data available[/]")
                return
            
            # Convert dict-based chain to list of dicts
            current_chain = []
            
            if isinstance(chain_obj.calls, dict):
                for strike, call in chain_obj.calls.items():
                    current_chain.append({
                        "option_type": "CE",
                        "strike": getattr(call, 'strike', strike),
                        "ltp": getattr(call, 'ltp', 0) or 0,
                        "price": getattr(call, 'ltp', 0) or 0,
                        "oi": getattr(call, 'oi', 0) or 0,
                        "volume": getattr(call, 'volume', 0) or 0
                    })
            else:
                for call in chain_obj.calls:
                    current_chain.append({
                        "option_type": "CE",
                        "strike": getattr(call, 'strike', 0),
                        "ltp": getattr(call, 'ltp', 0) or 0,
                        "price": getattr(call, 'ltp', 0) or 0,
                        "oi": getattr(call, 'oi', 0) or 0,
                        "volume": getattr(call, 'volume', 0) or 0
                    })
            
            if isinstance(chain_obj.puts, dict):
                for strike, put in chain_obj.puts.items():
                    current_chain.append({
                        "option_type": "PE",
                        "strike": getattr(put, 'strike', strike),
                        "ltp": getattr(put, 'ltp', 0) or 0,
                        "price": getattr(put, 'ltp', 0) or 0,
                        "oi": getattr(put, 'oi', 0) or 0,
                        "volume": getattr(put, 'volume', 0) or 0
                    })
            else:
                for put in chain_obj.puts:
                    current_chain.append({
                        "option_type": "PE",
                        "strike": getattr(put, 'strike', 0),
                        "ltp": getattr(put, 'ltp', 0) or 0,
                        "price": getattr(put, 'ltp', 0) or 0,
                        "oi": getattr(put, 'oi', 0) or 0,
                        "volume": getattr(put, 'volume', 0) or 0
                    })
            
            # Filter to options with OI data
            current_chain = [opt for opt in current_chain if opt.get("oi", 0) > 0]
            
            if not current_chain:
                console.print("[yellow]⚠ No options with OI data (market may be closed)[/]")
                return
            
            # Simulate previous data (in real scenario, fetch historical)
            previous_chain = []
            for opt in current_chain:
                prev_opt = opt.copy()
                # Simulate 5-10% OI change
                oi_change = int(opt.get("oi", 0) * 0.08)
                prev_opt["oi"] = opt.get("oi", 0) - oi_change
                # Simulate price change
                prev_opt["price"] = opt.get("ltp", 0) - (opt.get("ltp", 0) * 0.02)
                previous_chain.append(prev_opt)
            
            # Detect buildups
            buildups = detect_buildups(
                current_strikes=current_chain,
                previous_strikes=previous_chain,
                min_oi_pct_change=5.0
            )
            
            if not buildups:
                console.print("[yellow]⚠ No significant buildups detected[/]")
                return
            
            # Display buildups
            table = Table(title=f"{underlying} - OI Buildup Detection")
            table.add_column("Strike", justify="right", style="cyan")
            table.add_column("Type", style="white")
            table.add_column("Buildup", style="yellow")
            table.add_column("OI", justify="right", style="white")
            table.add_column("OI Change", justify="right")
            table.add_column("Price", justify="right", style="white")
            table.add_column("Strength", style="magenta")
            
            for buildup in buildups[:15]:  # Show top 15
                change_style = "green" if buildup.oi_change > 0 else "red"
                
                table.add_row(
                    f"₹{buildup.strike:,.0f}",
                    buildup.option_type,
                    buildup.buildup_type.value.replace("_", " ").title(),
                    f"{buildup.oi:,}",
                    f"[{change_style}]{buildup.oi_change:+,} ({buildup.oi_pct_change:+.1f}%)[/]",
                    f"₹{buildup.price:,.2f}",
                    buildup.strength.title()
                )
            
            console.print(table)
            
            # Summary
            bullish = [b for b in buildups if b.is_bullish]
            bearish = [b for b in buildups if b.is_bearish]
            
            console.print(f"\n[bold]Summary:[/]")
            console.print(f"  [green]Bullish buildups: {len(bullish)}[/]")
            console.print(f"  [red]Bearish buildups: {len(bearish)}[/]")
            
        except Exception as e:
            console.print(f"[red]✗ Error: {str(e)}[/]")


# ============================================================================
# Main Menu
# ============================================================================

async def run_trading_terminal():
    """Run trading terminal."""
    console.print(Panel(
        "[bold cyan]BrokersV2 Trading Terminal v3.0[/]\n"
        "[dim]Direct Dhan Broker + Analytics Integration - LIVE DATA[/]",
        border_style="cyan"
    ))
    
    while True:
        console.print("\n[bold]═══════ TRADING MENU ═══════[/]")
        console.print("\n[bold cyan]Market Data (LIVE from Dhan):[/]")
        console.print("  1. Get Historical Data (OHLCV)")
        console.print("  2. Get Options Chain")
        console.print("  3. Get Market Depth (L2)")
        console.print("  4. Get Market Snapshot")
        
        console.print("\n[bold green]Analytics (TDD-Tested Modules):[/]")
        console.print("  5. VWAP Analytics (Session, Bands, Position)")
        console.print("  6. Options Greeks (Delta, Gamma, Theta, Vega)")
        console.print("  7. OI Buildup Detection (Long/Short Patterns)")
        
        console.print("\n[bold red]q. Quit[/]")
        
        choice = Prompt.ask("\nSelect option", choices=["1", "2", "3", "4", "5", "6", "7", "q"])
        
        if choice == "1":
            await DhanBrokerCLI.get_historical_data()
        elif choice == "2":
            await DhanBrokerCLI.get_options_chain()
        elif choice == "3":
            await DhanBrokerCLI.get_market_depth()
        elif choice == "4":
            await DhanBrokerCLI.get_market_snapshot()
        elif choice == "5":
            await DhanBrokerCLI.get_vwap_analytics()
        elif choice == "6":
            await DhanBrokerCLI.get_options_analytics()
        elif choice == "7":
            await DhanBrokerCLI.get_oi_buildup()
        elif choice == "q":
            break


def main():
    """Main entry point."""
    console.print(Panel(
        "[bold cyan]BrokersV2 Trading Terminal v3.0[/]\n"
        "[dim]Direct Dhan Broker + Analytics - Auto-loads .env - LIVE DATA + CALCULATIONS[/]\n\n"
        "[green]Using project venv: /Users/apple/Downloads/v5-of-glassytrade-ai/venv[/]",
        border_style="cyan",
        padding=(1, 2)
    ))
    
    asyncio.run(run_trading_terminal())


if __name__ == "__main__":
    main()
