import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import { Portfolio, TradePosition } from '../types';

interface PortfolioState {
    /** Current portfolio state */
    portfolio: Portfolio;
    
    /** Symbol of the active portfolio */
    symbol: string;
}

interface PortfolioActions {
    /** Set entire portfolio */
    setPortfolio: (symbol: string, portfolio: Portfolio) => void;
    
    /** Update a single position */
    updatePosition: (symbol: string, positionId: string, updates: Partial<TradePosition>) => void;
    
    /** Add a new position */
    addPosition: (symbol: string, position: TradePosition) => void;
    
    /** Remove a position */
    removePosition: (symbol: string, positionId: string) => void;
    
    /** Update portfolio balance */
    updateBalance: (symbol: string, balance: number) => void;
    
    /** Update portfolio equity */
    updateEquity: (symbol: string, equity: number) => void;
    
    /** Add closed trade */
    addClosedTrade: (symbol: string, trade: TradePosition) => void;
    
    /** Clear portfolio */
    clearPortfolio: () => void;
}

export type PortfolioStore = PortfolioState & PortfolioActions;

export const usePortfolioStore = create<PortfolioStore>()(
    immer((set) => ({
        // Initial state
        portfolio: {
            balance: 10_000_000,
            equity: 10_000_000,
            leverage: 10,
            positions: [],
            closedTrades: [],
            history: [],
        },
        symbol: '',
        
        // Actions
        setPortfolio: (symbol, portfolio) => set((state) => {
            state.portfolio = portfolio;
            state.symbol = symbol;
        }),
        
        updatePosition: (symbol, positionId, updates) => set((draft) => {
            if (draft.symbol !== symbol) return;
            
            const position = draft.portfolio.positions.find(p => p.id === positionId);
            if (position) {
                Object.assign(position, updates);
            }
        }),
        
        addPosition: (symbol, position) => set((draft) => {
            if (draft.symbol !== symbol) return;
            draft.portfolio.positions.push(position);
        }),
        
        removePosition: (symbol, positionId) => set((draft) => {
            if (draft.symbol !== symbol) return;
            draft.portfolio.positions = draft.portfolio.positions.filter(p => p.id !== positionId);
        }),
        
        updateBalance: (symbol, balance) => set((draft) => {
            if (draft.symbol !== symbol) return;
            draft.portfolio.balance = balance;
        }),
        
        updateEquity: (symbol, equity) => set((draft) => {
            if (draft.symbol !== symbol) return;
            draft.portfolio.equity = equity;
        }),
        
        addClosedTrade: (symbol, trade) => set((draft) => {
            if (draft.symbol !== symbol) return;
            draft.portfolio.closedTrades.push(trade);
        }),
        
        clearPortfolio: () => set((state) => {
            state.portfolio = {
                balance: 10_000_000,
                equity: 10_000_000,
                leverage: 10,
                positions: [],
                closedTrades: [],
                history: [],
            };
            state.symbol = '';
        }),
    }))
);

// ============================================================================
// Selectors
// ============================================================================

/** Select all open positions */
export const selectOpenPositions = (state: PortfolioStore): TradePosition[] => {
    return state.portfolio.positions.filter(p => p.status === 'OPEN');
};

/** Select all closed trades */
export const selectClosedTrades = (state: PortfolioStore): TradePosition[] => {
    return state.portfolio.closedTrades;
};

/** Select total open PnL */
export const selectOpenPnL = (state: PortfolioStore): number => {
    return state.portfolio.positions.reduce((acc, p) => acc + p.pnl, 0);
};

/** Select portfolio equity */
export const selectEquity = (state: PortfolioStore): number => {
    return state.portfolio.equity;
};

/** Select portfolio balance */
export const selectBalance = (state: PortfolioStore): number => {
    return state.portfolio.balance;
};

/** Check if any positions are open */
export const selectHasOpenPositions = (state: PortfolioStore): boolean => {
    return state.portfolio.positions.some(p => p.status === 'OPEN');
};

/** Select win rate from closed trades */
export const selectWinRate = (state: PortfolioStore): number => {
    const closed = state.portfolio.closedTrades;
    if (closed.length === 0) return 0;
    
    const winningTrades = closed.filter(t => t.pnl > 0);
    return (winningTrades.length / closed.length) * 100;
};

/** Select total PnL from closed trades */
export const selectTotalPnL = (state: PortfolioStore): number => {
    return state.portfolio.closedTrades.reduce((acc, t) => acc + t.pnl, 0);
};
