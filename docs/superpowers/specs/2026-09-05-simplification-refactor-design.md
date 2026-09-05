# Simplification Refactor — Design

**Date:** 2026-09-05
**Status:** Approved (user-approved 2026-09-05)
**Source evidence:** knowledge graph rebuild (production-only scope: 5,577 nodes / 10,933 edges / 304 communities) + grep verification of every claim; graph outputs in `graphify-out/` (gitignored local artifact).
**Baseline:** branch `feat/fractal-half-trend-signals` at `eeb28882`; full `tests/quant` suite 1,761 passed / 0 failed; backend unit suite 687 passed.

## 1. Problem

Post-quantv2-removal, the live system still carries structural duplication that (a) makes every change touch 4–6 files, (b) risks calculation drift between parallel implementations, and (c) hides god-files. Evidence, grep-verified:

| # | Target | Evidence |
|---|--------|----------|
| 1 | Broker port fan-out: `cancel_order` ×6 files, `get_option_chain`/`stream_full` ×5, `get_lot_size` ×5 — across `quant/contracts/ports/*`, `brokers/broker/ports.py` + `application/services/*`, `backend/app/infrastructure/adapters/*` | graph fan-out + grep |
| 2 | Type clones: `Signal` (`quant/contracts/entities.py`, `quant/decision/signal_builder.py`, dead `quant/hansi/models.py`), `Position` (`contracts/entities.py`, `execution/order.py`, `shared/entities/models.py`), `Bar` (`quant/bars.py`, `quant/state_machine.py`), `OHLC` (`quant/contracts/value_objects.py`, `brokers/broker/dhan/domain/value_objects.py`) | graph dup matrix + grep |
| 3 | Calc duplication: `detect_absorption()` (`quant/amt/orderflow/footprint.py:281`) vs `AbsorptionDetector` (`quant/amt/orderflow/detectors.py:273`); private `_extract_underlying` in `quant/amt/session/symbol_registry.py` and `quant/amt/session/futures_provider.py` while the canonical `ExchangeConfig.extract_underlying` is already used by `quant/runtime.py:1432` | grep-verified |
| 4 | Dead code: `quant/hansi/` — zero importers in quant/, backend/, tests/ | grep-verified |
| 5 | God files: `brokers/broker/dhan/domain/entities.py` (144 graph nodes), `backend/app/config_models/settings_adapter.py` (84) | graph hotspot table |

### Withdrawn claims (graph artifacts, verified NOT duplication)

- `find_lvns` ×3 — already unified: `amt/analyzer.py` and `amt/profile/displacement.py` both import from `amt/profile/lvn.py`. A verification test will keep it pinned.
- `snapshot()` ×6 — six *different* concepts sharing a method name (`TripleASnapshot`, `ViewState`, order-feed snapshot, …). Not duplication.
- `coordinator_view.py` dead — wrong: imported by `backend/app/api/websocket/gameloop.py`. Stays.

## 2. Decisions (user-approved)

1. **Scope:** full simplification (all five targets).
2. **Canonical broker port lives in `brokers/`:** `brokers/broker/ports.py` is THE port surface; `quant/contracts/ports/broker.py` and `market_data.py` become re-export shims; backend adapters import the port, never the `DhanBroker` concrete.
3. **Approach A — canonical homes in place:** each duplicated type keeps its current live home; all other sites become re-exports or calls. No relocation of types between packages. `broker_mapper.py`'s explicit `BrokerSignal`/`EngineSignal` aliasing is the sanctioned seam and remains.
4. **Sequencing:** strangler — five independent slices, each ending green + committed; system shippable after every slice.

### Canonical homes (binding)

