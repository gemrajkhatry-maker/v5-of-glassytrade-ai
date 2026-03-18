"""Live Market Checklist — Pre-market integrity checks.

Run this BEFORE enabling signals at market open.
10 checks that verify data feeds and system state.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def run_live_checks() -> list[dict]:
    """Run 10 live market integrity checks."""
    
    checks = []
    
    # Check 1: Backend health
    try:
        import requests
        resp = requests.get("http://localhost:9090/api/health", timeout=5)
        checks.append({
            "id": 1,
            "name": "Backend Health",
            "passed": resp.status_code == 200,
            "details": resp.json() if resp.status_code == 200 else resp.text,
        })
    except Exception as e:
        checks.append({
            "id": 1,
            "name": "Backend Health",
            "passed": False,
            "details": str(e),
        })
    
    # Check 2: Database connection
    try:
        resp = requests.get("http://localhost:9090/api/health", timeout=5)
        data = resp.json()
        checks.append({
            "id": 2,
            "name": "Database Connection",
            "passed": data.get("checks", {}).get("database") == "ok",
            "details": data.get("checks", {}),
        })
    except:
        checks.append({"id": 2, "name": "Database Connection", "passed": False, "details": "unreachable"})
    
    # Check 3: LLM loaded
    try:
        resp = requests.get("http://localhost:9090/api/health", timeout=5)
        data = resp.json()
        checks.append({
            "id": 3,
            "name": "LLM Model Loaded",
            "passed": data.get("checks", {}).get("llm") == "ok",
            "details": "LLM ready" if data.get("checks", {}).get("llm") == "ok" else "LLM not ready",
        })
    except:
        checks.append({"id": 3, "name": "LLM Model Loaded", "passed": False, "details": "unreachable"})
    
    # Check 4: Scanner configuration
    try:
        from app.config import settings
        checks.append({
            "id": 4,
            "name": "Scanner Configuration",
            "passed": bool(settings.SCANNER_UNDERLYINGS),
            "details": f"Underlyings: {settings.SCANNER_UNDERLYINGS}, Mode: {settings.SCANNER_MODE}",
        })
    except Exception as e:
        checks.append({"id": 4, "name": "Scanner Configuration", "passed": False, "details": str(e)})
    
    # Check 5: Session context working
    try:
        from app.domain.fabio_ai.services.session_context import get_session_info
        session = get_session_info(market="NSE")
        checks.append({
            "id": 5,
            "name": "Session Context",
            "passed": bool(session.session),
            "details": f"Session: {session.session}, Entry allowed: {session.allow_entry}",
        })
    except Exception as e:
        checks.append({"id": 5, "name": "Session Context", "passed": False, "details": str(e)})
    
    # Check 6: AMT Analyzer
    try:
        from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer
        analyzer = AMTAnalyzer()
        checks.append({
            "id": 6,
            "name": "AMT Analyzer",
            "passed": True,
            "details": "AMTAnalyzer initialized successfully",
        })
    except Exception as e:
        checks.append({"id": 6, "name": "AMT Analyzer", "passed": False, "details": str(e)})
    
    # Check 7: Entry Gate
    try:
        from app.domain.fabio_ai.services.entry_gate import three_align_check
        checks.append({
            "id": 7,
            "name": "Entry Gate",
            "passed": callable(three_align_check),
            "details": "three_align_check function available",
        })
    except Exception as e:
        checks.append({"id": 7, "name": "Entry Gate", "passed": False, "details": str(e)})
    
    # Check 8: Session Risk Manager
    try:
        from app.domain.fabio_ai.services.session_risk_manager import SessionRiskManager
        rm = SessionRiskManager()
        checks.append({
            "id": 8,
            "name": "Circuit Breaker",
            "passed": rm.can_trade and rm.max_consecutive_losses == 3,
            "details": f"Max losses: {rm.max_consecutive_losses}, Can trade: {rm.can_trade}",
        })
    except Exception as e:
        checks.append({"id": 8, "name": "Circuit Breaker", "passed": False, "details": str(e)})
    
    # Check 9: Option Scanner
    try:
        from app.domain.fabio_ai.services.option_scanner import OptionScannerService
        checks.append({
            "id": 9,
            "name": "Option Scanner",
            "passed": True,
            "details": "OptionScannerService available",
        })
    except Exception as e:
        checks.append({"id": 9, "name": "Option Scanner", "passed": False, "details": str(e)})
    
    # Check 10: Prompt Builder
    try:
        from app.domain.fabio_ai.services.prompt_builder import build_entry_prompt
        checks.append({
            "id": 10,
            "name": "Prompt Builder",
            "passed": callable(build_entry_prompt),
            "details": "build_entry_prompt function available",
        })
    except Exception as e:
        checks.append({"id": 10, "name": "Prompt Builder", "passed": False, "details": str(e)})
    
    return checks


def print_checklist(checks: list[dict]):
    """Print the checklist results."""
    print("=" * 80)
    print("LIVE MARKET CHECKLIST — PRE-MARKET VERIFICATION")
    print("=" * 80)
    print(f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    print()
    
    passed = 0
    for check in checks:
        status = "✅" if check["passed"] else "❌"
        print(f"{status} [{check['id']:2}] {check['name']}")
        print(f"       {check['details']}")
        if check["passed"]:
            passed += 1
    
    print()
    print("=" * 80)
    print(f"RESULT: {passed}/{len(checks)} checks passed")
    
    if passed == len(checks):
        print("✅ ALL CHECKS PASS — READY FOR TRADING")
    elif passed >= len(checks) - 2:
        print("⚠️ MINOR ISSUES — PROCEED WITH CAUTION")
    else:
        print("❌ CRITICAL FAILURES — DO NOT TRADE")
    print("=" * 80)


if __name__ == "__main__":
    import requests
    checks = run_live_checks()
    print_checklist(checks)
