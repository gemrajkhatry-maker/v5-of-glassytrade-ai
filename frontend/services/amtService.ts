
import { OHLCData, OrderBook, VolumeProfileLevel, TradeSignal, AMTAnalysis, AggressivePrint } from '../types';

/**
 * AUCTION MARKET THEORY (AMT) SERVICE
 */

const CONFIG = {
    LVN_SMOOTHING: 3, 
    LVN_PROMINENCE: 0.85, // Increased from 0.70 to 0.85 to make LVNs easier to find (less strict)
    OBI_THRESHOLD: 0.25,
    DELTA_THRESHOLD: 0.3,
    ABSORPTION_THRESHOLD: 0.3,
    STOP_BUFFER: 0.001,
    BUBBLE_VOL_MULTIPLIER: 1.5 // Multiplier of Avg Vol to be considered a bubble
};

// Helper: Calculate Simple Moving Average (Centered)
const smoothArray = (data: number[], window: number): number[] => {
    const smoothed: number[] = [];
    const offset = Math.floor(window / 2);
    
    for (let i = 0; i < data.length; i++) {
        let sum = 0;
        let count = 0;
        for (let j = i - offset; j <= i + offset; j++) {
            if (j >= 0 && j < data.length) {
                sum += data[j];
                count++;
            }
        }
        smoothed.push(sum / count);
    }
    return smoothed;
};

const createProfile = (data: OHLCData[], buckets = 50): VolumeProfileLevel[] => {
    if (data.length === 0) return [];
    
    let min = Infinity;
    let max = -Infinity;
    data.forEach(d => {
        if (d.low < min) min = d.low;
        if (d.high > max) max = d.high;
    });

    const buffer = (max - min) * 0.01;
    min -= buffer;
    max += buffer;

    const range = max - min;
    if (range === 0) {
        return new Array(buckets).fill(0).map((_, i) => ({
            price: min,
            volume: data.reduce((sum, d) => sum + d.volume, 0) / buckets,
            buyVolume: 0,
            sellVolume: 0
        }));
    }

    const step = range / buckets;
    const profile: VolumeProfileLevel[] = new Array(buckets).fill(0).map((_, i) => ({
        price: min + (i * step) + (step / 2),
        volume: 0,
        buyVolume: 0,
        sellVolume: 0
    }));

    data.forEach(d => {
        let startBucket = Math.floor((d.low - min) / step);
        let endBucket = Math.floor((d.high - min) / step);
        startBucket = Math.max(0, Math.min(buckets - 1, startBucket));
        endBucket = Math.max(0, Math.min(buckets - 1, endBucket));

        const bucketsCovered = Math.max(1, endBucket - startBucket + 1);
        const volPerBucket = d.volume / bucketsCovered;
        
        // Approximate Buy vs Sell based on TakerBuyVolume
        const buyRatio = d.volume > 0 ? d.takerBuyVolume / d.volume : 0.5;
        const buyVolPerBucket = volPerBucket * buyRatio;
        const sellVolPerBucket = volPerBucket * (1 - buyRatio);

        for (let i = startBucket; i <= endBucket; i++) {
            if (profile[i]) {
                profile[i].volume += volPerBucket;
                profile[i].buyVolume += buyVolPerBucket;
                profile[i].sellVolume += sellVolPerBucket;
            }
        }
    });

    return profile;
};

const findLVNs = (profile: VolumeProfileLevel[]): number[] => {
    const rawVolumes = profile.map(p => p.volume);
    const smoothed = smoothArray(rawVolumes, CONFIG.LVN_SMOOTHING);
    const lvns: number[] = [];

    // Skip edges to avoid false LVNs at top/bottom of chart
    for (let i = 3; i < smoothed.length - 3; i++) {
        // Local Minimum
        if (smoothed[i] <= smoothed[i - 1] && smoothed[i] <= smoothed[i + 1]) {
            
            // Find surrounding peaks
            let leftPeak = smoothed[i];
            let l = i; 
            while (l > 0 && smoothed[l - 1] >= smoothed[l]) { 
                l--; 
                leftPeak = smoothed[l]; 
            }
            
            let rightPeak = smoothed[i];
            let r = i; 
            while (r < smoothed.length - 1 && smoothed[r + 1] >= smoothed[r]) { 
                r++; 
                rightPeak = smoothed[r]; 
            }

            const lowerPeak = Math.min(leftPeak, rightPeak);
            
            // Prominence Check
            if (profile[i].volume < lowerPeak * CONFIG.LVN_PROMINENCE) {
                lvns.push(profile[i].price);
            }
        }
    }
    return lvns;
};

