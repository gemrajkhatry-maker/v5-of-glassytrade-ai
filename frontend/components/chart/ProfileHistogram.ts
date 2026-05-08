/**
 * ProfileHistogram - Pure data transformation for volume profile rendering
 * 
 * Extracts calculation logic from canvas-based profile bar rendering:
 * - Bar dimension calculations (width, height, position)
 * - Zone classification (POC, HVN, LVN, Value Area)
 * - Color and alpha determination
 * - Value area background zone calculation
 * 
 * Benefits:
 * - 100% testable (pure functions)
 * - Separates calculation from rendering
 * - Easy to validate profile logic
 * - Reusable across different chart modes
 */

export interface ProfileLevel {
  price: number;
  volume: number;
  buyVolume: number;
  sellVolume: number;
}

export interface ProfileBarConfig {
  x: number;
  y: number;
  width: number;
  height: number;
  baseColor: string;
  baseAlpha: number;
  zoneType: 'poc' | 'hvn' | 'lvn' | 'valueArea' | 'normal';
  edgeWidth: number;
  edgeColor: string;
  edgeAlpha: number;
}

export interface ProfileConfig {
  bars: ProfileBarConfig[];
  valueAreaZone: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
  maxVolume: number;
  barWidthScale: number;
}

export interface ProfileRenderOptions {
  maxWidthPct: number;
  xOffset: number;
  canvasWidth: number;
  bullColor: string;
  bearColor: string;
  useDirectionColors: boolean;
  hvnPrices?: number[];
  lvnPrices?: number[];
  vahPrice?: number;
  valPrice?: number;
  pocPrice?: number;
}

/**
 * Calculate price tolerance for zone matching
 * 
 * @param profile - Profile levels
 * @returns Tolerance value for price comparisons
 */
export function calculatePriceTolerance(profile: ProfileLevel[]): number {
  if (profile.length <= 1) {
    return 1;
  }
  const step = Math.abs(profile[1].price - profile[0].price);
  return step > 0 ? step * 0.6 : 1;
}

/**
 * Check if price is near target prices (within tolerance)
 * 
 * @param price - Price to check
 * @param targets - Target prices
 * @param tolerance - Tolerance value
 * @returns true if price is near any target
 */
export function isPriceNearTarget(
  price: number,
  targets: number[] | undefined,
  tolerance: number
): boolean {
  if (!targets || targets.length === 0) {
    return false;
  }
  return targets.some(t => Math.abs(price - t) < tolerance);
}

/**
 * Check if price is within value area
 * 
 * @param price - Price to check
 * @param vahPrice - Value Area High
 * @param valPrice - Value Area Low
 * @returns true if price is in value area
 */
export function isInValueArea(
  price: number,
  vahPrice: number | undefined,
  valPrice: number | undefined
): boolean {
  if (vahPrice == null || valPrice == null) {
    return false;
  }
  return price >= valPrice && price <= vahPrice;
}

/**
 * Classify profile bar zone type
 * 
 * @param price - Bar price
 * @param options - Render options with zone prices
 * @param tolerance - Price tolerance
 * @returns Zone type classification
 */
export function classifyZoneType(
  price: number,
  options: ProfileRenderOptions,
  tolerance: number
): ProfileBarConfig['zoneType'] {
  const isPoc = options.pocPrice != null && Math.abs(price - options.pocPrice) < tolerance;
  const isHvn = isPriceNearTarget(price, options.hvnPrices, tolerance);
  const isLvn = isPriceNearTarget(price, options.lvnPrices, tolerance);
  const isVA = isInValueArea(price, options.vahPrice, options.valPrice);

  if (isPoc) return 'poc';
  if (isHvn) return 'hvn';
  if (isLvn) return 'lvn';
  if (isVA) return 'valueArea';
  return 'normal';
}

/**
 * Calculate bar color and alpha based on zone type
 * 
 * @param level - Profile level
 * @param zoneType - Classified zone type
 * @param options - Render options
 * @returns Color and alpha values
 */
