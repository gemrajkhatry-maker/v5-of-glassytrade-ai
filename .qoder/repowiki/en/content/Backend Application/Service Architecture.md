# Service Architecture

<cite>
**Referenced Files in This Document**
- [backend/app/main.py](file://backend/app/main.py)
- [backend/app/api/dependencies.py](file://backend/app/api/dependencies.py)
- [backend/app/config.py](file://backend/app/config.py)
- [backend/app/config_models/loader.py](file://backend/app/config_models/loader.py)
- [backend/app/config_models/validator.py](file://backend/app/config_models/validator.py)
- [backend/config/base.yaml](file://backend/config/base.yaml)
- [backend/config/environments/development.yaml](file://backend/config/environments/development.yaml)
- [backend/config/feature_flags.yaml](file://backend/config/feature_flags.yaml)
- [backend/app/shared/timezones.py](file://backend/app/shared/timezones.py)
- [backend/app/domain/models/exchange_config.py](file://backend/app/domain/models/exchange_config.py)
- [backend/app/domain/services/symbol_registry.py](file://backend/app/domain/services/symbol_registry.py)
- [backend/app/infrastructure/adapters/paper_broker.py](file://backend/app/infrastructure/adapters/paper_broker.py)
- [backend/app/infrastructure/adapters/dhan_adapter.py](file://backend/app/infrastructure/adapters/dhan_adapter.py)
- [backend/app/application/service_graph.py](file://backend/app/application/service_graph.py)
- [backend/app/domain/services/volume_profile_service.py](file://backend/app/domain/services/volume_profile_service.py)
- [backend/app/domain/services/market_state_classifier.py](file://backend/app/domain/services/market_state_classifier.py)
- [backend/app/domain/fabio_ai/services/option_scanner.py](file://backend/app/domain/fabio_ai/services/option_scanner.py)
- [backend/app/domain/fabio_ai/services/vp_contract_selector.py](file://backend/app/domain/fabio_ai/services/vp_contract_selector.py)
</cite>

## Update Summary
**Changes Made**
- Added new VolumeProfileService for computing volume profiles from OHLCV data
- Integrated MarketStateClassifier for classifying market structure based on price action and volume
- Enhanced OptionScannerService with parallel processing capabilities using ThreadPoolExecutor
- Added VPContractSelector for Volume Profile-based contract selection replacing momentum-based approach
- Updated service graph to include new services and their dependencies
- Enhanced dependency injection system to support new architectural components

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
This document explains the GlassyTrade AI service architecture patterns with a focus on:
- Dependency Injection (DI) and the service graph creation mechanism
- Configuration management across environments and feature flags
- Utility and shared components supporting cross-cutting concerns
- Timezone handling and other shared utilities
- Practical examples of service wiring, dependency resolution, and architectural patterns such as Ports & Adapters and Hexagonal Architecture
- Service lifecycle management, startup sequence, and graceful shutdown
- **Updated** Enhanced with new VolumeProfileService, MarketStateClassifier, and parallel processing capabilities

## Project Structure
The backend is organized around a layered, modular structure emphasizing separation of concerns:
- Application layer: API routers, handlers, and services orchestrating trading logic
- Domain layer: Models, ports, services, and domain-specific logic
- Infrastructure layer: Adapters, storage, and external integrations
- Shared layer: Cross-cutting utilities and configuration
- Config layer: YAML-based configuration hierarchy with environment overrides and feature flags

```mermaid
graph TB
subgraph "App Layer"
MAIN["main.py"]
DEPS["api/dependencies.py"]
end
subgraph "Domain Layer"
EXCFG["domain/models/exchange_config.py"]
SYMBOLREG["domain/services/symbol_registry.py"]
VPS["domain/services/volume_profile_service.py"]
MSC["domain/services/market_state_classifier.py"]
OS["domain/fabio_ai/services/option_scanner.py"]
VPSEL["domain/fabio_ai/services/vp_contract_selector.py"]
end
subgraph "Infrastructure Layer"
DHALAD["infrastructure/adapters/dhan_adapter.py"]
PAPER["infrastructure/adapters/paper_broker.py"]
end
subgraph "Config Layer"
CFGPY["app/config.py"]
LOADER["config_models/loader.py"]
VALIDATOR["config_models/validator.py"]
BASEYAML["config/base.yaml"]
ENVDEV["config/environments/development.yaml"]
FLAGS["config/feature_flags.yaml"]
end
MAIN --> DEPS
DEPS --> EXCFG
DEPS --> SYMBOLREG
DEPS --> VPS
DEPS --> MSC
DEPS --> OS
DEPS --> VPSEL
DEPS --> DHALAD
DEPS --> PAPER
CFGPY --> LOADER
LOADER --> VALIDATOR
LOADER --> BASEYAML
LOADER --> ENVDEV
LOADER --> FLAGS
```

**Diagram sources**
- [backend/app/main.py:171-176](file://backend/app/main.py#L171-L176)
- [backend/app/api/dependencies.py:63-118](file://backend/app/api/dependencies.py#L63-L118)
- [backend/app/config.py:26-156](file://backend/app/config.py#L26-L156)
- [backend/app/config_models/loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)
- [backend/app/config_models/validator.py:22-176](file://backend/app/config_models/validator.py#L22-L176)
- [backend/config/base.yaml:1-493](file://backend/config/base.yaml#L1-L493)
- [backend/config/environments/development.yaml:1-33](file://backend/config/environments/development.yaml#L1-L33)
- [backend/config/feature_flags.yaml:1-37](file://backend/config/feature_flags.yaml#L1-L37)
- [backend/app/domain/models/exchange_config.py:20-307](file://backend/app/domain/models/exchange_config.py#L20-L307)
- [backend/app/domain/services/symbol_registry.py:19-94](file://backend/app/domain/services/symbol_registry.py#L19-L94)
- [backend/app/domain/services/volume_profile_service.py:10-137](file://backend/app/domain/services/volume_profile_service.py#L10-L137)
- [backend/app/domain/services/market_state_classifier.py:10-97](file://backend/app/domain/services/market_state_classifier.py#L10-L97)
- [backend/app/domain/fabio_ai/services/option_scanner.py:40-512](file://backend/app/domain/fabio_ai/services/option_scanner.py#L40-L512)
- [backend/app/domain/fabio_ai/services/vp_contract_selector.py:76-641](file://backend/app/domain/fabio_ai/services/vp_contract_selector.py#L76-L641)
- [backend/app/infrastructure/adapters/dhan_adapter.py:66-457](file://backend/app/infrastructure/adapters/dhan_adapter.py#L66-L457)
- [backend/app/infrastructure/adapters/paper_broker.py:118-199](file://backend/app/infrastructure/adapters/paper_broker.py#L118-L199)

**Section sources**
- [backend/app/main.py:1-227](file://backend/app/main.py#L1-L227)
- [backend/app/api/dependencies.py:1-118](file://backend/app/api/dependencies.py#L1-L118)
- [backend/app/config.py:1-157](file://backend/app/config.py#L1-L157)
- [backend/app/config_models/loader.py:1-288](file://backend/app/config_models/loader.py#L1-L288)
- [backend/app/config_models/validator.py:1-177](file://backend/app/config_models/validator.py#L1-L177)
- [backend/config/base.yaml:1-493](file://backend/config/base.yaml#L1-L493)
- [backend/config/environments/development.yaml:1-33](file://backend/config/environments/development.yaml#L1-L33)
- [backend/config/feature_flags.yaml:1-37](file://backend/config/feature_flags.yaml#L1-L37)
- [backend/app/domain/models/exchange_config.py:1-307](file://backend/app/domain/models/exchange_config.py#L1-L307)
- [backend/app/domain/services/symbol_registry.py:1-94](file://backend/app/domain/services/symbol_registry.py#L1-L94)
- [backend/app/domain/services/volume_profile_service.py:1-137](file://backend/app/domain/services/volume_profile_service.py#L1-L137)
- [backend/app/domain/services/market_state_classifier.py:1-97](file://backend/app/domain/services/market_state_classifier.py#L1-L97)
- [backend/app/domain/fabio_ai/services/option_scanner.py:1-512](file://backend/app/domain/fabio_ai/services/option_scanner.py#L1-L512)
- [backend/app/domain/fabio_ai/services/vp_contract_selector.py:1-641](file://backend/app/domain/fabio_ai/services/vp_contract_selector.py#L1-L641)
- [backend/app/infrastructure/adapters/dhan_adapter.py:1-457](file://backend/app/infrastructure/adapters/dhan_adapter.py#L1-L457)
- [backend/app/infrastructure/adapters/paper_broker.py:1-199](file://backend/app/infrastructure/adapters/paper_broker.py#L1-L199)

## Core Components
- Service Graph Factory: Builds and wires the entire service graph once at startup, exposing singleton instances via FastAPI dependency helpers.
- Configuration Loader and Validator: Loads YAML hierarchy, merges environment overrides, parses typed configuration, validates rules, and logs a startup summary.
- Adapter Layer: Implements ports for market data, broker, LLM inference, and storage; integrates with external systems.
- Domain Services: Provide exchange abstraction, symbol registry, and session context factories.
- **Updated** New Services: VolumeProfileService for computing volume profiles, MarketStateClassifier for market state classification, and enhanced OptionScannerService with parallel processing.
- Shared Utilities: Timezone constants and configuration base settings.

Key responsibilities:
- DI and Service Wiring: Centralized in the service graph factory; FastAPI dependencies resolve from the singleton graph.
- Configuration Management: Hierarchical YAML loading with environment-specific overrides and feature flags.
- Cross-Cutting Concerns: Structured logging, rate limiting, CORS, and timezone handling.
- **Updated** Parallel Processing: OptionScannerService now supports parallel underling processing for improved performance.

**Section sources**
- [backend/app/api/dependencies.py:63-118](file://backend/app/api/dependencies.py#L63-L118)
- [backend/app/config_models/loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)
- [backend/app/config_models/validator.py:22-176](file://backend/app/config_models/validator.py#L22-L176)
- [backend/app/infrastructure/adapters/dhan_adapter.py:66-457](file://backend/app/infrastructure/adapters/dhan_adapter.py#L66-L457)
- [backend/app/infrastructure/adapters/paper_broker.py:118-199](file://backend/app/infrastructure/adapters/paper_broker.py#L118-L199)
- [backend/app/domain/models/exchange_config.py:20-307](file://backend/app/domain/models/exchange_config.py#L20-L307)
- [backend/app/domain/services/symbol_registry.py:19-94](file://backend/app/domain/services/symbol_registry.py#L19-L94)
- [backend/app/domain/services/volume_profile_service.py:10-137](file://backend/app/domain/services/volume_profile_service.py#L10-L137)
- [backend/app/domain/services/market_state_classifier.py:10-97](file://backend/app/domain/services/market_state_classifier.py#L10-L97)
- [backend/app/domain/fabio_ai/services/option_scanner.py:306-356](file://backend/app/domain/fabio_ai/services/option_scanner.py#L306-L356)
- [backend/app/shared/timezones.py:14-16](file://backend/app/shared/timezones.py#L14-L16)

## Architecture Overview
GlassyTrade AI follows a layered architecture aligned with Ports & Adapters and Hexagonal Architecture:
- Domain layer defines contracts (ports) and core business logic
- Infrastructure layer implements adapters for external systems
- Application layer orchestrates services and exposes HTTP APIs
- Configuration and shared utilities provide cross-cutting capabilities
- **Updated** New domain services provide specialized analysis capabilities

```mermaid
graph TB
CLIENT["Client / Frontend"]
API["FastAPI App"]
DEPS["Service Graph Factory"]
EXCFG["ExchangeConfig"]
SYMBOLREG["SymbolRegistry"]
VPS["VolumeProfileService"]
MSC["MarketStateClassifier"]
OS["OptionScannerService"]
VPSEL["VPContractSelector"]
MD["MarketDataPort Adapter"]
BROKER["BrokerPort Adapter"]
LLM["LLMInferencePort Adapter"]
STORAGE["StoragePort Adapter"]
GENAI["GenerativeAIService"]
SESSION["TradingSessionService"]
CLIENT --> API
API --> DEPS
DEPS --> EXCFG
DEPS --> SYMBOLREG
DEPS --> VPS
DEPS --> MSC
DEPS --> OS
DEPS --> VPSEL
DEPS --> MD
DEPS --> BROKER
DEPS --> LLM
DEPS --> STORAGE
DEPS --> GENAI
DEPS --> SESSION
```

**Diagram sources**
- [backend/app/main.py:171-176](file://backend/app/main.py#L171-L176)
- [backend/app/api/dependencies.py:63-118](file://backend/app/api/dependencies.py#L63-L118)

## Detailed Component Analysis

### Dependency Injection and Service Graph Creation
The service graph is created once at startup and exposed via FastAPI dependency helpers. It wires:
- Exchange abstraction: ExchangeConfig and Strategy
- Symbol registry and session factory
- Market data adapter (Dhan)
- Broker adapter (Paper)
- LLM inference adapter (MLX/GGUF)
- Generative AI service
- Probability inference adapter (LightGBM)
- Storage adapter (SQLite) wrapped in an async persistence bus
- Trading session service and auxiliary services (alert manager, composite profile, gate rejection tracker, latency tracker, signal tracker, OI analyzer, NPOC tracker, VP contract selector)
- **Updated** New services: VolumeProfileService, MarketStateClassifier, and enhanced OptionScannerService

```mermaid
classDiagram
class ServiceGraph {
+exchange_config
+symbol_registry
+exchange_strategy
+session_factory
+market_data
+broker
+llm_inference
+gen_ai_service
+probability_engine
+composite_profile
+alert_manager
+delta_profile
+vp_contract_selector
+trading_session
+npoc_tracker
+gate_tracker
+latency_tracker
+oi_analyzer
+signal_tracker
+storage
+engine
+active_symbols
+vp_result
+volume_profile_service
+market_state_classifier
+option_scanner_service
}
class ExchangeConfig
class SymbolRegistry
class VolumeProfileService
class MarketStateClassifier
class OptionScannerService
class VPContractSelector
class DhanMarketDataAdapter
class PaperBrokerAdapter
class MLXInferenceAdapter
class LGBMProbabilityAdapter
class GenerativeAIService
class TradingSessionService
ServiceGraph --> ExchangeConfig : "holds"
ServiceGraph --> SymbolRegistry : "holds"
ServiceGraph --> VolumeProfileService : "holds"
ServiceGraph --> MarketStateClassifier : "holds"
ServiceGraph --> OptionScannerService : "holds"
ServiceGraph --> VPContractSelector : "holds"
ServiceGraph --> DhanMarketDataAdapter : "holds"
ServiceGraph --> PaperBrokerAdapter : "holds"
ServiceGraph --> MLXInferenceAdapter : "holds"
ServiceGraph --> LGBMProbabilityAdapter : "holds"
ServiceGraph --> GenerativeAIService : "holds"
ServiceGraph --> TradingSessionService : "holds"
```

**Diagram sources**
- [backend/app/api/dependencies.py:63-118](file://backend/app/api/dependencies.py#L63-L118)
- [backend/app/application/service_graph.py:25-388](file://backend/app/application/service_graph.py#L25-L388)
- [backend/app/domain/models/exchange_config.py:20-307](file://backend/app/domain/models/exchange_config.py#L20-L307)
- [backend/app/domain/services/symbol_registry.py:19-94](file://backend/app/domain/services/symbol_registry.py#L19-L94)
- [backend/app/domain/services/volume_profile_service.py:10-137](file://backend/app/domain/services/volume_profile_service.py#L10-L137)
- [backend/app/domain/services/market_state_classifier.py:10-97](file://backend/app/domain/services/market_state_classifier.py#L10-L97)
- [backend/app/domain/fabio_ai/services/option_scanner.py:40-512](file://backend/app/domain/fabio_ai/services/option_scanner.py#L40-L512)
- [backend/app/domain/fabio_ai/services/vp_contract_selector.py:76-641](file://backend/app/domain/fabio_ai/services/vp_contract_selector.py#L76-L641)
- [backend/app/infrastructure/adapters/dhan_adapter.py:66-457](file://backend/app/infrastructure/adapters/dhan_adapter.py#L66-L457)
- [backend/app/infrastructure/adapters/paper_broker.py:118-199](file://backend/app/infrastructure/adapters/paper_broker.py#L118-L199)

Practical examples:
- Service wiring: The factory constructs adapters and services, initializes async persistence, and pre-warms the broker and scanners.
- Dependency resolution: FastAPI dependency helpers return singleton instances from the service graph.
- Strategy pattern: Exchange strategy is selected at startup based on ExchangeConfig.
- **Updated** Parallel processing: OptionScannerService uses ThreadPoolExecutor for parallel underling processing when enabled.

**Section sources**
- [backend/app/api/dependencies.py:63-118](file://backend/app/api/dependencies.py#L63-L118)
- [backend/app/application/service_graph.py:25-388](file://backend/app/application/service_graph.py#L25-L388)
- [backend/app/domain/fabio_ai/services/option_scanner.py:306-356](file://backend/app/domain/fabio_ai/services/option_scanner.py#L306-L356)

### Configuration Management System
Configuration is loaded from a YAML hierarchy with strict merge order:
1. base.yaml: Establishes defaults
2. environments/{GLASSYTRADE_ENV}.yaml: Deep-merge overrides base
3. strategies/*.yaml: Deep-merge overrides result
4. feature_flags.yaml: Feature flags
5. Environment variables: Secrets only
6. Typed SystemConfig: Immutable, frozen
7. Validation: ConfigValidator runs hard and warning rules
8. Logging: Startup summary

```mermaid
flowchart TD
Start(["Load Config"]) --> Base["Load base.yaml"]
Base --> Env["Load environments/GLASSYTRADE_ENV.yaml"]
Env --> Merge1["Deep-merge base + env"]
Merge1 --> Strat["Load strategies/*.yaml"]
Strat --> Merge2["Deep-merge result + strategies"]
Merge2 --> Flags["Load feature_flags.yaml"]
Flags --> Merge3["Deep-merge result + flags"]
Merge3 --> EnvVars["Read secrets from env vars"]
EnvVars --> Typed["Parse into typed SystemConfig"]
Typed --> Validate["Run ConfigValidator"]
Validate --> Summary["Log startup summary"]
Summary --> End(["Config Ready"])
```

**Diagram sources**
- [backend/app/config_models/loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)
- [backend/app/config_models/validator.py:22-176](file://backend/app/config_models/validator.py#L22-L176)
- [backend/config/base.yaml:1-493](file://backend/config/base.yaml#L1-L493)
- [backend/config/environments/development.yaml:1-33](file://backend/config/environments/development.yaml#L1-L33)
- [backend/config/feature_flags.yaml:1-37](file://backend/config/feature_flags.yaml#L1-L37)

Environment-specific settings:
- Development environment restricts symbols and relaxes risk parameters.
- Feature flags enable/disable components and roles (e.g., LLM advisory, risk tier engine).

Feature flags:
- Short signals, risk tier engine, initial balance engine, correlation guard, LLM roles, and infrastructure flags.

**Section sources**
- [backend/app/config_models/loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)
- [backend/app/config_models/validator.py:22-176](file://backend/app/config_models/validator.py#L22-L176)
- [backend/config/environments/development.yaml:1-33](file://backend/config/environments/development.yaml#L1-L33)
- [backend/config/feature_flags.yaml:1-37](file://backend/config/feature_flags.yaml#L1-L37)

### Adapter Layer and Ports & Adapters Pattern
Adapters implement domain ports to integrate with external systems:
- MarketDataPort: DhanMarketDataAdapter provides historical data, quotes, streaming, and fallback polling
- BrokerPort: PaperBrokerAdapter simulates order execution with realistic cost modeling
- LLMInferencePort: MLXInferenceAdapter/GGUFInferenceAdapter provides model loading, readiness checks, and validation
- StoragePort: SQLiteStorageAdapter wrapped by AsyncPersistenceBus for async writes

```mermaid
classDiagram
class MarketDataPort
class BrokerPort
class LLMInferencePort
class StoragePort
class DhanMarketDataAdapter {
+ensure_initialized_sync()
+fetch_history()
+stream_full()
+stream_poll()
+stream_depth_20()
+close_sync()
}
class PaperBrokerAdapter {
+execute_order()
+compute_exit_costs()
+cancel_order()
}
class MLXInferenceAdapter {
+wait_until_ready()
+validate()
}
class GGUFInferenceAdapter {
+wait_until_ready()
+validate()
}
class SQLiteStorageAdapter
class AsyncPersistenceBus
DhanMarketDataAdapter ..|> MarketDataPort
PaperBrokerAdapter ..|> BrokerPort
MLXInferenceAdapter ..|> LLMInferencePort
GGUFInferenceAdapter ..|> LLMInferencePort
SQLiteStorageAdapter --> AsyncPersistenceBus : "wrapped by"
AsyncPersistenceBus ..|> StoragePort
```

**Diagram sources**
- [backend/app/infrastructure/adapters/dhan_adapter.py:66-457](file://backend/app/infrastructure/adapters/dhan_adapter.py#L66-L457)
- [backend/app/infrastructure/adapters/paper_broker.py:118-199](file://backend/app/infrastructure/adapters/paper_broker.py#L118-L199)
- [backend/app/api/dependencies.py:56-75](file://backend/app/api/dependencies.py#L56-L75)

**Section sources**
- [backend/app/infrastructure/adapters/dhan_adapter.py:66-457](file://backend/app/infrastructure/adapters/dhan_adapter.py#L66-L457)
- [backend/app/infrastructure/adapters/paper_broker.py:118-199](file://backend/app/infrastructure/adapters/paper_broker.py#L118-L199)
- [backend/app/api/dependencies.py:56-75](file://backend/app/api/dependencies.py#L56-L75)

### Domain Abstractions and Shared Utilities
- ExchangeConfig: Immutable configuration for NSE/MCX with exchange-specific defaults, thresholds, and tick/lot sizes
- SymbolRegistry: Centralized exchange detection and symbol categorization
- **Updated** VolumeProfileService: Computes volume profiles from OHLCV data using histogram-based approach
- **Updated** MarketStateClassifier: Classifies market structure based on price action and volume profile characteristics
- **Updated** OptionScannerService: Enhanced with parallel processing capabilities for improved performance
- **Updated** VPContractSelector: Implements Volume Profile-based contract selection replacing momentum-based approach
- Timezone utilities: Consistent IST usage across the system

```mermaid
classDiagram
class ExchangeConfig {
+exchange
+underlyings
+default_symbol
+scanner_underlying
+scanner_underlyings
+aggression_sigma
+displacement_multiplier
+balance_ratio_threshold
+cvd_block_threshold
+warm_up_minutes
+llm_instruction
+eia_symbols
+eia_suppression_minutes
+tick_sizes
+lot_sizes
+point_values
+get_tick_size()
+get_lot_size()
+get_point_value()
+for_exchange()
+from_dict()
}
class SymbolRegistry {
+mcx_underlyings
+nse_underlyings
+exchange_for()
+is_mcx()
+is_nse()
+is_option()
+all_underlyings()
+from_exchange_configs()
}
class VolumeProfileService {
+compute_profile()
+_compute_value_area()
}
class MarketStateClassifier {
+classify()
+_is_trending()
+_is_balanced()
}
class OptionScannerService {
+scan_top_n()
+_scan_underlying_for_contracts()
+_process_contract()
+update_market_context()
}
class VPContractSelector {
+select_contracts()
+_compute_volume_profile()
+_classify_market_state()
+_select_by_state()
}
class IST
```

**Diagram sources**
- [backend/app/domain/models/exchange_config.py:20-307](file://backend/app/domain/models/exchange_config.py#L20-L307)
- [backend/app/domain/services/symbol_registry.py:19-94](file://backend/app/domain/services/symbol_registry.py#L19-L94)
- [backend/app/domain/services/volume_profile_service.py:10-137](file://backend/app/domain/services/volume_profile_service.py#L10-L137)
- [backend/app/domain/services/market_state_classifier.py:10-97](file://backend/app/domain/services/market_state_classifier.py#L10-L97)
- [backend/app/domain/fabio_ai/services/option_scanner.py:40-512](file://backend/app/domain/fabio_ai/services/option_scanner.py#L40-L512)
- [backend/app/domain/fabio_ai/services/vp_contract_selector.py:76-641](file://backend/app/domain/fabio_ai/services/vp_contract_selector.py#L76-L641)
- [backend/app/shared/timezones.py:14-16](file://backend/app/shared/timezones.py#L14-L16)

**Section sources**
- [backend/app/domain/models/exchange_config.py:20-307](file://backend/app/domain/models/exchange_config.py#L20-L307)
- [backend/app/domain/services/symbol_registry.py:19-94](file://backend/app/domain/services/symbol_registry.py#L19-L94)
- [backend/app/domain/services/volume_profile_service.py:10-137](file://backend/app/domain/services/volume_profile_service.py#L10-L137)
- [backend/app/domain/services/market_state_classifier.py:10-97](file://backend/app/domain/services/market_state_classifier.py#L10-L97)
- [backend/app/domain/fabio_ai/services/option_scanner.py:40-512](file://backend/app/domain/fabio_ai/services/option_scanner.py#L40-L512)
- [backend/app/domain/fabio_ai/services/vp_contract_selector.py:76-641](file://backend/app/domain/fabio_ai/services/vp_contract_selector.py#L76-L641)
- [backend/app/shared/timezones.py:14-16](file://backend/app/shared/timezones.py#L14-L16)

### Service Lifecycle, Startup, and Shutdown
Lifecycle management is handled in the FastAPI lifespan:
- Startup:
  - Create service graph and load LLM model
  - Wait for model readiness and run validation
  - Start the trading engine and inject references
  - Initialize market data feed and scanners
  - **Updated** Initialize new domain services (VolumeProfileService, MarketStateClassifier)
- Running:
  - Serve API endpoints and WebSocket
- Shutdown:
  - Stop trading engine
  - Flush pending database ticks
  - Shutdown handler thread pools
  - Disconnect market data feed

```mermaid
sequenceDiagram
participant Client as "Client"
participant App as "FastAPI App"
participant Lifespan as "lifespan()"
participant Graph as "ServiceGraph"
participant Engine as "TradingEngine"
participant VPS as "VolumeProfileService"
participant MSC as "MarketStateClassifier"
participant OS as "OptionScannerService"
Client->>App : Start server
App->>Lifespan : Enter lifespan
Lifespan->>Graph : get_service_graph()
Lifespan->>Graph : llm.wait_until_ready()
Lifespan->>Graph : llm.validate()
Lifespan->>VPS : get(VolumeProfileService)
Lifespan->>MSC : get(MarketStateClassifier)
Lifespan->>OS : get(OptionScannerService)
Lifespan->>Engine : TradingEngine(graph)
Lifespan->>Engine : engine.start()
Lifespan->>MD : market_data.ensure_initialized_sync()
App-->>Client : Server ready
Client->>App : Stop server
App->>Lifespan : Exit lifespan
Lifespan->>Engine : engine.stop()
Lifespan->>MD : market_data.close_sync()
```

**Diagram sources**
- [backend/app/main.py:83-170](file://backend/app/main.py#L83-L170)
- [backend/app/api/dependencies.py:125-129](file://backend/app/api/dependencies.py#L125-L129)
- [backend/app/application/service_graph.py:347-388](file://backend/app/application/service_graph.py#L347-L388)

**Section sources**
- [backend/app/main.py:83-170](file://backend/app/main.py#L83-L170)
- [backend/app/api/dependencies.py:125-129](file://backend/app/api/dependencies.py#L125-L129)
- [backend/app/application/service_graph.py:347-388](file://backend/app/application/service_graph.py#L347-L388)

### Enhanced OptionScannerService with Parallel Processing
**Updated** The OptionScannerService has been significantly enhanced with parallel processing capabilities:

- **Parallel Execution**: Uses ThreadPoolExecutor to process multiple underlyings concurrently
- **Dynamic Worker Scaling**: Configurable via environment variables (OPTION_SCANNER_PARALLEL_UNDERLYINGS, OPTION_SCANNER_MAX_WORKERS)
- **Graceful Error Handling**: Individual underling failures don't block the entire scanning process
- **Performance Optimization**: Reduces scanning time for multi-underlying configurations

```mermaid
flowchart TD
A[scan_top_n called] --> B{Parallel Enabled?}
B --> |Yes| C[ThreadPoolExecutor with max_workers]
C --> D[Submit _scan_underlying_for_contracts for each underling]
D --> E[as_completed futures]
E --> F[Collect results]
B --> |No| G[Sequential processing]
F --> H[Merge and sort results]
G --> H
H --> I[Return top N contracts]
```

**Diagram sources**
- [backend/app/domain/fabio_ai/services/option_scanner.py:306-356](file://backend/app/domain/fabio_ai/services/option_scanner.py#L306-L356)
- [backend/app/domain/fabio_ai/services/option_scanner.py:321-341](file://backend/app/domain/fabio_ai/services/option_scanner.py#L321-L341)

**Section sources**
- [backend/app/domain/fabio_ai/services/option_scanner.py:306-356](file://backend/app/domain/fabio_ai/services/option_scanner.py#L306-L356)

## Dependency Analysis
The service graph exhibits strong cohesion within functional areas and loose coupling via ports. Key dependency relationships:
- ServiceGraph depends on configuration and adapters
- TradingSessionService depends on broker, gen ai service, storage, and probability engine
- Domain services depend on ExchangeConfig and SymbolRegistry
- **Updated** New services: VolumeProfileService and MarketStateClassifier depend on IMarketData, IStorage, and Configuration
- **Updated** OptionScannerService depends on broker and market context
- **Updated** VPContractSelector depends on broker and implements its own data fetching
- Adapters depend on external libraries via the brokers package

Potential circular dependencies are avoided by:
- One-way imports from application to domain/infrastructure
- Singleton service graph preventing multiple instantiations
- Ports decoupling domain from infrastructure

```mermaid
graph LR
CFG["Config Loader"] --> SG["ServiceGraph"]
EXCFG["ExchangeConfig"] --> SG
SYMBOLREG["SymbolRegistry"] --> SG
VPS["VolumeProfileService"] --> SG
MSC["MarketStateClassifier"] --> SG
OS["OptionScannerService"] --> SG
VPSEL["VPContractSelector"] --> SG
MD["MarketDataPort Adapter"] --> SG
BROKER["BrokerPort Adapter"] --> SG
LLM["LLMInferencePort Adapter"] --> SG
PROB["ProbabilityInferencePort Adapter"] --> SG
STORE["StoragePort Adapter"] --> SG
GENAI["GenerativeAIService"] --> SG
SESSION["TradingSessionService"] --> SG
```

**Diagram sources**
- [backend/app/config_models/loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)
- [backend/app/api/dependencies.py:63-118](file://backend/app/api/dependencies.py#L63-L118)
- [backend/app/application/service_graph.py:25-388](file://backend/app/application/service_graph.py#L25-L388)

**Section sources**
- [backend/app/config_models/loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)
- [backend/app/api/dependencies.py:63-118](file://backend/app/api/dependencies.py#L63-L118)
- [backend/app/application/service_graph.py:25-388](file://backend/app/application/service_graph.py#L25-L388)

## Performance Considerations
- Asynchronous persistence bus offloads storage writes to a background thread
- Pre-warming of market data and scanners reduces cold-start latency
- LLM model readiness and validation occur during startup to avoid runtime failures
- Rate limiting middleware protects the server from overload
- Timezone handling uses a single constant to avoid repeated timezone object construction
- **Updated** Parallel processing in OptionScannerService significantly improves multi-underlying scanning performance
- **Updated** VolumeProfileService uses efficient histogram-based computation for large datasets
- **Updated** MarketStateClassifier provides fast market state determination for real-time analysis

## Troubleshooting Guide
Common issues and diagnostics:
- LLM model readiness: If model fails to load within timeout, backend starts but LLM calls will fail; validate readiness and run validation
- Trading engine start: Failures are logged; inspect engine initialization and dependencies
- Market data feed: Initialization failures are logged; ensure credentials and network connectivity
- Configuration validation: Hard errors block boot; review validation messages and fix misconfigurations
- Shutdown: Errors during engine stop, tick flush, thread pool cleanup, or market data disconnect are logged as debug; investigate exceptions
- **Updated** Parallel processing: Check OPTION_SCANNER_PARALLEL_UNDERLYINGS and OPTION_SCANNER_MAX_WORKERS environment variables
- **Updated** Volume profile computation: Verify sufficient historical data availability for accurate profile calculation
- **Updated** Market state classification: Ensure both price and volume profile data are available for proper classification

**Section sources**
- [backend/app/main.py:83-170](file://backend/app/main.py#L83-L170)
- [backend/app/config_models/validator.py:22-176](file://backend/app/config_models/validator.py#L22-L176)
- [backend/app/domain/fabio_ai/services/option_scanner.py:306-356](file://backend/app/domain/fabio_ai/services/option_scanner.py#L306-L356)
- [backend/app/domain/services/volume_profile_service.py:23-76](file://backend/app/domain/services/volume_profile_service.py#L23-L76)
- [backend/app/domain/services/market_state_classifier.py:23-55](file://backend/app/domain/services/market_state_classifier.py#L23-L55)

## Conclusion
GlassyTrade AI employs a robust DI-driven architecture with a centralized service graph, a hierarchical configuration system, and clear separation of concerns through Ports & Adapters. The design supports environment-specific configurations, feature flags, and cross-cutting utilities like timezone handling. The lifecycle management ensures reliable startup and graceful shutdown, while the adapter layer facilitates integration with external systems.

**Updated** The architecture has been significantly enhanced with new domain services including VolumeProfileService for advanced market analysis, MarketStateClassifier for intelligent market state detection, and enhanced OptionScannerService with parallel processing capabilities. These additions provide more sophisticated trading insights and improved performance while maintaining the clean architectural boundaries established by the original design.

## Appendices

### Practical Examples: Service Wiring and Dependency Resolution
- Wiring adapters and services: Construct adapters and services in the service graph factory; wrap storage with async persistence; initialize trackers and inject into the trading session
- Resolving dependencies: Use FastAPI dependency helpers to retrieve singleton instances from the service graph
- **Updated** New service integration: VolumeProfileService and MarketStateClassifier are now available through dedicated dependency helpers
- Example paths:
  - [ServiceGraph.__init__:46-388](file://backend/app/application/service_graph.py#L46-L388)
  - [get_service_graph:125-129](file://backend/app/api/dependencies.py#L125-L129)
  - [get_* dependency helpers:63-118](file://backend/app/api/dependencies.py#L63-L118)

**Section sources**
- [backend/app/application/service_graph.py:46-388](file://backend/app/application/service_graph.py#L46-L388)
- [backend/app/api/dependencies.py:63-118](file://backend/app/api/dependencies.py#L63-L118)

### Configuration Loading and Validation Reference
- Loading order and parsing: [load_config:139-245](file://backend/app/config_models/loader.py#L139-L245)
- Validation rules: [validate_config:22-176](file://backend/app/config_models/validator.py#L22-L176)
- Base defaults: [base.yaml:1-493](file://backend/config/base.yaml#L1-L493)
- Environment overrides: [development.yaml:1-33](file://backend/config/environments/development.yaml#L1-L33)
- Feature flags: [feature_flags.yaml:1-37](file://backend/config/feature_flags.yaml#L1-L37)

**Section sources**
- [backend/app/config_models/loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)
- [backend/app/config_models/validator.py:22-176](file://backend/app/config_models/validator.py#L22-L176)
- [backend/config/base.yaml:1-493](file://backend/config/base.yaml#L1-L493)
- [backend/config/environments/development.yaml:1-33](file://backend/config/environments/development.yaml#L1-L33)
- [backend/config/feature_flags.yaml:1-37](file://backend/config/feature_flags.yaml#L1-L37)

### Adapter Contracts and Implementations
- Market data adapter: [DhanMarketDataAdapter:66-457](file://backend/app/infrastructure/adapters/dhan_adapter.py#L66-L457)
- Broker adapter: [PaperBrokerAdapter:118-199](file://backend/app/infrastructure/adapters/paper_broker.py#L118-L199)
- LLM adapter: [MLXInferenceAdapter:56-75](file://backend/app/api/dependencies.py#L56-L75)
- Storage adapter: [SQLiteStorageAdapter:369-371](file://backend/app/application/service_graph.py#L369-L371)

**Section sources**
- [backend/app/infrastructure/adapters/dhan_adapter.py:66-457](file://backend/app/infrastructure/adapters/dhan_adapter.py#L66-L457)
- [backend/app/infrastructure/adapters/paper_broker.py:118-199](file://backend/app/infrastructure/adapters/paper_broker.py#L118-L199)
- [backend/app/api/dependencies.py:56-75](file://backend/app/api/dependencies.py#L56-L75)
- [backend/app/application/service_graph.py:369-371](file://backend/app/application/service_graph.py#L369-L371)

### New Service Components and Integration
- **Updated** VolumeProfileService: [VolumeProfileService:10-137](file://backend/app/domain/services/volume_profile_service.py#L10-L137)
- **Updated** MarketStateClassifier: [MarketStateClassifier:10-97](file://backend/app/domain/services/market_state_classifier.py#L10-L97)
- **Updated** OptionScannerService: [OptionScannerService:40-512](file://backend/app/domain/fabio_ai/services/option_scanner.py#L40-L512)
- **Updated** VPContractSelector: [VPContractSelector:76-641](file://backend/app/domain/fabio_ai/services/vp_contract_selector.py#L76-L641)

**Section sources**
- [backend/app/domain/services/volume_profile_service.py:10-137](file://backend/app/domain/services/volume_profile_service.py#L10-L137)
- [backend/app/domain/services/market_state_classifier.py:10-97](file://backend/app/domain/services/market_state_classifier.py#L10-L97)
- [backend/app/domain/fabio_ai/services/option_scanner.py:40-512](file://backend/app/domain/fabio_ai/services/option_scanner.py#L40-L512)
- [backend/app/domain/fabio_ai/services/vp_contract_selector.py:76-641](file://backend/app/domain/fabio_ai/services/vp_contract_selector.py#L76-L641)