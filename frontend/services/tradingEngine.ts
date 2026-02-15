
import { Portfolio, TradePosition, TradeSignal, AIAnalysis, StrategyStats, OHLCData } from '../types';
import { v4 as uuidv4 } from 'uuid';

export class TradingEngine {
  public static INITIAL_CAPITAL = 10000000;
  public static LEVERAGE = 10;
  public static RISK_PER_TRADE = 0.01;

  public static createInitialPortfolio(): Portfolio {
    return {
      balance: this.INITIAL_CAPITAL,
      equity: this.INITIAL_CAPITAL,
      leverage: this.LEVERAGE,
      positions: [],
      closedTrades: [],
      history: []
    };
  }

  public static updatePortfolio(
    portfolio: Portfolio,
    tick: OHLCData
  ): Portfolio {
    const nextPortfolio = { ...portfolio, positions: [...portfolio.positions] };
    const currentPrice = tick.close;
    const currentTime = tick.time;
    let unrealizedPnL = 0;

    // 1. Update PnL and check Exits
    const activePositions: TradePosition[] = [];
    const newlyClosed: TradePosition[] = [];

    nextPortfolio.positions.forEach(pos => {
      // Phase 6.3: Break-Even on Strong CVD Pressure
      // Rule: If CVD in direction > threshold, move stop to entry.
      // Using normalized delta (Delta / Volume) > 0.5 as "Strong Pressure"
      const normalizedDelta = tick.volume > 0 ? tick.delta / tick.volume : 0;
      
      if (pos.side === 'LONG' && normalizedDelta > 0.5 && pos.stopLoss < pos.entryPrice) {
          // Move SL to Entry (Break Even)
          pos.stopLoss = pos.entryPrice;
      } else if (pos.side === 'SHORT' && normalizedDelta < -0.5 && pos.stopLoss > pos.entryPrice) {
          pos.stopLoss = pos.entryPrice;
      }

      const priceDiff = pos.side === 'LONG' 
        ? currentPrice - pos.entryPrice 
        : pos.entryPrice - currentPrice;
      
      const currentPnL = priceDiff * pos.size;
      
      let shouldClose = false;
      let closeReason = '';

      // Phase 6: Full Exit Logic (No partials)
      if (pos.side === 'LONG') {
        if (currentPrice <= pos.stopLoss) { shouldClose = true; closeReason = 'Stop Loss'; }
        else if (currentPrice >= pos.takeProfit) { shouldClose = true; closeReason = 'Take Profit (Full)'; }
      } else {
        if (currentPrice >= pos.stopLoss) { shouldClose = true; closeReason = 'Stop Loss'; }
        else if (currentPrice <= pos.takeProfit) { shouldClose = true; closeReason = 'Take Profit (Full)'; }
      }

      if (shouldClose) {
        newlyClosed.push({
          ...pos,
          pnl: currentPnL,
          status: 'CLOSED',
          exitPrice: currentPrice,
          exitTime: currentTime,
          closeReason
        });
        nextPortfolio.balance += currentPnL;
      } else {
        pos.pnl = currentPnL;
        activePositions.push(pos);
        unrealizedPnL += currentPnL;
      }
    });

    nextPortfolio.positions = activePositions;
    nextPortfolio.closedTrades = [...nextPortfolio.closedTrades, ...newlyClosed];
    nextPortfolio.equity = nextPortfolio.balance + unrealizedPnL;

    // 2. History Windowing (Keep last 1000 points)
    if (nextPortfolio.history.length === 0 || 
        new Date(currentTime).getTime() - new Date(nextPortfolio.history[nextPortfolio.history.length-1].time).getTime() > 60000) {
      nextPortfolio.history.push({ time: currentTime, pnl: unrealizedPnL });
      if (nextPortfolio.history.length > 1000) nextPortfolio.history.shift();
    }

    return nextPortfolio;
  }

  public static executeSignal(portfolio: Portfolio, signal: TradeSignal): Portfolio {
    // Prevent duplicate source positions
    if (portfolio.positions.some(p => p.source === signal.source)) return portfolio;

    const riskAmount = portfolio.equity * this.RISK_PER_TRADE;
    const riskPerUnit = Math.abs(signal.price - signal.stopLoss);
    if (riskPerUnit === 0) return portfolio;

    let size = riskAmount / riskPerUnit;
    const maxNotional = portfolio.equity * portfolio.leverage;
    if (size * signal.price > maxNotional) size = maxNotional / signal.price;

    const nextPortfolio = { ...portfolio, positions: [...portfolio.positions] };
    nextPortfolio.positions.push({
      id: uuidv4(),
      symbol: 'BTCUSDT',
      side: signal.type === 'BUY' ? 'LONG' : 'SHORT',
      source: signal.source,
      entryPrice: signal.price,
      size,
      stopLoss: signal.stopLoss,
      takeProfit: signal.takeProfit,
      pnl: 0,
      entryTime: signal.timestamp,
      status: 'OPEN',
      metadata: signal.metadata
    });

    return nextPortfolio;
  }

  public static getStats(closedTrades: TradePosition[], source: 'AMT' | 'PREDICTION'): StrategyStats {
    const trades = closedTrades.filter(t => t.source === source);
    const wins = trades.filter(t => t.pnl > 0);
    const losses = trades.filter(t => t.pnl <= 0);
    const netProfit = trades.reduce((sum, t) => sum + t.pnl, 0);
    
    return {
      totalTrades: trades.length,
      wins: wins.length,
      losses: losses.length,
      winRate: trades.length > 0 ? (wins.length / trades.length) * 100 : 0,
      netProfit,
      avgProfit: trades.length > 0 ? netProfit / trades.length : 0,
      largestWin: wins.reduce((max, t) => Math.max(max, t.pnl), 0),
      largestLoss: losses.reduce((min, t) => Math.min(min, t.pnl), 0)
    };
  }
}
