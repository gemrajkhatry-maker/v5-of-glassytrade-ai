
import { OHLCData, OrderBook, VolumeProfileLevel, TradeSignal, AMTAnalysis, AggressivePrint } from '../types';

/**
 * AUCTION MARKET THEORY (AMT) SERVICE
 */

const CONFIG = {
    LVN_THRESHOLD: 0.40,   // <40% of mean volume = Low Volume Node (formula: 0.3-0.5)
    HVN_THRESHOLD: 0.40,   // >40% of max volume = High Volume Node (formula: 0.3-0.5)
    LVN_SMOOTHING: 3,      // Smooth histogram before LVN/HVN detection
    OBI_THRESHOLD: 0.25,
    DELTA_THRESHOLD: 0.3,
    ABSORPTION_THRESHOLD: 0.3,
    STOP_BUFFER: 0.001,
    BUBBLE_VOL_MULTIPLIER: 2.5 // 2.5σ aggressive prints
};

// Centered simple moving average smoothing (for LVN/HVN detection)
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

const createProfile = (data: OHLCData[], buckets = 24): VolumeProfileLevel[] => {
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
        if (d.volume <= 0) return;

        let startBucket = Math.floor((d.low - min) / step);
        let endBucket = Math.floor((d.high - min) / step);
        startBucket = Math.max(0, Math.min(buckets - 1, startBucket));
        endBucket = Math.max(0, Math.min(buckets - 1, endBucket));

        // Buy/sell split: use taker data if available, else body-proportional
        let buyRatio: number;
        if (d.takerBuyVolume > 0 && d.volume > 0) {
            buyRatio = d.takerBuyVolume / d.volume;
        } else {
            const body = Math.abs(d.close - d.open);
            const candleRange = d.high - d.low;
            if (candleRange === 0) {
                buyRatio = 0.5;
            } else {
                buyRatio = d.close >= d.open
                    ? 0.5 + 0.5 * (body / candleRange)
                    : 0.5 - 0.5 * (body / candleRange);
            }
        }

        // Gaussian-weighted distribution centered on VWAP/close (matches backend)
        const center = (d.vwap && d.vwap > 0) ? d.vwap : d.close;
        const candleRange = d.high - d.low;
        const sigma = Math.max(candleRange * 0.25, step * 0.5);

        const weights: number[] = [];
        let totalWeight = 0;
        for (let i = startBucket; i <= endBucket; i++) {
            const bucketCenter = profile[i].price;
            const z = (bucketCenter - center) / sigma;
            const w = Math.exp(-0.5 * z * z);
            weights.push(w);
            totalWeight += w;
        }
        if (totalWeight <= 0) {
            const n = Math.max(1, endBucket - startBucket + 1);
            for (let i = 0; i < weights.length; i++) weights[i] = 1.0 / n;
            totalWeight = 1.0;
        }

        for (let i = startBucket; i <= endBucket; i++) {
            if (profile[i]) {
                const frac = weights[i - startBucket] / totalWeight;
                const vol = d.volume * frac;
                profile[i].volume += vol;
                profile[i].buyVolume += vol * buyRatio;
                profile[i].sellVolume += vol * (1 - buyRatio);
            }
        }
    });

    return profile;
};

const findLVNs = (profile: VolumeProfileLevel[]): number[] => {
    if (profile.length < 3) return [];
    const raw = profile.map(p => p.volume);
    const sm = smoothArray(raw, CONFIG.LVN_SMOOTHING);
    const meanVol = sm.reduce((a, b) => a + b, 0) / sm.length;
    if (meanVol <= 0) return [];

    const threshold = meanVol * CONFIG.LVN_THRESHOLD;
    const step = profile[1].price - profile[0].price;
    const lvns: number[] = [];

    for (let i = 1; i < sm.length - 1; i++) {
        if (sm[i] < sm[i - 1] && sm[i] < sm[i + 1] && sm[i] <= threshold) {
            if (lvns.length === 0 || Math.abs(profile[i].price - lvns[lvns.length - 1]) > step * 2) {
                lvns.push(profile[i].price);
            }
        }
    }
    return lvns;
};