| Type | Canonical | Becomes re-export |
|------|-----------|-------------------|
| `Signal` | `quant/decision/signal_builder.py` | `quant/contracts/entities.py`, `shared/entities/models.py`; `quant/hansi/` deleted |
| `Position` | `quant/execution/order.py` | `quant/contracts/entities.py`, `shared/entities/models.py` |
| `Bar` | `quant/bars.py` | `quant/state_machine.py` |
| `OHLC` | `quant/contracts/value_objects.py` | `brokers/broker/dhan/domain/value_objects.py` |
| absorption | `quant/amt/orderflow/detectors.py::AbsorptionDetector` | `footprint.py::detect_absorption` delegates or is deleted (caller census decides) |
| symbol parsing | `quant/contracts/exchange_config.py::ExchangeConfig.extract_underlying` | private copies in `symbol_registry.py`, `futures_provider.py` |

## 3. Strangler slices (order is binding: 4 depends on 2)

1. **Dead code** — delete `quant/hansi/` and any dead leftovers confirmed by importer grep. Commit contains deletions only.
2. **Type clones** — `Bar`, `OHLC`, `Position`, `Signal` unified via re-export shims per the canonical table. Mapper contracts pinned by existing `broker_mapper`/`view_mappers` tests. Backend unit suite gate applies.
3. **Calc dedup** — absorption single-definition; `_extract_underlying` private copies replaced by `ExchangeConfig.for_exchange(...)` calls. **Characterization parity tests first** (see §4).
4. **Broker port inversion** — `quant/contracts/ports/broker.py` + `market_data.py` re-export `brokers/broker/ports.py`; backend adapters import the port; pure passthrough methods deleted from adapters.
5. **God-file splits** — `brokers/broker/dhan/domain/entities.py` split by entity family; `backend/app/config_models/settings_adapter.py` split by config domain. Cosmetic; last.

## 4. Calculation-accuracy protocol (mandatory for slice 3, applies to any behavior-adjacent step)

1. **Characterization parity test first (red):** run OLD and NEW implementations over fixture inputs (real candle corpora for absorption; NSE/BSE/MCX symbol corpus for parsing) and assert field-by-field identical outputs. The test failing before merge proves the implementations genuinely differ — drift is caught, not silently merged.
2. **If parity fails:** the drift is a live calculation bug. Diff outputs, decide correctness against `docs/amt` semantics, fix the canonical, then deduplicate. Never merge a known disagreement.
3. **Golden trace gate:** `tests/quant/runtime/test_decide_golden.py::test_decide_golden_matches_committed_snapshot` stays byte-identical through every slice. Drift = STOP and diagnose. Never regenerate the snapshot to make a slice pass.
4. **Exact equality:** parity asserts exact parsed values (Decimal/float equality after identical parsing) — no epsilon tolerances.

## 5. Testing & safety

- **Per-slice gates:** full `tests/quant` (baseline 1,761) before every commit; `tests/system/test_quant_execution_e2e.py` before every commit; backend unit suite (baseline 687) for slices 2 and 4.
- **Identity re-export tests:** each shim gets `module.X is canonical.X` (identity, not equality).
- **Anti-clone AST guard:** extend the existing `test_no_import_cycles.py` pattern with a guard asserting no duplicate top-level class definitions of `Signal`/`Position`/`Bar`/`OHLC` outside their canonical homes (plus sanctioned shims list).
- **Strangler discipline:** one concern per commit; no slice mixes deletions with moves.

## 6. Error handling & rollback

- Mid-slice failure → revert that slice's commits only; slices are independent by construction.
- Golden-trace drift → STOP, diagnose against `docs/amt`, fix forward on the canonical.
- Post-merge runtime verification: stack boot, `/health/ready` all green, `startup_reconciliation` reports `discrepancies=0`, journal summary clean (same protocol as the truthfulness branch).

## 7. Non-goals

- No behavior changes beyond bug-fixes surfaced by parity drift.
- No relocation of types between packages (Approach B explicitly rejected).
- No new abstractions/protocols (Approach C rejected — it does not remove duplication).
- No changes to `quantv2/` (deleted), no work on test organization beyond what slices require.
