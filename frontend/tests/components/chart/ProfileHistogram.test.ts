import { describe, it, expect } from 'vitest';
import {
  calculatePriceTolerance,
  isPriceNearTarget,
  isInValueArea,
  classifyZoneType,
  calculateBarColor,
  calculateEdgeStyle,
  generateProfileConfig,
  validateProfileData,
  getProfileStats,
  ProfileLevel,
  ProfileRenderOptions,
} from '../../../components/chart/ProfileHistogram';

describe('ProfileHistogram', () => {
  const sampleProfile: ProfileLevel[] = [
    { price: 49900, volume: 100, buyVolume: 60, sellVolume: 40 },
    { price: 49950, volume: 200, buyVolume: 120, sellVolume: 80 },
    { price: 50000, volume: 500, buyVolume: 300, sellVolume: 200 }, // POC
    { price: 50050, volume: 300, buyVolume: 150, sellVolume: 150 },
    { price: 50100, volume: 150, buyVolume: 70, sellVolume: 80 },
  ];

  const defaultOptions: ProfileRenderOptions = {
    maxWidthPct: 0.15,
    xOffset: 0,
    canvasWidth: 1000,
    bullColor: '#4488cc',
    bearColor: '#cc4444',
    useDirectionColors: true,
    hvnPrices: [50000, 49950],
    lvnPrices: [49900],
    vahPrice: 50050,
    valPrice: 49950,
    pocPrice: 50000,
  };

  describe('calculatePriceTolerance', () => {
    it('calculates tolerance from price step', () => {
      const tolerance = calculatePriceTolerance(sampleProfile);
      expect(tolerance).toBe(30); // 50 * 0.6
    });

    it('returns 1 for single level', () => {
      const tolerance = calculatePriceTolerance([{ price: 50000, volume: 100, buyVolume: 50, sellVolume: 50 }]);
      expect(tolerance).toBe(1);
    });

    it('returns 1 for empty profile', () => {
      const tolerance = calculatePriceTolerance([]);
      expect(tolerance).toBe(1);
    });
  });

  describe('isPriceNearTarget', () => {
    it('returns true for price within tolerance', () => {
      const result = isPriceNearTarget(50005, [50000, 49950], 10);
      expect(result).toBe(true);
    });

    it('returns false for price outside tolerance', () => {
      const result = isPriceNearTarget(50100, [50000, 49950], 10);
      expect(result).toBe(false);
    });

    it('returns false for undefined targets', () => {
      const result = isPriceNearTarget(50000, undefined, 10);
      expect(result).toBe(false);
    });

    it('returns false for empty targets', () => {
      const result = isPriceNearTarget(50000, [], 10);
      expect(result).toBe(false);
    });
  });

  describe('isInValueArea', () => {
    it('returns true for price in value area', () => {
      const result = isInValueArea(50000, 50050, 49950);
      expect(result).toBe(true);
    });

    it('returns false for price below VA', () => {
      const result = isInValueArea(49900, 50050, 49950);
      expect(result).toBe(false);
    });

    it('returns false for price above VA', () => {
      const result = isInValueArea(50100, 50050, 49950);
      expect(result).toBe(false);
    });

    it('returns false for undefined VA prices', () => {
      const result = isInValueArea(50000, undefined, undefined);
      expect(result).toBe(false);
    });
  });

  describe('classifyZoneType', () => {
    const tolerance = 30;

    it('classifies POC zone', () => {
      const zone = classifyZoneType(50000, defaultOptions, tolerance);
      expect(zone).toBe('poc');
    });

    it('classifies HVN zone', () => {
      const zone = classifyZoneType(49950, defaultOptions, tolerance);
      expect(zone).toBe('hvn');
    });

    it('classifies LVN zone', () => {
      const zone = classifyZoneType(49900, defaultOptions, tolerance);
      expect(zone).toBe('lvn');
    });

    it('classifies value area zone', () => {
      const options: ProfileRenderOptions = {
        ...defaultOptions,
        pocPrice: undefined,
        hvnPrices: [],
        lvnPrices: [],
      };
      const zone = classifyZoneType(50000, options, tolerance);
      expect(zone).toBe('valueArea');
    });

    it('classifies normal zone', () => {
      const options: ProfileRenderOptions = {
        ...defaultOptions,
        pocPrice: undefined,
        hvnPrices: [],
        lvnPrices: [],
        vahPrice: undefined,
        valPrice: undefined,
      };
      const zone = classifyZoneType(50100, options, tolerance);
      expect(zone).toBe('normal');
    });
  });

  describe('calculateBarColor', () => {
    it('returns bullish color with high alpha for POC', () => {
      const level: ProfileLevel = { price: 50000, volume: 500, buyVolume: 300, sellVolume: 200 };
      const { baseColor, baseAlpha } = calculateBarColor(level, 'poc', defaultOptions);
      expect(baseColor).toBe('#4488cc'); // Bullish
      expect(baseAlpha).toBe(0.85);
    });

    it('returns bearish color when sellVolume > buyVolume', () => {
      const level: ProfileLevel = { price: 50050, volume: 300, buyVolume: 100, sellVolume: 200 };
      const { baseColor, baseAlpha } = calculateBarColor(level, 'hvn', defaultOptions);
      expect(baseColor).toBe('#cc4444'); // Bearish
      expect(baseAlpha).toBe(0.65);
    });

    it('uses bullColor for all bars when useDirectionColors is false', () => {
      const level: ProfileLevel = { price: 50050, volume: 300, buyVolume: 100, sellVolume: 200 };
      const options: ProfileRenderOptions = { ...defaultOptions, useDirectionColors: false };
      const { baseColor } = calculateBarColor(level, 'normal', options);
      expect(baseColor).toBe('#4488cc');
    });

    it('returns correct alpha for LVN', () => {
      const level: ProfileLevel = { price: 49900, volume: 100, buyVolume: 60, sellVolume: 40 };
      const { baseAlpha } = calculateBarColor(level, 'lvn', defaultOptions);
      expect(baseAlpha).toBe(0.18);
    });

    it('returns correct alpha for value area', () => {
      const level: ProfileLevel = { price: 50000, volume: 500, buyVolume: 300, sellVolume: 200 };
      const { baseAlpha } = calculateBarColor(level, 'valueArea', defaultOptions);
      expect(baseAlpha).toBe(0.45);
    });

    it('returns correct alpha for normal zone', () => {
      const level: ProfileLevel = { price: 50100, volume: 150, buyVolume: 70, sellVolume: 80 };
      const { baseAlpha } = calculateBarColor(level, 'normal', defaultOptions);
      expect(baseAlpha).toBe(0.30);
    });
  });

  describe('calculateEdgeStyle', () => {
    it('returns POC edge style', () => {
      const style = calculateEdgeStyle('poc', '#4488cc', 0.85);
      expect(style.edgeWidth).toBe(2);
      expect(style.edgeColor).toBe('#facc15');
      expect(style.edgeAlpha).toBe(0.9);
    });

    it('returns HVN edge style', () => {
      const style = calculateEdgeStyle('hvn', '#4488cc', 0.65);
      expect(style.edgeWidth).toBe(2);
      expect(style.edgeColor).toBe('#22c55e');
      expect(style.edgeAlpha).toBe(0.7);
    });

    it('returns LVN edge style', () => {
      const style = calculateEdgeStyle('lvn', '#4488cc', 0.18);
      expect(style.edgeWidth).toBe(1);
      expect(style.edgeColor).toBe('#f97316');
      expect(style.edgeAlpha).toBe(0.5);
    });

    it('returns normal edge style', () => {
      const style = calculateEdgeStyle('normal', '#4488cc', 0.30);
      expect(style.edgeWidth).toBe(1);
      expect(style.edgeColor).toBe('#4488cc');
      expect(style.edgeAlpha).toBe(0.24); // 0.30 * 0.8
    });
  });

  describe('generateProfileConfig', () => {
    const mockPriceToY = (price: number) => 1000 - (price - 49000) * 10;

    it('generates config for all profile levels', () => {
      const config = generateProfileConfig(sampleProfile, mockPriceToY, defaultOptions);
      expect(config.bars.length).toBe(5);
    });

    it('calculates correct max volume', () => {
      const config = generateProfileConfig(sampleProfile, mockPriceToY, defaultOptions);
      expect(config.maxVolume).toBe(500);
    });

    it('generates value area zone', () => {
      const config = generateProfileConfig(sampleProfile, mockPriceToY, defaultOptions);
      expect(config.valueAreaZone).not.toBeNull();
      expect(config.valueAreaZone?.width).toBeGreaterThan(0);
    });

    it('returns empty config for empty profile', () => {
      const config = generateProfileConfig([], mockPriceToY, defaultOptions);
      expect(config.bars).toHaveLength(0);
      expect(config.maxVolume).toBe(0);
    });

    it('returns empty config when max volume is 0', () => {
      const zeroProfile: ProfileLevel[] = [
        { price: 50000, volume: 0, buyVolume: 0, sellVolume: 0 },
      ];
      const config = generateProfileConfig(zeroProfile, mockPriceToY, defaultOptions);
      expect(config.bars).toHaveLength(0);
    });

    it('skips bars with invalid Y coordinates', () => {
      const invalidPriceToY = (price: number) => price === 50000 ? null : 500;
      const config = generateProfileConfig(sampleProfile, invalidPriceToY, defaultOptions);
      expect(config.bars.length).toBeLessThan(5);
    });
  });

  describe('validateProfileData', () => {
    it('returns empty array for valid profile', () => {
      const errors = validateProfileData(sampleProfile);
      expect(errors).toHaveLength(0);
    });

    it('detects missing price', () => {
      const invalidProfile: any = [{ volume: 100, buyVolume: 50, sellVolume: 50 }];
      const errors = validateProfileData(invalidProfile);
      expect(errors.length).toBeGreaterThan(0);
    });

    it('detects negative volume', () => {
      const invalidProfile: ProfileLevel[] = [
        { price: 50000, volume: -100, buyVolume: 50, sellVolume: 50 },
      ];
      const errors = validateProfileData(invalidProfile);
      expect(errors).toContain('Profile level 0: Negative volume');
    });

    it('detects unsorted prices', () => {
      const unsortedProfile: ProfileLevel[] = [
        { price: 50100, volume: 100, buyVolume: 50, sellVolume: 50 },
        { price: 50000, volume: 100, buyVolume: 50, sellVolume: 50 },
      ];
      const errors = validateProfileData(unsortedProfile);
      expect(errors.length).toBeGreaterThan(0);
    });

    it('allows empty profile', () => {
      const errors = validateProfileData([]);
      expect(errors).toHaveLength(0);
    });
  });

  describe('getProfileStats', () => {
    it('calculates total volume', () => {
      const stats = getProfileStats(sampleProfile);
      expect(stats?.totalVolume).toBe(1250);
    });

    it('calculates average volume', () => {
      const stats = getProfileStats(sampleProfile);
      expect(stats?.averageVolume).toBe(250);
    });

    it('calculates buy/sell volumes', () => {
      const stats = getProfileStats(sampleProfile);
      expect(stats?.totalBuyVolume).toBe(700);
      expect(stats?.totalSellVolume).toBe(550);
    });

    it('calculates buy/sell ratio', () => {
      const stats = getProfileStats(sampleProfile);
      expect(stats?.buySellRatio).toBeGreaterThan(1); // 700/550 ≈ 1.27
    });

    it('returns null for empty profile', () => {
      const stats = getProfileStats([]);
      expect(stats).toBeNull();
    });
  });
});
