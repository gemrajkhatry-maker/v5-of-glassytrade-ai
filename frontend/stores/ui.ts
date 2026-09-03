import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { immer } from 'zustand/middleware/immer';
import { ChartMode } from '../types';

interface UIState {
    /** Chart display mode */
    chartMode: ChartMode;
    
    /** Left sidebar (market scanner) visibility */
    sidebarOpen: boolean;
    
    /** Right sidebar (intelligence panel) visibility */
    rightSidebarOpen: boolean;
    
    /** Volume profile display mode */
    vpMode: 'session' | 'leg' | 'combined' | 'off';
    
    /** Show volume profile overlay */
    showVolumeProfile: boolean;
    
    /** Show HalfTrend overlay (trend line, ATR channels, Buy/Sell labels) */
    showHalfTrend: boolean;
    
    /** Current page */
    currentPage: 'trading' | 'journal';
    
    /** Workspace name */
    workspaceName: string;
}

interface UIActions {
    /** Set chart mode */
    setChartMode: (mode: ChartMode) => void;
    
    /** Toggle left sidebar */
    toggleSidebar: () => void;
    
    /** Set left sidebar visibility */
    setSidebarOpen: (open: boolean) => void;
    
    /** Toggle right sidebar */
    toggleRightSidebar: () => void;
    
    /** Set right sidebar visibility */
    setRightSidebarOpen: (open: boolean) => void;
    
    /** Set volume profile mode */
    setVpMode: (mode: 'session' | 'leg' | 'combined' | 'off') => void;
    
    /** Toggle volume profile */
    toggleVolumeProfile: () => void;
    
    /** Toggle HalfTrend overlay */
    toggleHalfTrend: () => void;
    
    /** Set HalfTrend overlay visibility */
    setHalfTrendVisible: (visible: boolean) => void;
    
    /** Set current page */
    setCurrentPage: (page: 'trading' | 'journal') => void;
    
    /** Set workspace name */
    setWorkspaceName: (name: string) => void;
    
    /** Reset UI to defaults */
    resetUI: () => void;
}

export type UIStore = UIState & UIActions;

export const useUIStore = create<UIStore>()(
    persist(
        immer((set) => ({
            // Initial state
            chartMode: 'STANDARD',
            sidebarOpen: true,
            rightSidebarOpen: true,
            vpMode: 'session',
            showVolumeProfile: true,
            showHalfTrend: true,
            currentPage: 'trading',
            workspaceName: 'Default',
            
            // Actions
            setChartMode: (mode) => set((state) => {
                state.chartMode = mode;
            }),
            
            toggleSidebar: () => set((state) => {
                state.sidebarOpen = !state.sidebarOpen;
            }),
            
            setSidebarOpen: (open) => set((state) => {
                state.sidebarOpen = open;
            }),
            
            toggleRightSidebar: () => set((state) => {
                state.rightSidebarOpen = !state.rightSidebarOpen;
            }),
            
            setRightSidebarOpen: (open) => set((state) => {
                state.rightSidebarOpen = open;
            }),
            
            setVpMode: (mode) => set((state) => {
                state.vpMode = mode;
                state.showVolumeProfile = mode !== 'off';
            }),
            
            toggleVolumeProfile: () => set((state) => {
                state.showVolumeProfile = !state.showVolumeProfile;
                if (!state.showVolumeProfile) {
                    state.vpMode = 'off';
                }
            }),
            
            toggleHalfTrend: () => set((state) => {
                state.showHalfTrend = !state.showHalfTrend;
            }),
            
            setHalfTrendVisible: (visible) => set((state) => {
                state.showHalfTrend = visible;
            }),
            
            setCurrentPage: (page) => set((state) => {
                state.currentPage = page;
            }),
            
            setWorkspaceName: (name) => set((state) => {
                state.workspaceName = name;
            }),
            
            resetUI: () => set((state) => {
                state.chartMode = 'STANDARD';
                state.sidebarOpen = true;
                state.rightSidebarOpen = true;
                state.vpMode = 'session';
                state.showVolumeProfile = true;
                state.showHalfTrend = true;
                state.currentPage = 'trading';
            }),
        })),
        {
            name: 'glassytrade-ui-state', // localStorage key
            partialize: (state) => ({
                // Only persist these fields
                chartMode: state.chartMode,
                sidebarOpen: state.sidebarOpen,
                rightSidebarOpen: state.rightSidebarOpen,
                vpMode: state.vpMode,
                showVolumeProfile: state.showVolumeProfile,
                showHalfTrend: state.showHalfTrend,
                workspaceName: state.workspaceName,
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

/** Select volume profile mode */
export const selectVpMode = (state: UIStore): string => {
    return state.vpMode;
};

/** Select HalfTrend overlay visibility */
export const selectShowHalfTrend = (state: UIStore): boolean => {
    return state.showHalfTrend;
};

/** Select current page */
export const selectCurrentPage = (state: UIStore): 'trading' | 'journal' => {
    return state.currentPage;
};
