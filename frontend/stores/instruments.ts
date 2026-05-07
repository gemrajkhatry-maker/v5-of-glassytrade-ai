import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import { InstrumentState, OHLCData } from '../types';

/**
 * Normalized instrument state store.
 * Uses byId + allIds pattern for efficient updates and selections.
 */
interface InstrumentsState {
    byId: Record<string, InstrumentState>;
    allIds: string[];
    activeId: string;
}

interface InstrumentsActions {
    /** Set the active instrument */
    setActive: (symbol: string) => void;
    
    /** Add a new instrument to the store */
    addInstrument: (symbol: string, state: InstrumentState) => void;
    
    /** Update an instrument with partial data */
    updateInstrument: (symbol: string, updates: Partial<InstrumentState>) => void;
    
    /** Merge candle data into existing instrument */
    mergeCandleData: (symbol: string, candles: OHLCData[]) => void;
    
    /** Update a single field deeply nested in instrument */
    updateInstrumentField: <T extends keyof InstrumentState>(
        symbol: string,
        field: T,
        value: InstrumentState[T]
    ) => void;
    
    /** Remove an instrument from the store */
    removeInstrument: (symbol: string) => void;
    
    /** Clear all instruments */
    clearAll: () => void;
}

export type InstrumentsStore = InstrumentsState & InstrumentsActions;

export const useInstrumentsStore = create<InstrumentsStore>()(
    immer((set) => ({
        // Initial state
        byId: {},
        allIds: [],
        activeId: '',
        
        // Actions
        setActive: (symbol) => set((state) => {
            if (state.byId[symbol]) {
                state.activeId = symbol;
            }
        }),
        
        addInstrument: (symbol, state) => set((draft) => {
            if (!draft.byId[symbol]) {
                draft.byId[symbol] = state;
                draft.allIds.push(symbol);
            }
        }),
        
        updateInstrument: (symbol, updates) => set((draft) => {
            if (draft.byId[symbol]) {
                Object.assign(draft.byId[symbol], updates);
            }
        }),
        
        mergeCandleData: (symbol, candles) => set((draft) => {
            const instrument = draft.byId[symbol];
            if (!instrument || candles.length === 0) return;
            
            // Create map of existing candles by time
            const existingMap = new Map<string, OHLCData>();
            instrument.data.forEach(candle => {
                existingMap.set(candle.time, candle);
            });
            
            // Add new candles that don't exist
            let added = 0;
            candles.forEach(candle => {
                if (!existingMap.has(candle.time)) {
                    instrument.data.push(candle);
                    existingMap.set(candle.time, candle);
                    added++;
                }
            });
            
            // Sort by timestamp if we added any
            if (added > 0) {
                instrument.data.sort((a, b) => 
                    new Date(a.time).getTime() - new Date(b.time).getTime()
                );
            }
        }),
        
        updateInstrumentField: (symbol, field, value) => set((draft) => {
            if (draft.byId[symbol]) {
                (draft.byId[symbol] as any)[field] = value;
            }
        }),
        
        removeInstrument: (symbol) => set((draft) => {
            delete draft.byId[symbol];
            draft.allIds = draft.allIds.filter(id => id !== symbol);
            
            // If active instrument was removed, select first available
            if (draft.activeId === symbol && draft.allIds.length > 0) {
                draft.activeId = draft.allIds[0];
            } else if (draft.allIds.length === 0) {
                draft.activeId = '';
            }
        }),
        
        clearAll: () => set((draft) => {
            draft.byId = {};
            draft.allIds = [];
            draft.activeId = '';
        }),
    }))
);

// ============================================================================
// Selectors - Use these in components to subscribe to specific state slices
// ============================================================================

/** Select the active instrument */
export const selectActiveInstrument = (state: InstrumentsStore): InstrumentState | null => {
    if (!state.activeId || !state.byId[state.activeId]) return null;
    return state.byId[state.activeId];
};

/** Select a specific instrument by symbol */
export const selectInstrument = (state: InstrumentsStore, symbol: string): InstrumentState | null => {
    return state.byId[symbol] || null;
};

/** Select all instrument symbols */
export const selectAllSymbols = (state: InstrumentsStore): string[] => {
    return state.allIds;
};

/** Select active instrument's LTP (last traded price) */
export const selectActiveLTP = (state: InstrumentsStore): number => {
    const instrument = state.byId[state.activeId];
    if (!instrument || instrument.data.length === 0) return 0;
    return instrument.data[instrument.data.length - 1].close;
};

/** Select active instrument's portfolio */
export const selectActivePortfolio = (state: InstrumentsStore) => {
    const instrument = state.byId[state.activeId];
    return instrument?.portfolio || null;
};

/** Select active instrument's AMT analysis */
export const selectActiveAMTAnalysis = (state: InstrumentsStore) => {
    const instrument = state.byId[state.activeId];
    return instrument?.amtAnalysis || null;
};

/** Select active instrument's agent decision */
export const selectActiveAgentDecision = (state: InstrumentsStore) => {
    const instrument = state.byId[state.activeId];
    return instrument?.agentDecision || null;
};

/** Check if a specific instrument exists */
export const selectHasInstrument = (state: InstrumentsStore, symbol: string): boolean => {
    return symbol in state.byId;
};

/** Count of instruments in store */
export const selectInstrumentCount = (state: InstrumentsStore): number => {
    return state.allIds.length;
};