export function calculateBarColor(
  level: ProfileLevel,
  zoneType: ProfileBarConfig['zoneType'],
  options: ProfileRenderOptions
): { baseColor: string; baseAlpha: number } {
  // Base color selection
  let baseColor: string;
  if (options.useDirectionColors) {
    const isBullish = level.buyVolume > level.sellVolume;
    baseColor = isBullish ? options.bullColor : options.bearColor;
  } else {
    baseColor = options.bullColor;
  }

  // Alpha based on zone type
  let baseAlpha: number;
  switch (zoneType) {
    case 'poc':
      baseAlpha = 0.85;
      break;
    case 'hvn':
      baseAlpha = 0.65;
      break;
    case 'lvn':
      baseAlpha = 0.18;
      break;
    case 'valueArea':
      baseAlpha = 0.45;
      break;
    default:
      baseAlpha = 0.30;
  }

  return { baseColor, baseAlpha };
}

/**
 * Calculate edge styling for profile bar
 * 
 * @param zoneType - Zone type
 * @param baseColor - Base bar color
 * @param baseAlpha - Base bar alpha
 * @returns Edge width, color, and alpha
 */
export function calculateEdgeStyle(
  zoneType: ProfileBarConfig['zoneType'],
  baseColor: string,
  baseAlpha: number
): { edgeWidth: number; edgeColor: string; edgeAlpha: number } {
  switch (zoneType) {
    case 'poc':
      return {
        edgeWidth: 2,
        edgeColor: '#facc15',
        edgeAlpha: 0.9,
      };
    case 'hvn':
      return {
        edgeWidth: 2,
        edgeColor: '#22c55e',
        edgeAlpha: 0.7,
      };
    case 'lvn':
      return {
        edgeWidth: 1,
        edgeColor: '#f97316',
        edgeAlpha: 0.5,
      };
    default:
      return {
        edgeWidth: 1,
        edgeColor: baseColor,
        edgeAlpha: baseAlpha * 0.8,
      };
  }
}

/**
 * Calculate single profile bar configuration
 * 
 * @param level - Profile level data
 * @param priceToY - Function to convert price to Y coordinate
 * @param options - Render options
 * @param tolerance - Price tolerance
 * @returns Bar configuration (or null if Y coordinate unavailable)
 */
export function calculateBarConfig(
  level: ProfileLevel,
  priceToY: (price: number) => number | null,
  options: ProfileRenderOptions,
  tolerance: number
): ProfileBarConfig | null {
  const y = priceToY(level.price);
  if (y === null) return null;

  // Calculate bar height
  const step = options.hvnPrices && options.hvnPrices.length > 1
    ? Math.abs(options.hvnPrices[1] - options.hvnPrices[0])
    : 0;

  let barHeight = 2;
  if (step > 0) {
    const topY = priceToY(level.price + (step / 2));
    const bottomY = priceToY(level.price - (step / 2));
    if (topY !== null && bottomY !== null) {
      barHeight = Math.max(1, Math.abs(bottomY - topY) + 0.5);
    }
  }

  // Calculate bar width and position
  const maxVolume = Math.max(...[level.volume]); // Will be replaced with actual max
  const maxBarWidth = options.canvasWidth * options.maxWidthPct;
  const widthScale = maxBarWidth / (maxVolume || 1);
  const barWidth = level.volume * widthScale;
  const rightEdge = options.canvasWidth - 50;
  const x = rightEdge - options.xOffset - barWidth;

  // Classify zone and calculate colors
  const zoneType = classifyZoneType(level.price, options, tolerance);
  const { baseColor, baseAlpha } = calculateBarColor(level, zoneType, options);
  const edgeStyle = calculateEdgeStyle(zoneType, baseColor, baseAlpha);

  return {
    x,
    y,
    width: barWidth,
    height: barHeight,
    baseColor,
    baseAlpha,
    zoneType,
    ...edgeStyle,
  };
}

/**
 * Generate complete profile configuration for all bars
 * 
 * @param profile - Profile level data
 * @param priceToY - Function to convert price to Y coordinate
 * @param options - Render options
 * @returns Complete profile configuration
 */
