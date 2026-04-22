# Testing Strategy

<cite>
**Referenced Files in This Document**
- [conftest.py](file://backend/tests/conftest.py)
- [pytest.ini](file://backend/pytest.ini)
- [baseline_test_results.json](file://backend/tests/baseline_test_results.json)
- [test_trading_context.py](file://backend/tests/unit/test_trading_context.py)
- [test_composite_profile.py](file://backend/tests/unit/test_composite_profile.py)
- [test_market_state_engine.py](file://backend/tests/unit/domain/test_market_state_engine.py)
- [test_api_endpoints.py](file://backend/tests/integration/test_api_endpoints.py)
- [comparison_engine.py](file://backend/tests/validation/comparison_engine.py)
- [synthetic_market_data.py](file://backend/tests/validation/synthetic_market_data.py)
- [test_e2e_trading_lifecycle.py](file://backend/tests/integration/test_e2e_trading_lifecycle.py)
- [test_e2e_broker_mock.py](file://backend/tests/integration/test_e2e_broker_mock.py)
- [test_amt_handler.py](file://backend/tests/unit/application/test_amt_handler.py)
- [test_llm_entry_handler.py](file://backend/tests/unit/application/test_llm_entry_handler.py)
- [test_amt_handler.md](file://backend/tests/unit/application/test_amt_handler.md)
- [test_llm_entry_handler.md](file://backend/tests/unit/application/test_llm_entry_handler.md)
- [test_e2e_integration.py](file://appv2/backend/tests/test_e2e_integration.py)
- [test_production_services.py](file://appv2/backend/tests/test_production_services.py)
- [test_comprehensive_coverage.py](file://appv2/backend/tests/test_comprehensive_coverage.py)
- [test_edge_cases.py](file://appv2/backend/tests/test_edge_cases.py)
</cite>

## Update Summary
**Changes Made**
- Added comprehensive testing framework documentation for 14 E2E integration tests
- Documented 5 quorum-specific unit tests for AMTHandler and LLMEntryHandler
- Updated test suite organization to reflect production-ready test structure
- Enhanced validation testing with dual-run comparison and synthetic market data
- Added appv2 backend testing framework documentation

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document defines the comprehensive testing strategy for GlassyTrade AI v5. It outlines a multi-layered approach covering unit tests, integration tests, validation scenarios, and market data testing. The system now includes a production-ready test suite with 14 E2E integration tests and 5 quorum-specific unit tests, ensuring robust correctness, reliability, and maintainability across both backend and appv2 systems.

## Project Structure
The backend test suite is organized into three primary layers with enhanced coverage:
- Unit tests: Focused on isolated components and pure logic with comprehensive quorum-specific testing
- Integration tests: Validate end-to-end flows and API endpoints with extensive E2E scenarios
- Validation tests: Provide dual-run comparison and synthetic market data generation for stability and correctness

```mermaid
graph TB
subgraph "Unit Tests (Enhanced)"
U1["app.domain.*"]
U2["app.application.*"]
U3["app.infrastructure.*"]
U4["Quorum-specific tests<br/>5 specialized unit tests"]
end
subgraph "Integration Tests (14 E2E)"
I1["Full trading lifecycle"]
I2["Broker mock integration"]
I3["WebSocket server-driven mode"]
I4["Commission/slippage pipeline"]
I5["AI endpoints E2E"]
end
subgraph "Validation Tests"
V1["Dual-run comparison"]
V2["Synthetic market data"]
V3["Spec compliance"]
end
subgraph "Appv2 Backend Tests"
A1["Production services"]
A2["Comprehensive coverage"]
A3["Edge cases"]
A4["Advanced services"]
end
U1 --> I2
U2 --> I2
U3 --> I1
I1 --> V1
I2 --> V1
V2 --> V1
A1 --> A2
A2 --> A3
```

**Diagram sources**
- [test_e2e_trading_lifecycle.py:1-697](file://backend/tests/integration/test_e2e_trading_lifecycle.py#L1-L697)
- [test_e2e_broker_mock.py:1-779](file://backend/tests/integration/test_e2e_broker_mock.py#L1-L779)
- [test_amt_handler.py:1-624](file://backend/tests/unit/application/test_amt_handler.py#L1-L624)
- [test_llm_entry_handler.py:1-937](file://backend/tests/unit/application/test_llm_entry_handler.py#L1-L937)
- [test_e2e_integration.py:1-340](file://appv2/backend/tests/test_e2e_integration.py#L1-L340)

**Section sources**
- [conftest.py:1-35](file://backend/tests/conftest.py#L1-L35)
- [pytest.ini:1-9](file://backend/pytest.ini#L1-L9)

## Core Components
- Test configuration and environment:
  - Shared fixtures and path setup enable importing backend modules and stubbing subpackages
  - Pytest markers define unit, integration, and slow test categories
- Baseline results:
  - A JSON baseline captures historical pass/fail counts and floor expectations to track regression
- Enhanced test categories:
  - Unit: Pure logic, data models, domain services, and specialized quorum tests
  - Integration: API endpoints, trading lifecycle, cross-service flows, and E2E scenarios
  - Validation: Dual-run comparison and synthetic market data generation

**Section sources**
- [conftest.py:1-35](file://backend/tests/conftest.py#L1-L35)
- [pytest.ini:1-9](file://backend/pytest.ini#L1-L9)
- [baseline_test_results.json:1-28](file://backend/tests/baseline_test_results.json#L1-L28)

## Architecture Overview
The testing architecture enforces separation of concerns across layers and uses deterministic fixtures and synthetic data to ensure reproducibility. The enhanced framework now includes comprehensive E2E testing and specialized unit tests for critical components.

```mermaid
graph TB
T["Pytest Runner"] --> C["conftest.py<br/>Path & fixture setup"]
T --> U["Unit Tests<br/>(Enhanced with quorum tests)"]
T --> I["Integration Tests<br/>(14 E2E scenarios)"]
T --> V["Validation Tests"]
T --> A["Appv2 Backend Tests"]
U --> UT1["Domain logic tests"]
U --> UT2["Application services tests"]
U --> UT3["Infrastructure adapters tests"]
U --> QT1["AMTHandler quorum tests"]
U --> QT2["LLMEntryHandler quorum tests"]
I --> IE1["Full trading lifecycle"]
I --> IE2["Broker mock integration"]
I --> IE3["WebSocket server-driven mode"]
I --> IE4["Commission/slippage pipeline"]
V --> VC1["Dual-run comparer"]
V --> VS1["Synthetic market generator"]
A --> AT1["Production services"]
A --> AT2["Comprehensive coverage"]
A --> AT3["Edge case testing"]
```

**Diagram sources**
- [test_e2e_trading_lifecycle.py:85-186](file://backend/tests/integration/test_e2e_trading_lifecycle.py#L85-L186)
- [test_amt_handler.py:86-103](file://backend/tests/unit/application/test_amt_handler.py#L86-L103)
- [test_llm_entry_handler.py:190-282](file://backend/tests/unit/application/test_llm_entry_handler.py#L190-L282)
- [test_e2e_integration.py:81-100](file://appv2/backend/tests/test_e2e_integration.py#L81-L100)

## Detailed Component Analysis

### Unit Testing Strategy (Enhanced)
Unit tests focus on pure logic and isolated components with comprehensive quorum-specific testing. The enhanced framework now includes 5 specialized unit tests covering critical components:

#### Quorum-Specific Unit Tests
- **AMTHandler tests (5 tests)**: Cover initialization, argument delegation, volume profile rebuild strategies, day boundary handling, and error propagation
- **LLMEntryHandler tests (5 tests)**: Cover should_run gating, Three-Align gate, session phase filtering, LLM timeout handling, and response parsing

```mermaid
classDiagram
class AMTHandler {
+initialize()
+analyze(data, order_book, ...)
+incremental_update()
+day_boundary_reset()
+error_propagation()
}
class LLMEntryHandler {
+should_run()
+three_align_check()
+run_entry()
+timeout_guard()
+response_parsing()
}
class QuorumTestSuite {
+AH-01 : Initialization tests
+AH-02 : Argument delegation tests
+AH-03 : VP rebuild strategies
+AH-04 : Day boundary handling
+AH-05 : Error propagation
+EH-01 : should_run gating
+EH-02 : Three-Align gate
+EH-03 : Session phase filtering
+EH-04 : LLM timeout handling
+EH-05 : Response parsing
}
```

**Diagram sources**
- [test_amt_handler.py:86-103](file://backend/tests/unit/application/test_amt_handler.py#L86-L103)
- [test_llm_entry_handler.py:190-282](file://backend/tests/unit/application/test_llm_entry_handler.py#L190-L282)
- [test_amt_handler.md:18-40](file://backend/tests/unit/application/test_amt_handler.md#L18-L40)
- [test_llm_entry_handler.md:27-47](file://backend/tests/unit/application/test_llm_entry_handler.md#L27-L47)

**Updated** Enhanced with comprehensive quorum-specific testing for critical trading components

Practical examples:
- **AMTHandler quorum tests**: Test initialization with default state, analyze() delegation to internal services, VP rebuild strategies, day boundary resets, and error propagation
- **LLMEntryHandler quorum tests**: Test should_run pre-flight checks, Three-Align gate evaluation, session phase filtering, LLM timeout handling, and response parsing with proper error resilience

**Section sources**
- [test_amt_handler.py:1-624](file://backend/tests/unit/application/test_amt_handler.py#L1-L624)
- [test_llm_entry_handler.py:1-937](file://backend/tests/unit/application/test_llm_entry_handler.py#L1-L937)
- [test_amt_handler.md:1-166](file://backend/tests/unit/application/test_amt_handler.md#L1-L166)
- [test_llm_entry_handler.md:1-303](file://backend/tests/unit/application/test_llm_entry_handler.md#L1-L303)

### Integration Testing Strategy (14 E2E Scenarios)
Integration tests validate end-to-end flows and API endpoints using FastAPI's TestClient. The enhanced framework now includes 14 comprehensive E2E integration tests covering:

#### Full Trading Lifecycle E2E Tests
- Complete trading pipeline from tick ingestion through analysis, signal generation, position management, and portfolio accounting
- WebSocket server-driven mode with proper configuration and history loading
- System control endpoints for halt/resume operations and risk state monitoring
- Commission and slippage pipeline integration with exact P&L arithmetic verification

#### Broker Mock Integration E2E Tests
- Full profitable trade simulation with entry, partial exits, and trailing stops
- Losing trade scenarios with SL hits and proper position closure
- Circuit breaker integration preventing entries after consecutive losses
- Multiple symbol management with independent position tracking

```mermaid
sequenceDiagram
participant Client as "TestClient"
participant Trading as "TradingSessionService"
participant Broker as "PaperBrokerAdapter"
participant Portfolio as "Portfolio"
Client->>Trading : Process tick (N candles)
Trading->>Portfolio : Update state
Portfolio->>Portfolio : Calculate P&L
Portfolio->>Broker : Execute orders (if applicable)
Broker-->>Portfolio : Fill confirmations
Portfolio-->>Trading : Closed positions
Trading-->>Client : Portfolio state with equity history
```

**Diagram sources**
- [test_e2e_trading_lifecycle.py:91-171](file://backend/tests/integration/test_e2e_trading_lifecycle.py#L91-L171)
- [test_e2e_broker_mock.py:226-281](file://backend/tests/integration/test_e2e_broker_mock.py#L226-L281)

**Updated** Expanded from basic integration tests to comprehensive 14 E2E scenarios covering complete trading lifecycle

Practical examples:
- **Full trading lifecycle**: Feed 200 volatile candles and verify state shape, position opens with slipped entry, and commission/slippage accounting
- **WebSocket integration**: Server-driven mode with proper configuration messages and history loading
- **Broker mock testing**: Full profitable trade with partial exits and trailing stops, losing trade with SL hits
- **Circuit breaker testing**: Prevent entries after consecutive losses and account loss limit breaches

**Section sources**
- [test_e2e_trading_lifecycle.py:1-697](file://backend/tests/integration/test_e2e_trading_lifecycle.py#L1-L697)
- [test_e2e_broker_mock.py:1-779](file://backend/tests/integration/test_e2e_broker_mock.py#L1-L779)

### Validation Testing Strategy
Validation tests ensure behavioral parity and correctness under controlled conditions:
- Dual-run comparison engine compares old vs new codepaths tick-by-tick and reports mismatches
- Synthetic market data generator creates realistic scenarios with expected outcomes for AMT validation

```mermaid
flowchart TD
Start(["Start Dual-Run"]) --> TickLoop["For each tick"]
TickLoop --> OldPath["Run old pipeline"]
TickLoop --> NewPath["Run new pipeline"]
OldPath --> Compare["Compare state dicts"]
NewPath --> Compare
Compare --> Mismatch{"Mismatch?"}
Mismatch --> |No| NextTick["Next tick"]
Mismatch --> |Yes| Record["Record mismatch<br/>with key, values, tolerance"]
Record --> NextTick
NextTick --> Done{"All ticks processed?"}
Done --> |No| TickLoop
Done --> |Yes| Report["Generate report<br/>mismatches, max error, detail keys"]
Report --> End(["Assert clean or handle mismatches"])
```

**Diagram sources**
- [comparison_engine.py:47-175](file://backend/tests/validation/comparison_engine.py#L47-L175)

Practical examples:
- Using the dual-run comparer: Initialize with a small tolerance, compare old and new state dictionaries for each tick, and assert zero mismatches or analyze the report
- Generating synthetic market scenarios: Use generators for balanced rotation, displacement legs, pullbacks to LVN, and aggressive candles with expected market state outcomes

**Section sources**
- [comparison_engine.py:1-194](file://backend/tests/validation/comparison_engine.py#L1-L194)
- [synthetic_market_data.py:1-405](file://backend/tests/validation/synthetic_market_data.py#L1-L405)

### Appv2 Backend Testing Framework
The appv2 backend includes a comprehensive testing framework with specialized test suites:

#### Production Services Tests
- Position reconciliation with matched and mismatched scenarios
- Signal TTL management with duplicate detection and TTL enforcement
- Post-trade analytics with comprehensive statistics computation
- Trade journal lifecycle with JSONL file generation and validation

#### Comprehensive Coverage Tests
- Domain service testing for break detection, drive tracking, entry zones, and exposure monitoring
- Multi-timeframe analysis with alignment scoring and directional consistency
- Order flow detectors including big trade detection, absorption patterns, and volume bubbles
- Advanced trading components like volatility adjustment, trail engines, and strike selection

#### Edge Case Tests
- Market state detection for gap opens above VAH and below VAL
- Low liquidity filtering with OI, volume, and spread thresholds
- Session phase handling during opening noise periods
- Order retry mechanisms with exponential backoff and max caps

```mermaid
graph TB
subgraph "Production Services"
PS1["Position Reconciliation"]
PS2["Signal TTL Management"]
PS3["Post-Trade Analytics"]
PS4["Trade Journal"]
end
subgraph "Comprehensive Coverage"
CC1["Domain Service Testing"]
CC2["Multi-Timeframe Analysis"]
CC3["Order Flow Detection"]
CC4["Advanced Trading Components"]
end
subgraph "Edge Case Testing"
EC1["Market State Edge Cases"]
EC2["Liquidity Filtering"]
EC3["Session Phase Handling"]
EC4["Order Retry Mechanisms"]
end
PS1 --> CC1
CC1 --> EC1
```

**Diagram sources**
- [test_production_services.py:20-80](file://appv2/backend/tests/test_production_services.py#L20-L80)
- [test_comprehensive_coverage.py:37-120](file://appv2/backend/tests/test_comprehensive_coverage.py#L37-L120)
- [test_edge_cases.py:18-47](file://appv2/backend/tests/test_edge_cases.py#L18-L47)

**Updated** Added comprehensive appv2 backend testing framework with production services, coverage, and edge case testing

**Section sources**
- [test_production_services.py:1-173](file://appv2/backend/tests/test_production_services.py#L1-L173)
- [test_comprehensive_coverage.py:1-632](file://appv2/backend/tests/test_comprehensive_coverage.py#L1-L632)
- [test_edge_cases.py:1-156](file://appv2/backend/tests/test_edge_cases.py#L1-L156)

### Backtesting Capabilities
Backtesting is supported through dedicated scripts and validation scenarios:
- Scripts for running backtests and generating datasets are located under backend/scripts/
- Validation scenarios encode expected outcomes for AMT pipelines, enabling scenario-based testing and regression checks
- Appv2 includes comprehensive coverage testing for multi-timeframe analysis and advanced trading components

Guidelines:
- Use synthetic market data to construct long/short mean reversion, trend continuation, and no-trade scenarios
- Run backtests over multi-session windows to validate weekly bias alignment and confidence adjustments
- Track performance metrics and ensure parity with expected outcomes
- Leverage the 14 E2E integration tests as production-ready validation scenarios

## Dependency Analysis
The test suite relies on:
- Pytest configuration and markers for categorization and execution control
- Shared fixtures for path resolution and module stubbing
- TestClient for API integration tests
- Validation utilities for dual-run comparisons and synthetic data
- Enhanced appv2 testing framework with specialized test suites

```mermaid
graph TB
P["pytest.ini"] --> M["Markers: unit, integration, slow"]
C["conftest.py"] --> R["Root path injection"]
C --> S["Module stubs"]
I["integration tests"] --> TC["FastAPI TestClient"]
I --> E2E["14 E2E Scenarios"]
V["validation tests"] --> DC["DualRunComparer"]
V --> SM["SyntheticMarketData"]
A["appv2 tests"] --> PS["Production Services"]
A --> CC["Comprehensive Coverage"]
A --> EC["Edge Cases"]
```

**Diagram sources**
- [pytest.ini:1-9](file://backend/pytest.ini#L1-L9)
- [conftest.py:1-35](file://backend/tests/conftest.py#L1-L35)
- [test_e2e_trading_lifecycle.py:192-208](file://backend/tests/integration/test_e2e_trading_lifecycle.py#L192-L208)
- [test_production_services.py:20-34](file://appv2/backend/tests/test_production_services.py#L20-L34)

**Section sources**
- [pytest.ini:1-9](file://backend/pytest.ini#L1-L9)
- [conftest.py:1-35](file://backend/tests/conftest.py#L1-L35)

## Performance Considerations
- Use the slow marker to exclude heavy tests from quick runs and schedule them separately
- Prefer synthetic data and deterministic fixtures to avoid flakiness and reduce runtime variance
- For dual-run comparisons, tune tolerance to account for numerical precision while maintaining strictness for functional correctness
- Monitor pass rates and regressions using the baseline results JSON to maintain quality floors
- **Updated**: Leverage the 14 E2E integration tests for comprehensive performance validation across complete trading scenarios

**Section sources**
- [pytest.ini:6-6](file://backend/pytest.ini#L6-L6)
- [baseline_test_results.json:1-28](file://backend/tests/baseline_test_results.json#L1-L28)

## Troubleshooting Guide
Common issues and resolutions:
- Import errors in tests: Ensure project root and backend root are added to sys.path via conftest
- Network or hardware dependencies: Mock at the test level; avoid global mocks
- API test failures: Override dependencies locally using dependency_overrides or monkeypatch for specific endpoints
- Dual-run mismatches: Inspect the last mismatches in the report and adjust tolerance or fix divergent logic
- **Updated**: E2E test failures: Use the comprehensive 14 E2E scenarios to isolate specific pipeline failures and verify complete trading lifecycle correctness

**Section sources**
- [conftest.py:1-35](file://backend/tests/conftest.py#L1-L35)
- [test_api_endpoints.py:65-72](file://backend/tests/integration/test_api_endpoints.py#L65-L72)
- [test_api_endpoints.py:191-219](file://backend/tests/integration/test_api_endpoints.py#L191-L219)
- [comparison_engine.py:161-194](file://backend/tests/validation/comparison_engine.py#L161-L194)

## Conclusion
GlassyTrade AI v5 employs a robust, layered testing strategy that ensures correctness, reliability, and maintainability. The enhanced framework now includes 14 comprehensive E2E integration tests, 5 quorum-specific unit tests, and production-ready test suites across both backend and appv2 systems. Unit tests isolate logic, integration tests validate end-to-end flows, and validation tests enforce behavioral parity and scenario-driven correctness. By leveraging synthetic data, dual-run comparisons, structured baselining, and comprehensive E2E scenarios, the system maintains a high-quality floor and supports continuous improvement.

## Appendices

### Continuous Integration Workflows
- Configure CI to run unit tests, integration tests, validation tests, and appv2 test suites with appropriate markers
- Use the slow marker to separate heavy tests from quick feedback loops
- Publish baseline results and reports to monitor trends and regressions
- **Updated**: Include the 14 E2E integration tests in CI pipelines for comprehensive validation

### Test Coverage Analysis
- Maintain coverage targets for critical domains (domain, application, infrastructure)
- Use coverage tools to identify untested branches and increase targeted tests
- Focus on edge cases exposed by synthetic scenarios, dual-run comparisons, and comprehensive E2E testing
- **Updated**: Ensure comprehensive coverage of the 5 quorum-specific unit tests and 14 E2E integration scenarios