const findHVNs = (profile: VolumeProfileLevel[]): number[] => {
    const rawVolumes = profile.map(p => p.volume);
    const smoothed = smoothArray(rawVolumes, CONFIG.LVN_SMOOTHING);
    const hvns: number[] = [];

    // Local Maxima
    for (let i = 2; i < smoothed.length - 2; i++) {
        if (smoothed[i] >= smoothed[i - 1] && smoothed[i] >= smoothed[i + 1]) {
            const maxVol = Math.max(...smoothed);
            // Significant volume only (> 40% of max)
            if (smoothed[i] > maxVol * 0.4) { 
                 hvns.push(profile[i].price);
            }
        }
    }
    return hvns;
};

const findAggressivePrints = (data: OHLCData[]): AggressivePrint[] => {
    const prints: AggressivePrint[] = [];
    if (data.length < 50) return prints;

    // Calculate Avg Volume
    const avgVol = data.reduce((s, d) => s + d.volume, 0) / data.length;
    const threshold = avgVol * CONFIG.BUBBLE_VOL_MULTIPLIER;

    data.forEach(d => {
        if (d.volume > threshold) {
            // Check for directional aggression
            // Significant delta relative to volume
            const deltaRatio = Math.abs(d.delta) / d.volume;
            
            if (deltaRatio > 0.15) { // At least 15% imbalance
                prints.push({
                    price: d.close,
                    time: d.time,
                    volume: d.volume,
                    delta: d.delta,
                    side: d.delta > 0 ? 'BUY' : 'SELL'
                });
            }
        }
    });

    return prints;
};