export function generateProfileConfig(
  profile: ProfileLevel[],
  priceToY: (price: number) => number | null,
  options: ProfileRenderOptions
): ProfileConfig {
  if (!profile || profile.length === 0) {
    return { bars: [], valueAreaZone: null, maxVolume: 0, barWidthScale: 0 };
  }

  const maxVolume = Math.max(...profile.map(p => p.volume));
  if (maxVolume === 0) {
    return { bars: [], valueAreaZone: null, maxVolume: 0, barWidthScale: 0 };
  }

  const maxBarWidth = options.canvasWidth * options.maxWidthPct;
  const widthScale = maxBarWidth / maxVolume;
  const tolerance = calculatePriceTolerance(profile);
  const rightEdge = options.canvasWidth - 50;

  // Calculate value area background zone
  let valueAreaZone: ProfileConfig['valueAreaZone'] = null;
  if (options.vahPrice != null && options.valPrice != null) {
    const vahY = priceToY(options.vahPrice);
    const valY = priceToY(options.valPrice);
    if (vahY !== null && valY !== null) {
      valueAreaZone = {
        x: rightEdge - options.xOffset - maxBarWidth,
        y: Math.min(vahY, valY),
        width: maxBarWidth,
        height: Math.abs(valY - vahY),
      };
    }
  }

  // Calculate all bar configurations
  const bars: ProfileBarConfig[] = [];
  profile.forEach(level => {
    const barConfig = calculateBarConfig(level, priceToY, {
      ...options,
      canvasWidth: options.canvasWidth,
    }, tolerance);

    if (barConfig !== null) {
      // Override width calculation with correct maxVolume
      barConfig.width = level.volume * widthScale;
      barConfig.x = rightEdge - options.xOffset - barConfig.width;
      bars.push(barConfig);
    }
  });

  return {
    bars,
    valueAreaZone,
    maxVolume,
    barWidthScale: widthScale,
  };
}

/**
 * Validate profile data integrity
 * 
 * @param profile - Profile level data
 * @returns Array of validation errors (empty if valid)
 */
export function validateProfileData(profile: ProfileLevel[]): string[] {
  const errors: string[] = [];

  if (!profile || profile.length === 0) {
    return errors; // Empty is valid
  }

  profile.forEach((level, index) => {
    if (level.price === undefined || level.price === null) {
      errors.push(`Profile level ${index}: Missing price`);
    }
    if (level.volume === undefined || level.volume === null) {
      errors.push(`Profile level ${index}: Missing volume`);
    }
    if (level.volume < 0) {
      errors.push(`Profile level ${index}: Negative volume`);
    }
    if (level.buyVolume === undefined || level.buyVolume === null) {
      errors.push(`Profile level ${index}: Missing buyVolume`);
    }
    if (level.sellVolume === undefined || level.sellVolume === null) {
      errors.push(`Profile level ${index}: Missing sellVolume`);
    }
  });

  // Check for price sequence (should be sorted)
  for (let i = 1; i < profile.length; i++) {
    if (profile[i].price <= profile[i - 1].price) {
      errors.push(`Profile levels not sorted at index ${i}`);
      break;
    }
  }

  return errors;
}

/**
 * Get profile statistics
 * 
 * @param profile - Profile level data
 * @returns Statistical summary
 */
export function getProfileStats(profile: ProfileLevel[]) {
  if (!profile || profile.length === 0) {
    return null;
  }

  const volumes = profile.map(p => p.volume);
  const totalVolume = volumes.reduce((a, b) => a + b, 0);
  const totalBuyVolume = profile.reduce((a, b) => a + b.buyVolume, 0);
  const totalSellVolume = profile.reduce((a, b) => a + b.sellVolume, 0);

  return {
    levelCount: profile.length,
    totalVolume,
    averageVolume: totalVolume / profile.length,
    maxVolume: Math.max(...volumes),
    minVolume: Math.min(...volumes),
    totalBuyVolume,
    totalSellVolume,
    buySellRatio: totalSellVolume > 0 ? totalBuyVolume / totalSellVolume : 0,
  };
}
