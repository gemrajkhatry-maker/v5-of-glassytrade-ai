
import { ModelWeights, TradePosition, FactorBreakdown } from '../types';

/**
 * AI LEARNING ENGINE
 * 
 * This engine implements a feedback loop for the Quant Model.
 * It analyzes closed trades and adjusts the weights of the prediction factors
 * (Trend, Momentum, Delta, OrderBook) based on success or failure.
 */

export class AILearningEngine {
    private weights: ModelWeights;
    private learningRate: number = 0.05;
    private generation: number = 0;
    private history: { generation: number, result: 'WIN' | 'LOSS', weights: ModelWeights }[] = [];

    constructor() {
        // Initial Default Weights (Sum to ~1.0)
        this.weights = {
            trend: 0.40,
            momentum: 0.25,
            delta: 0.15,
            orderBook: 0.15,
            volatility: 0.05
        };
    }

    public getWeights(): ModelWeights {
        return { ...this.weights };
    }

    public getGeneration(): number {
        return this.generation;
    }

    /**
     * The Core Learning Step
     * Called when a Prediction Trade is closed.
     */
    public learn(trade: TradePosition) {
        if (trade.source !== 'PREDICTION' || !trade.metadata?.factorBreakdown) return;

        const breakdown = trade.metadata.factorBreakdown as FactorBreakdown;
        const isWin = trade.pnl > 0;
        const tradeDir = trade.side === 'LONG' ? 1 : -1;

        // "Backpropagation" Simulation
        // We look at which factors agreed with the trade direction.
        // If WIN: Boost factors that agreed.
        // If LOSS: Penalize factors that agreed (they were wrong).

        const adjustments: Partial<ModelWeights> = {};

        // Helper to check alignment
        // factorScore is the raw contribution (e.g. +50 for Uptrend).
        const checkFactor = (factorScore: number, key: keyof ModelWeights) => {
            const factorDir = factorScore > 0 ? 1 : factorScore < 0 ? -1 : 0;
            
            if (factorDir === 0) return; // Factor was neutral, no learning

            const agreed = factorDir === tradeDir;

            if (isWin) {
                // Reinforce: If it agreed, increase weight. If it disagreed, decrease weight (it was fighting the win).
                if (agreed) this.weights[key] += this.learningRate;
                else this.weights[key] -= this.learningRate * 0.5;
            } else {
                // Penalize: If it agreed (led us to loss), decrease weight. If it disagreed (was right!), increase weight.
                if (agreed) this.weights[key] -= this.learningRate;
                else this.weights[key] += this.learningRate * 0.5;
            }
        };

        checkFactor(breakdown.trend, 'trend');
        checkFactor(breakdown.momentum, 'momentum');
        checkFactor(breakdown.delta, 'delta');
        checkFactor(breakdown.orderBook, 'orderBook');
        // Volatility is usually a scaler, not directional, so we might skip or treat differently. 
        // For simplicity, let's treat it as a confidence booster.

        this.normalizeWeights();
        this.generation++;
        
        this.history.push({
            generation: this.generation,
            result: isWin ? 'WIN' : 'LOSS',
            weights: { ...this.weights }
        });

        console.log(`[AI LEARNING] Gen ${this.generation} | Result: ${isWin ? 'WIN' : 'LOSS'} | Updated Weights:`, this.weights);
    }

    private normalizeWeights() {
        const total = Object.values(this.weights).reduce((a, b) => a + Math.abs(b), 0);
        if (total === 0) return;

        // Normalize to sum to 1.0
        (Object.keys(this.weights) as Array<keyof ModelWeights>).forEach(key => {
            this.weights[key] = Math.max(0.01, this.weights[key] / total); // Prevent 0 weight
        });
    }
}
