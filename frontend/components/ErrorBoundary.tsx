import React, { Component, ErrorInfo, ReactNode } from 'react';

interface ErrorBoundaryProps {
    children: ReactNode;
    name?: string;
    fallback?: ReactNode;
}

interface ErrorBoundaryState {
    hasError: boolean;
    error: Error | null;
}

/**
 * Catches render errors in child components and displays a fallback UI.
 * Prevents a single component crash from taking down the entire page.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
    constructor(props: ErrorBoundaryProps) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error: Error): ErrorBoundaryState {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, info: ErrorInfo): void {
        const name = this.props.name || 'ErrorBoundary';
        console.error(`[ErrorBoundary:${name}]`, error, info);
    }

    render(): ReactNode {
        if (this.state.hasError) {
            if (this.props.fallback) return this.props.fallback;
            return (
                <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs" role="alert">
                    <p className="font-bold mb-1">Component Error</p>
                    <p className="font-mono text-[10px] opacity-70">
                        {this.state.error?.message || 'An unexpected error occurred'}
                    </p>
                </div>
            );
        }

        return this.props.children;
    }
}

export default ErrorBoundary;
