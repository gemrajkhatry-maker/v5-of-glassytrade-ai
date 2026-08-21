# Stable Futures/Options Startup and Rendering Design

## Goal

Make the current `stable_6` worktree use one coherent futures/options startup and market-data flow, eliminating the causes of missing option volume profiles, startup races, and unnecessary chart redraws without adding a second parallel architecture.

## Confirmed root causes

1. `QuantCoordinator._scan()` returns persisted contracts before adding futures. A same-day file created by the older option-only coordinator can therefore start only options, leaving no futures engine from which option AMT can consume auction data.
2. `_spawn_engine()` starts the engine thread before registering it. A concurrent snapshot can observe no engine and receive an incomplete symbol state.
3. The current coordinator resolves futures and options in separate places. The option-to-futures mapping is reconstructed during each spawn instead of being part of one startup plan.
4. The shared feed has one primary queue per symbol. Option AMT needs a non-consuming copy of the underlying futures stream; directly sharing the primary queue would starve the futures engine.
5. The backend emits live quote changes frequently by design. The frontend chart compared JSON-decoded profile entries by object identity, so unchanged profiles still triggered overlay redraws on every update.

## Design

The coordinator will construct the active symbol set once per start/rescan:

```text
configured underlyings
        ↓
resolved front-month futures
        ↓
validated persisted options OR fresh option scan
        ↓
active futures + option symbols
        ↓
one engine plan with option → futures mapping
```

The persisted contract file remains a cache, not the authority for the current topology. When futures are enabled, a persisted selection is accepted only if it contains the required current futures symbols and valid option symbols for the configured underlyings. Otherwise it is discarded and rebuilt through the normal scanner.

The coordinator will use the existing `MultiplexedMarketFeed` as the sole producer. Each futures engine keeps its primary queue. Each option engine receives a dedicated reader queue registered against the matching futures symbol. Reader queues receive copies of ticks and are removed during engine shutdown. No second broker WebSocket and no second producer loop will be introduced.

Engine registration will complete before its thread starts. Shutdown will remove the engine from the registry and close its primary/reader gateways exactly once, preserving the current lock discipline.

The frontend will retain the current value-based profile comparison. No additional generic render/cache abstraction will be added.

## Scope

Included:

- current uncommitted feed fan-out changes;
- current chart profile equality fix;
- persisted contract validation and migration behavior;
- single startup mapping and lifecycle ordering;
- focused backend and frontend regression tests;
- verification against `stable_5` behavior and current `stable_6` tests.

Excluded:

- redesigning the AMT algorithm;
- changing trading thresholds or strategy decisions;
- replacing the WebSocket protocol;
- broad cleanup of unrelated scanner failures;
- adding dependencies or a new coordinator abstraction unless the existing functions cannot express the fix cleanly.

## Error and compatibility behavior

- A stale or option-only persisted contract file is treated as a cache miss and replaced through the normal scan path.
- If a selected option cannot map to an active futures symbol, the engine remains operational only through the existing explicit premium fallback, and startup logs the symbol and reason. Tests will distinguish this fallback from the normal underlying path.
- Reader queue shutdown must unblock a waiting engine with the same `None` sentinel semantics as primary queues.
- Existing persisted files are not deleted blindly; they are invalidated by being ignored and overwritten only after a successful replacement selection.

## Verification strategy

- Unit test the persisted topology validator with option-only, complete, stale, and mismatched-exchange files.
- Test startup ordering through a coordinator fixture that snapshots while engines are being created.
- Test one futures primary queue plus multiple option reader queues, proving no tick theft.
- Test that option engine bars and AMT state use futures prices while option quotes/depth remain attached to the option.
- Test frontend profile equality against separately decoded but equal profile objects.
- Run focused Python tests, all frontend tests, frontend type-check/build, and `git diff --check`.

