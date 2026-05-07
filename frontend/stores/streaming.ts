import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

export type ConnectionStatus = 
    | 'disconnected'
    | 'connecting'
    | 'connected'
    | 'reconnecting'
    | 'error';

interface StreamingState {
    /** WebSocket connection status */
    status: ConnectionStatus;
    
    /** WebSocket URL */
    url: string | null;
    
    /** Last connection error message */
    error: string | null;
    
    /** Connection attempts count */
    reconnectAttempts: number;
    
    /** Max reconnection attempts */
    maxReconnectAttempts: number;
    
    /** Last successful connection timestamp */
    lastConnectedAt: number | null;
    
    /** Last message received timestamp */
    lastMessageAt: number | null;
    
    /** Total messages received */
    messageCount: number;
}

interface StreamingActions {
    /** Set connection status */
    setStatus: (status: ConnectionStatus) => void;
    
    /** Set WebSocket URL */
    setUrl: (url: string) => void;
    
    /** Set connection error */
    setError: (error: string | null) => void;
    
    /** Increment reconnect attempts */
    incrementReconnectAttempts: () => void;
    
    /** Reset reconnect attempts */
    resetReconnectAttempts: () => void;
    
    /** Record successful connection */
    recordConnection: () => void;
    
    /** Record received message */
    recordMessage: () => void;
    
    /** Reset streaming state */
    reset: () => void;
}

export type StreamingStore = StreamingState & StreamingActions;

export const useStreamingStore = create<StreamingStore>()(
    immer((set) => ({
        // Initial state
        status: 'disconnected',
        url: null,
        error: null,
        reconnectAttempts: 0,
        maxReconnectAttempts: 10,
        lastConnectedAt: null,
        lastMessageAt: null,
        messageCount: 0,
        
        // Actions
        setStatus: (status) => set((state) => {
            state.status = status;
        }),
        
        setUrl: (url) => set((state) => {
            state.url = url;
        }),
        
        setError: (error) => set((state) => {
            state.error = error;
        }),
        
        incrementReconnectAttempts: () => set((state) => {
            state.reconnectAttempts += 1;
        }),
        
        resetReconnectAttempts: () => set((state) => {
            state.reconnectAttempts = 0;
        }),
        
        recordConnection: () => set((state) => {
            state.lastConnectedAt = Date.now();
            state.reconnectAttempts = 0;
            state.status = 'connected';
            state.error = null;
        }),
        
        recordMessage: () => set((state) => {
            state.lastMessageAt = Date.now();
            state.messageCount += 1;
        }),
        
        reset: () => set((state) => {
            state.status = 'disconnected';
            state.url = null;
            state.error = null;
            state.reconnectAttempts = 0;
            state.lastConnectedAt = null;
            state.lastMessageAt = null;
            state.messageCount = 0;
        }),
    }))
);

// ============================================================================
// Selectors
// ============================================================================

/** Check if currently connected */
export const selectIsConnected = (state: StreamingStore): boolean => {
    return state.status === 'connected';
};

/** Check if currently reconnecting */
export const selectIsReconnecting = (state: StreamingStore): boolean => {
    return state.status === 'reconnecting';
};

/** Get connection status display text */
export const selectStatusText = (state: StreamingStore): string => {
    const statusMap: Record<ConnectionStatus, string> = {
        disconnected: 'Disconnected',
        connecting: 'Connecting...',
        connected: 'Connected',
        reconnecting: `Reconnecting (${state.reconnectAttempts}/${state.maxReconnectAttempts})`,
        error: state.error || 'Error',
    };
    return statusMap[state.status];
};

/** Get time since last message (in seconds) */
export const selectSecondsSinceLastMessage = (state: StreamingStore): number | null => {
    if (!state.lastMessageAt) return null;
    return (Date.now() - state.lastMessageAt) / 1000;
};

/** Check if connection is stale (no messages for 30+ seconds) */
export const selectIsConnectionStale = (state: StreamingStore): boolean => {
    if (!state.lastMessageAt) return false;
    return (Date.now() - state.lastMessageAt) > 30000;
};
