import { useStreamingStore, ConnectionStatus } from '../../stores/streaming';

/**
 * WebSocket Manager with auto-reconnection and resilience
 * 
 * Features:
 * - Exponential backoff reconnection
 * - Maximum reconnection attempts
 * - Connection state tracking
 * - Automatic ping/pong heartbeat
 * - Graceful degradation
 */
export class WebSocketManager {
    private ws: WebSocket | null = null;
    private url: string | null = null;
    private reconnectAttempts = 0;
    private maxReconnectAttempts = 10;
    private baseDelay = 1000; // 1 second
    private maxDelay = 30000; // 30 seconds
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    private lastPongTime = Date.now();
    private heartbeatInterval = 30000; // 30 seconds
    private messageHandlers: Map<string, Set<(data: any) => void>> = new Map();
    private isConnecting = false;

    /**
     * Connect to WebSocket server
     */
    connect(url: string): void {
        this.url = url;
        this.reconnectAttempts = 0;
        this.attemptConnection();
    }

    /**
     * Attempt WebSocket connection
     */
    private attemptConnection(): void {
        if (this.isConnecting || !this.url) return;
        
        this.isConnecting = true;
        useStreamingStore.getState().setStatus('connecting');

        try {
            this.ws = new WebSocket(this.url);

            this.ws.onopen = () => {
                this.isConnecting = false;
                this.reconnectAttempts = 0;
                useStreamingStore.getState().recordConnection();
                console.log('[WebSocket] Connected');
                
                // Start heartbeat
                this.startHeartbeat();
                
                // Re-subscribe to channels
                this.resubscribeAll();
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.lastPongTime = Date.now();
                    useStreamingStore.getState().recordMessage();
                    
                    // Route to handlers
                    const type = data.type || 'message';
                    const handlers = this.messageHandlers.get(type);
                    if (handlers) {
                        handlers.forEach(handler => {
                            try {
                                handler(data.payload || data);
                            } catch (error) {
                                console.error(`[WebSocket] Handler error for ${type}:`, error);
                            }
                        });
                    }
                } catch (error) {
                    console.error('[WebSocket] Message parse error:', error);
                }
            };

            this.ws.onclose = (event) => {
                this.isConnecting = false;
                this.stopHeartbeat();
                useStreamingStore.getState().setStatus('disconnected');
                console.log(`[WebSocket] Closed: ${event.code} ${event.reason}`);
                
                // Attempt reconnection
                this.scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                this.isConnecting = false;
                useStreamingStore.getState().setStatus('error');
                useStreamingStore.getState().setError('Connection error');
                console.error('[WebSocket] Error:', error);
            };
        } catch (error) {
            this.isConnecting = false;
            useStreamingStore.getState().setStatus('error');
            useStreamingStore.getState().setError(error instanceof Error ? error.message : 'Unknown error');
            this.scheduleReconnect();
        }
    }

    /**
     * Schedule reconnection with exponential backoff
     */
    private scheduleReconnect(): void {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            useStreamingStore.getState().setStatus('error');
            useStreamingStore.getState().setError('Max reconnection attempts reached');
            console.error('[WebSocket] Max reconnection attempts reached');
            return;
        }

        this.reconnectAttempts++;
        useStreamingStore.getState().setStatus('reconnecting');
        useStreamingStore.getState().incrementReconnectAttempts();

        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (capped)
        const delay = Math.min(
            this.baseDelay * Math.pow(2, this.reconnectAttempts - 1),
            this.maxDelay
        );

        console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

        this.reconnectTimer = setTimeout(() => {
            this.attemptConnection();
        }, delay);
    }

    /**
     * Start heartbeat (ping/pong)
     */
    private startHeartbeat(): void {
        this.stopHeartbeat();
        
        this.heartbeatTimer = setInterval(() => {
            const timeSinceLastPong = Date.now() - this.lastPongTime;
            
            // If no pong received in 2x heartbeat interval, connection is stale
            if (timeSinceLastPong > this.heartbeatInterval * 2) {
                console.warn('[WebSocket] Connection stale, closing');
                this.ws?.close();
                return;
            }
            
            // Send ping
            if (this.ws?.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, this.heartbeatInterval);
    }

    /**
     * Stop heartbeat
     */
    private stopHeartbeat(): void {
        if (this.heartbeatTimer) {
            clearInterval(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
    }

    /**
     * Subscribe to message type
     */
    subscribe(type: string, handler: (data: any) => void): () => void {
        if (!this.messageHandlers.has(type)) {
            this.messageHandlers.set(type, new Set());
        }
        this.messageHandlers.get(type)!.add(handler);

        // Return unsubscribe function
        return () => {
            this.unsubscribe(type, handler);
        };
    }

    /**
     * Unsubscribe from message type
     */
    unsubscribe(type: string, handler: (data: any) => void): void {
        const handlers = this.messageHandlers.get(type);
        if (handlers) {
            handlers.delete(handler);
            if (handlers.size === 0) {
                this.messageHandlers.delete(type);
            }
        }
    }

    /**
     * Re-subscribe to all channels (after reconnection)
     */
    private resubscribeAll(): void {
        // Send subscription messages for all active handlers
        const types = Array.from(this.messageHandlers.keys());
        if (types.length > 0 && this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'subscribe',
                channels: types
            }));
        }
    }

    /**
     * Send message
     */
    send(data: any): void {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
            console.warn('[WebSocket] Cannot send, connection not open');
        }
    }

    /**
     * Disconnect
     */
    disconnect(): void {
        this.stopHeartbeat();
        
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        this.isConnecting = false;
        this.reconnectAttempts = 0;
        useStreamingStore.getState().setStatus('disconnected');
    }

    /**
     * Get connection status
     */
    get isConnected(): boolean {
        return this.ws?.readyState === WebSocket.OPEN;
    }

    /**
     * Get ready state
     */
    get readyState(): number {
        return this.ws?.readyState ?? WebSocket.CLOSED;
    }
}

// Singleton instance
let managerInstance: WebSocketManager | null = null;

export function getWebSocketManager(): WebSocketManager {
    if (!managerInstance) {
        managerInstance = new WebSocketManager();
    }
    return managerInstance;
}

export function resetWebSocketManager(): void {
    managerInstance?.disconnect();
    managerInstance = null;
}
