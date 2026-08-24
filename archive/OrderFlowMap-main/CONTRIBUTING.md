# Contributing to OrderFlowMap

Thank you for your interest in contributing to OrderFlowMap! This document provides guidelines and information for contributors.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Architecture Constraints](#architecture-constraints)
- [Development Workflow](#development-workflow)
- [Code Style](#code-style)
- [Submitting Changes](#submitting-changes)
- [Reporting Bugs](#reporting-bugs)
- [Feature Requests](#feature-requests)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you are expected to uphold this code. Please report unacceptable behavior by opening an issue.

---

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/OrderFlowMap.git
   cd OrderFlowMap
   ```
3. **Open** `index.html` in your browser — no build step needed
4. Make your changes and test by refreshing the browser

---

## Architecture Constraints

OrderFlowMap is intentionally designed as a **single HTML file** with zero build tooling. This is a core design principle, not a limitation.

### Rules

1. **Single file**: All HTML, CSS, and JavaScript must remain in `index.html`
2. **No build tools**: No webpack, vite, rollup, or any bundler
3. **No frameworks**: No React, Vue, Angular, etc.
4. **Minimal dependencies**: The only external dependency is Lightweight Charts (loaded via CDN). New dependencies require strong justification.
5. **No npm/node**: The project should work by simply opening the HTML file

### Why?

- **Zero friction**: Anyone can use it by opening a file
- **Portable**: Works offline, on any OS, no installation
- **Auditable**: The entire application is readable in a single file
- **No supply chain risk**: No `node_modules`, no build artifacts

---

## Development Workflow

### Testing

Since there is no test framework, testing is manual:

1. **Simulation mode**: Verify the simulator generates realistic data and all overlays render correctly
2. **UI controls**: Test every slider, checkbox, and preset
3. **Keyboard shortcuts**: Verify all hotkeys work
4. **Browser compatibility**: Test in Chrome, Firefox, and Safari
5. **Live mode** (if applicable): Test WebSocket connection flow

### Debugging

- Open browser DevTools (F12)
- Watch the console for errors
- Use the footer stats (Bars, Trades, Snapshots, FPS) to monitor performance
- The `bars`, `depth`, `trades`, and `cvdBars` arrays are global and inspectable in the console

---

## Code Style

### General

- **Semicolons**: Always use semicolons
- **Quotes**: Single quotes for strings
- **Indentation**: 2 spaces
- **Line length**: Keep lines reasonable (~120 chars max)
- **Comments**: Use `/* Section Header */` for major sections, `//` for inline

### Naming

- **Variables**: `camelCase` (e.g., `tradeVolByPrice`, `liveMsgCount`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `TICK`, `SPREAD_PT`, `DEPTH_LEVELS`)
- **Classes**: `PascalCase` (e.g., `HeatmapPrimitive`, `BubblesRenderer`)
- **CSS classes**: `kebab-case` (e.g., `stat-card`, `mode-badge`)
- **DOM IDs**: `camelCase` (e.g., `lastPrice`, `hmIntensity`)

### CSS

- Use CSS custom properties (variables) defined in `:root`
- Keep selectors shallow (max 2 levels)
- Group related styles with section comment headers

### JavaScript

- Use `const` by default, `let` when reassignment is needed, never `var`
- Arrow functions for callbacks and short expressions
- Use template literals for string interpolation
- Prefer `for` loops over `.forEach()` in hot paths (rendering)

---

## Submitting Changes

### Pull Request Process

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes in `index.html`

3. Test thoroughly in at least Chrome and Firefox

4. Commit with a clear, descriptive message:
   ```bash
   git commit -m "Add: configurable depth levels (3/5/10)"
   ```

5. Push to your fork and open a Pull Request

### Commit Message Format

```
<type>: <short description>

<optional body with more detail>
```

Types:
- `Add` — New feature
- `Fix` — Bug fix
- `Refactor` — Code restructuring without behavior change
- `Style` — CSS/visual changes
- `Docs` — Documentation only
- `Perf` — Performance improvement

### PR Requirements

- [ ] Works in simulation mode
- [ ] Works in live mode (if touching data flow)
- [ ] No console errors or warnings
- [ ] All existing keyboard shortcuts still work
- [ ] FPS remains stable (>30 FPS at 4× speed with 600s history)
- [ ] Description explains **what** and **why**

---

## Reporting Bugs

Open an issue with:

1. **Browser and version** (e.g., Chrome 120, Firefox 115)
2. **Mode** (Simulate or Live)
3. **Steps to reproduce**
4. **Expected behavior**
5. **Actual behavior**
6. **Screenshot or screen recording** (if visual)
7. **Console errors** (if any)

---

## Feature Requests

Open an issue with the `enhancement` label. Include:

1. **Use case**: Why is this feature needed?
2. **Proposed behavior**: What should it do?
3. **Alternatives considered**: Are there existing workarounds?
4. **Mockup** (optional): A sketch or description of the UI

---

## Areas for Contribution

Here are some areas where contributions would be especially welcome:

### Good First Issues
- Add tooltip descriptions to UI controls
- Improve mobile/responsive layout
- Add a "copy to clipboard" button for connection settings

### Medium Complexity
- WebSocket reconnection with exponential backoff
- Session export/import (JSON format)
- Additional colormap options
- Configurable depth levels (currently fixed at 5)

### Advanced
- Multi-symbol tabbed interface
- Additional exchange adapters (Binance, Zerodha Kite)
- WebGL-accelerated heatmap rendering
- Order flow imbalance stacking visualization

---

## Questions?

If you have questions about contributing, feel free to open a Discussion on GitHub. We're happy to help!
