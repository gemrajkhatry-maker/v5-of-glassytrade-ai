# AI Rules & Architecture Guidelines

This document defines the technology stack and architectural rules for the **AMT Options Scalper System**. All contributions must adhere to these standards to maintain performance, consistency, and live-trading reliability.

## 🛠 Technology Stack

- **Core Backend**: Python 3.x with **FastAPI** for high-performance, asynchronous REST and WebSocket communication.
- **Frontend Architecture**: **React 19** powered by **Vite** and **TypeScript** for a modern, type-safe, and responsive user interface.
- **Financial Visualization**: **lightweight-charts** for 2D price/volume analysis and **Three.js** (@react-three/fiber) for advanced 3D market depth rendering.
- **Local AI Inference**: **MLX** (Apple Silicon native) for low-latency, local-first LLM execution on macOS hardware.
- **Probability Engine**: **LightGBM** for efficient, real-time first-passage and success probability modeling.
- **Validation Layer**: **Pydantic v2** for robust data modeling, API schema enforcement, and centralized configuration.
- **Styling System**: **Tailwind CSS (v4)** for a performance-oriented, utility-first design system.
- **Persistence Layer**: **SQLite** for crash-resilient storage of trade history, positions, and risk management state.

## 📏 Library Usage Rules

To maintain the system's integrity, use the following libraries for their designated purposes:

### 🐍 Backend Rules
- **Pydantic**: **MANDATORY** for all data-carrying objects. Every class that represents a domain entity, value object, or API schema must inherit from `pydantic.BaseModel`.
- **FastAPI**: Use for all external-facing endpoints. Prefer `async def` for any handler involving network I/O or database access to prevent blocking the event loop.
- **MLX / mlx-lm**: The primary choice for local LLM inference. Standard `transformers` or `torch` should only be used in training scripts, not for live execution paths.
- **LightGBM**: Use for all "Probability Guard" and ML-based logic gates. Avoid deep learning models for these tasks to ensure fast execution during high-volatility events.
- **SharedSettings**: All configuration must be defined in `app.config` (inheriting from `SharedSettings`) and loaded via environment variables or `.env` files.

### ⚛️ Frontend Rules
- **TypeScript**: No `any` types allowed. Use strict typing for all props, states, and API responses.
- **Lightweight Charts**: The exclusive library for 2D financial data (OHLC, Volume, Indicators). Do not introduce generic charting libraries (D3, Chart.js) for market data.
- **Lucide React**: The standard icon library. Do not import individual SVG files or other icon sets.
- **Tailwind CSS**: Use utility classes exclusively for styling. Custom CSS files should only be used for complex Three.js shaders or global resets.
- **React 19 Hooks**: Prefer functional components and hooks (`useMemo`, `useCallback`) to optimize rendering performance for high-frequency updates.

## 🏗 Architectural Principles
1. **DIP (Dependency Inversion)**: Always depend on abstractions (Ports) rather than concretions (Adapters). For example, code should depend on `MarketDataPort`, not `DhanMarketDataAdapter`.
2. **Event-Driven**: Use the internal `InMemoryEventBus` to decouple domain logic from infrastructure (e.g., notifying the UI of a trade without hard-coding a WebSocket push).
3. **Immutability**: Prefer frozen dataclasses and Pydantic models for domain value objects (like `OHLC`, `Signal`, `AMTResult`) to prevent accidental side effects.
