import React, { Component, ReactNode } from 'react';

interface Props { children: ReactNode; fallback?: ReactNode; name?: string; }
interface State { hasError: boolean; error: Error | null; retryCount: number; }

const MAX_RETRIES = 3;

/**
 * Generic error boundary that catches render errors in child components.
 * Displays a retry-able fallback UI with the error message.
 * Stops retrying after MAX_RETRIES to prevent infinite loops.
 */
class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false, error: null, retryCount: 0 };

    static getDerivedStateFromError(error: Error): Partial<State> {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, info: React.ErrorInfo) {
        console.error(`[ErrorBoundary:${this.props.name}]`, error, info);
    }

    handleRetry = () => {
        this.setState(prev => ({
            hasError: false,
            error: null,
            retryCount: prev.retryCount + 1,
        }));
    };

    render() {
        if (this.state.hasError) {
            if (this.props.fallback) return this.props.fallback;

            const canRetry = this.state.retryCount < MAX_RETRIES;

            return (
                <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
                    <p className="font-bold">Component Error{this.props.name ? `: ${this.props.name}` : ''}</p>
                    <p className="text-xs text-red-400/70 mt-1">{this.state.error?.message}</p>
                    {canRetry ? (
                        <button
                            onClick={this.handleRetry}
                            className="mt-2 px-3 py-1 bg-red-500/20 rounded text-xs hover:bg-red-500/30"
                        >
                            Retry ({MAX_RETRIES - this.state.retryCount} left)
                        </button>
                    ) : (
                        <p className="mt-2 text-xs text-red-400/50">Max retries reached. Please reload the page.</p>
                    )}
                </div>
            );
        }
        return this.props.children;
    }
}

export default ErrorBoundary;
