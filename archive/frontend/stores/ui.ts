import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { ChartMode } from '../types';

interface UIState {
    /** Chart display mode */
    chartMode: ChartMode;
    
    /** Left sidebar (market scanner) visibility */
    sidebarOpen: boolean;
    
    /** Right sidebar (intelligence panel) visibility */
    rightSidebarOpen: boolean;
    
    /** Live opportunity card visibility */
    showControls: boolean;
    
    /** Current page */
    currentPage: 'trading' | 'journal';
}

interface UIActions {
    /** Set chart mode */
    setChartMode: (mode: ChartMode) => void;
    
    /** Set left sidebar visibility */
    setSidebarOpen: (open: boolean) => void;
    
    /** Set right sidebar visibility */
    setRightSidebarOpen: (open: boolean) => void;
    
    /** Set controls visibility */
    setShowControls: (show: boolean) => void;
    
    /** Set current page */
    setCurrentPage: (page: 'trading' | 'journal') => void;
}

export type UIStore = UIState & UIActions;

export const useUIStore = create<UIStore>()(
    persist(
        (set) => ({
            // Initial state
            chartMode: 'STANDARD',
            sidebarOpen: true,
            rightSidebarOpen: true,
            showControls: false,
            currentPage: 'trading',
            
            // Actions
            setChartMode: (mode) => set({ chartMode: mode }),
            
            setSidebarOpen: (open) => set({ sidebarOpen: open }),
            
            setRightSidebarOpen: (open) => set({ rightSidebarOpen: open }),
            
            setShowControls: (show) => set({ showControls: show }),
            
            setCurrentPage: (page) => set({ currentPage: page }),
        }),
        {
            name: 'glassytrade-ui-state', // localStorage key
            partialize: (state) => ({
                // Only persist these fields
                chartMode: state.chartMode,
                sidebarOpen: state.sidebarOpen,
                rightSidebarOpen: state.rightSidebarOpen,
            }),
        }
    )
);

// ============================================================================
// Selectors
// ============================================================================

/** Select chart mode */
export const selectChartMode = (state: UIStore): ChartMode => {
    return state.chartMode;
};

/** Select sidebar visibility */
export const selectSidebarOpen = (state: UIStore): boolean => {
    return state.sidebarOpen;
};

/** Select right sidebar visibility */
export const selectRightSidebarOpen = (state: UIStore): boolean => {
    return state.rightSidebarOpen;
};
