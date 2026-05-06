# TDD Quick Reference Card

## Workflow (Repeat for each test)

```
1. READ    → Next test in TDD_IMPLEMENTATION_PLAN.md
2. WRITE   → Add test to test file
3. RUN     → pytest path::to::test -v  (should FAIL = RED)
4. CODE    → Write minimal implementation
5. RUN     → pytest path::to::test -v  (should PASS = GREEN)
6. COMMIT  → git add + git commit -m "feat: ..."
7. REPEAT  → Next test
```

## Commands

### Run single test
```bash
pytest tests/path/to/test.py::TestClass::test_method -v
```

### Run all tests in file
```bash
pytest tests/path/to/test.py -v
```

### Run with coverage
```bash
pytest tests/path/to/test.py --cov=app.module --cov-report=term-missing
```

### Watch mode (auto-rerun)
```bash
ptw tests/path/to/test.py
```

### Debug failing test
```bash
pytest tests/path/to/test.py::test -v --tb=long --capture=no -s
```

## Git Workflow

```bash
# After test passes
git add <test_file> <implementation_file>
git commit -m "feat: <description> (Blocker X.Y)

TDD Cycle: RED→GREEN ✓

- <change 1>
- <change 2>

Tests: ✓ <test_name>"
```

## Current Status

✅ Blocker 1: SessionStateManager - COMPLETE (4/4 tests)
⏳ Blocker 2: DhanFeedSource - READY TO START
⏳ Blocker 3: AMTComputationStage - PENDING
⏳ Blocker 4: WebSocket AMT - PENDING

## File Locations

- **Plan**: `TDD_IMPLEMENTATION_PLAN.md`
- **Quickstart**: `TDD_QUICKSTART.md`
- **Progress**: `TDD_PROGRESS.md`
- **Tests**: `backendv2/tests/`
- **Code**: `backendv2/app/`

## TDD Rules

✅ Test behavior, not implementation
✅ Use public interfaces only
✅ One test at a time
✅ Minimal code to pass
✅ Never refactor while RED
✅ Run tests after each change

## Common Issues

**Import Error**: `cd backendv2 && python -c "import app"`
**Module Not Found**: Check `sys.path` includes backendv2
**Test Timeout**: Increase timeout in TestClient
**All Zeros**: Need more candles for meaningful AMT

---

**Next Step**: Blocker 2, Test 2.1 → `test_dhan_feed_source_yields_ticks`