export const analyzeAMT = (
    data: OHLCData[], 
    orderBook: OrderBook | null
): AMTAnalysis => {
    // 0. Safety Checks
    if (!data || data.length < 5) {
        return {
            marketState: 'BALANCED',
            poc: 0,
            valueAreaHigh: 0,
            valueAreaLow: 0,
            lvns: [],
            hvns: [],
            aggression: 0,
            signal: null,
            setup: null,
            profile: [],
            aggressivePrints: []
        };
    }

    const lookback = Math.min(data.length, 200);
    const recentData = data.slice(-lookback);
    const currentCandle = data[data.length - 1];

    // 1. VOLUME PROFILE
    const profile = createProfile(recentData);
    if (profile.length === 0) return { marketState: 'BALANCED', poc: 0, valueAreaHigh: 0, valueAreaLow: 0, lvns: [], hvns: [], aggression: 0, signal: null, setup: null, profile: [], aggressivePrints: [] };

    // Find POC
    let maxVol = 0;
    let pocIndex = 0;
    profile.forEach((level, i) => {
        if (level.volume > maxVol) {
            maxVol = level.volume;
            pocIndex = i;
        }
    });
    const poc = profile[pocIndex].price;

    // Calculate Value Area (70%)
    const totalVolume = profile.reduce((sum, p) => sum + p.volume, 0);
    const targetVolume = totalVolume * 0.7;
    let currentVolume = maxVol;
    let upIdx = pocIndex;
    let downIdx = pocIndex;

    while (currentVolume < targetVolume) {
        const upVol = (upIdx < profile.length - 1) ? profile[upIdx + 1].volume : 0;
        const downVol = (downIdx > 0) ? profile[downIdx - 1].volume : 0;

        if (upVol >= downVol && upIdx < profile.length - 1) {
            upIdx++;
            currentVolume += profile[upIdx].volume;
        } else if (downIdx > 0) {
            downIdx--;
            currentVolume += profile[downIdx].volume;
        } else {
            break;
        }
    }

    const valueAreaHigh = profile[upIdx].price;
    const valueAreaLow = profile[downIdx].price;
    const lvns = findLVNs(profile);
    const hvns = findHVNs(profile);
    const aggressivePrints = findAggressivePrints(recentData);

    // 2. MARKET STATE
    const isBalanced = currentCandle.close >= valueAreaLow && currentCandle.close <= valueAreaHigh;
    const marketState = isBalanced ? 'BALANCED' : 'IMBALANCED';

    // 3. AGGRESSION
    let obi = 0;
    if (orderBook) {
        const bids = orderBook.bids.reduce((a, b) => a + b.quantity, 0);
        const asks = orderBook.asks.reduce((a, b) => a + b.quantity, 0);
        const total = bids + asks;
        if (total > 0) obi = (bids - asks) / total;
    }

    const normalizedDelta = currentCandle.volume > 0 ? currentCandle.delta / currentCandle.volume : 0;
    
    const obiAggressive = Math.abs(obi) > CONFIG.OBI_THRESHOLD;
    const deltaAggressive = Math.abs(normalizedDelta) > CONFIG.DELTA_THRESHOLD;
    
    const candleRange = Math.max(currentCandle.high - currentCandle.low, currentCandle.close * 0.0001);
    const bodySize = Math.abs(currentCandle.close - currentCandle.open);
    const priceFlat = (bodySize / candleRange) < 0.3;
    
    const bullishAbsorption = normalizedDelta > CONFIG.ABSORPTION_THRESHOLD && priceFlat;
    const bearishAbsorption = normalizedDelta < -CONFIG.ABSORPTION_THRESHOLD && priceFlat;
    const isAbsorption = bullishAbsorption || bearishAbsorption;

    const hasAggression = obiAggressive || deltaAggressive || isAbsorption;

    let aggressionScore = 0;
    if (hasAggression) {
        const dir = (obi > 0 || normalizedDelta > 0) ? 1 : -1;
        aggressionScore = dir * Math.max(Math.abs(obi), Math.abs(normalizedDelta), isAbsorption ? 0.5 : 0);
    }

    // 4. SIGNAL GENERATION
    let signal: TradeSignal | null = null;
    let setup: 'TREND_MODEL' | 'MEAN_REVERSION' | null = null;

    if (marketState === 'IMBALANCED' && hasAggression) {
        const nearbyLVN = lvns.find(lvn => Math.abs(currentCandle.close - lvn) / lvn < 0.003);
        if (nearbyLVN) {
            const isBullish = currentCandle.close > valueAreaHigh && aggressionScore > 0;
            const isBearish = currentCandle.close < valueAreaLow && aggressionScore < 0;

            if (isBullish) {
                setup = 'TREND_MODEL';
                signal = {
                    type: 'BUY',
                    price: currentCandle.close,
                    reason: 'Trend Continuation: Aggression at LVN',
                    setup: 'TREND_MODEL',
                    source: 'AMT',
                    stopLoss: currentCandle.low * (1 - CONFIG.STOP_BUFFER),
                    takeProfit: currentCandle.close * 1.05,
                    timestamp: new Date().toISOString()
                };
            } else if (isBearish) {
                setup = 'TREND_MODEL';
                signal = {
                    type: 'SELL',
                    price: currentCandle.close,
                    reason: 'Trend Continuation: Aggression at LVN',
                    setup: 'TREND_MODEL',
                    source: 'AMT',
                    stopLoss: currentCandle.high * (1 + CONFIG.STOP_BUFFER),
                    takeProfit: currentCandle.close * 0.95,
                    timestamp: new Date().toISOString()
                };
            }
        }
    }

    if (marketState === 'BALANCED' && hasAggression) {
        const recentHistory = data.slice(-5);
        let hadBreakoutAbove = false;
        let hadBreakoutBelow = false;
        
        for (let i = 0; i < recentHistory.length - 1; i++) {
            if (recentHistory[i].high > valueAreaHigh) hadBreakoutAbove = true;
            if (recentHistory[i].low < valueAreaLow) hadBreakoutBelow = true;
        }

        const isInside = currentCandle.close < valueAreaHigh && currentCandle.close > valueAreaLow;
        const prevInside = data[data.length-2].close < valueAreaHigh && data[data.length-2].close > valueAreaLow;
        const reclaimConfirmed = isInside && prevInside;

        if (reclaimConfirmed) {
            if (hadBreakoutBelow && aggressionScore > 0) {
                setup = 'MEAN_REVERSION';
                signal = {
                    type: 'BUY',
                    price: currentCandle.close,
                    reason: 'Mean Reversion: Confirmed Reclaim',
                    setup: 'MEAN_REVERSION',
                    source: 'AMT',
                    stopLoss: valueAreaLow * (1 - CONFIG.STOP_BUFFER),
                    takeProfit: poc,
                    timestamp: new Date().toISOString()
                };
            } else if (hadBreakoutAbove && aggressionScore < 0) {
                setup = 'MEAN_REVERSION';
                signal = {
                    type: 'SELL',
                    price: currentCandle.close,
                    reason: 'Mean Reversion: Confirmed Reclaim',
                    setup: 'MEAN_REVERSION',
                    source: 'AMT',
                    stopLoss: valueAreaHigh * (1 + CONFIG.STOP_BUFFER),
                    takeProfit: poc,
                    timestamp: new Date().toISOString()
                };
            }
        }
    }

    return {
        marketState,
        poc,
        valueAreaHigh,
        valueAreaLow,
        lvns,
        hvns,
        aggression: aggressionScore,
        signal,
        setup,
        profile,
        aggressivePrints
    };
};