const findHVNs = (profile: VolumeProfileLevel[]): number[] => {
    if (profile.length < 3) return [];
    const raw = profile.map(p => p.volume);
    const sm = smoothArray(raw, CONFIG.LVN_SMOOTHING);
    const maxVol = Math.max(...sm);
    if (maxVol <= 0) return [];

    const threshold = maxVol * CONFIG.HVN_THRESHOLD;
    const step = profile[1].price - profile[0].price;
    const hvns: number[] = [];

    for (let i = 1; i < sm.length - 1; i++) {
        if (sm[i] > sm[i - 1] && sm[i] > sm[i + 1] && sm[i] >= threshold) {
            if (hvns.length === 0 || Math.abs(profile[i].price - hvns[hvns.length - 1]) > step * 2) {
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
            aggressivePrints: [],
            legProfile: [], legLvns: [], legPoc: 0, legVah: 0, legVal: 0, hasDisplacement: false
        };
    }

    const lookback = Math.min(data.length, 50);
    const recentData = data.slice(-lookback);
    const currentCandle = data[data.length - 1];

    // 1. VOLUME PROFILE
    const profile = createProfile(recentData);
    if (profile.length === 0) return { marketState: 'BALANCED', poc: 0, valueAreaHigh: 0, valueAreaLow: 0, lvns: [], hvns: [], aggression: 0, signal: null, setup: null, profile: [], aggressivePrints: [], legProfile: [], legLvns: [], legPoc: 0, legVah: 0, legVal: 0, hasDisplacement: false };

    // Find POC — tie-break: closest to current price when multiple bins share max volume
    const maxVol = Math.max(...profile.map(p => p.volume));
    const pocCandidates = profile.map((p, i) => ({ i, vol: p.volume })).filter(c => c.vol === maxVol);
    const currentPrice = currentCandle.close;
    const pocIndex = pocCandidates.reduce((best, c) =>
        Math.abs(profile[c.i].price - currentPrice) < Math.abs(profile[best.i].price - currentPrice) ? c : best
    ).i;
    const poc = profile[pocIndex].price;

    // Calculate Value Area (70%)
    const totalVolume = profile.reduce((sum, p) => sum + p.volume, 0);
    const targetVolume = totalVolume * 0.7;
    let currentVolume = maxVol;
    let upIdx = pocIndex;
    let downIdx = pocIndex;

    // CME two-row pairs method with upward tie-breaking
    while (currentVolume < targetVolume) {
        // Sum next TWO rows above
        let upPair = 0;
        let upCount = 0;
        for (let k = 1; k <= 2; k++) {
            if (upIdx + k < profile.length) { upPair += profile[upIdx + k].volume; upCount++; }
        }
        // Sum next TWO rows below
        let downPair = 0;
        let downCount = 0;
        for (let k = 1; k <= 2; k++) {
            if (downIdx - k >= 0) { downPair += profile[downIdx - k].volume; downCount++; }
        }

        if (upCount === 0 && downCount === 0) break;

        if (upCount > 0 && (downCount === 0 || upPair >= downPair)) {
            // Expand upward (tie: upward first per convention)
            for (let k = 0; k < upCount; k++) {
                if (upIdx + 1 < profile.length) { upIdx++; currentVolume += profile[upIdx].volume; }
            }
        } else if (downCount > 0) {
            for (let k = 0; k < downCount; k++) {
                if (downIdx - 1 >= 0) { downIdx--; currentVolume += profile[downIdx].volume; }
            }
        }
    }

    // VAH = upper edge of top VA bin, VAL = lower edge of bottom VA bin
    const step = profile.length > 1 ? profile[1].price - profile[0].price : 0;
    const halfStep = step / 2;
    const valueAreaHigh = profile[upIdx].price + halfStep;
    const valueAreaLow = profile[downIdx].price - halfStep;
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
        aggressivePrints,
        legProfile: [], legLvns: [], legPoc: 0, legVah: 0, legVal: 0, hasDisplacement: false
    };
};
