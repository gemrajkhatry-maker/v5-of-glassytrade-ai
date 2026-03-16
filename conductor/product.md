# Initial Concept
GlassyTrade AI (v5) - Trading simulation and visualization using AMT and AI.

# GlassyTrade AI (v5) - Product Definition

## Vision
To provide a high-performance, visually immersive, and AI-driven trading simulation platform that empowers traders to master Auction Market Theory (AMT) and quantitative analysis through real-time data visualization and reinforcement learning.

## Target Audience
- Advanced retail traders specializing in Auction Market Theory (AMT).
- Algorithmic trading developers testing AI/ML-based strategies.
- Financial analysts seeking sophisticated market structure visualization.

## Core Features
- **Dual-Engine Strategy Execution:**
  - **Theorist Engine (AMT):** Real-time market structure analysis using Volume Profile, POC, VWAP, and Order Flow.
  - **Quant Engine (AI):** Self-learning prediction model using reinforcement learning (PPO) and LLM-driven entry/overseer decisions.
- **High-Performance Visualization:** 2D canvas-based charting with Lightweight Charts, maintaining a "Glassmorphism" UI aesthetic.
- **Intraday Compounding & Risk Management:** Dynamic position sizing based on session P&L and conservative/momentum risk modes.
- **LLM Overseer:** Natural language interaction and structured trade rationales from fine-tuned LLMs (Nanbeige 3B, Qwen).
- **Multi-Source Data Integration:** Real-time and historical data from Binance (crypto) and potentially others (MCX/NSE options via brokers).

## Design Philosophy
- **Glassmorphism Aesthetic:** Modern, sleek, dark-mode-first interface using translucency and vibrant accents.
- **Performance First:** Decoupled architecture between React view and core trading/learning engines.
- **Methodology-Centric:** Built specifically around Fabio Valentini's AMT principles.
