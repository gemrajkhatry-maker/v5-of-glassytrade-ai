import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  LineStyle,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import type { SeriesMarker, SeriesMarkerPosition } from "lightweight-charts";
import type { AMTDecision, AMTSnapshot, CandleBar } from "../types";

const COLORS = {
  vwap: "#f5c542",
  band1: "rgba(245, 197, 66, 0.55)",
  band2: "rgba(245, 197, 66, 0.28)",
  poc: "#ffffff",
  vah: "#4fc3f7",
  val: "#4fc3f7",
  hvn: "#ff8a65",
  lvn: "#b39ddb",
  ib: "#90a4ae",
  buy: "#26a69a",
  sell: "#ef5350",
  tripleA: "#7c4dff",
  pyramid: "#ffb300",
  vaFade: "#29b6f6",
};

function num(v: string | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function toTime(ts: string): Time {
  // Backend timestamps are ISO strings (or "2026-08-24 12:30:00" style).
  const iso = ts.includes("T") ? ts : ts.replace(" ", "T");
  const d = new Date(iso);
  const millis = Number.isNaN(d.getTime()) ? Date.parse(ts) : d.getTime();
  return (millis / 1000) as Time;
}

interface Props {
  bars: CandleBar[];
  snapshots: AMTSnapshot[];
  live: AMTSnapshot | null;
  decisions: AMTDecision[];
  instrument: string;
}

export default function AMTChart({
  bars,
  snapshots,
  live,
  decisions,
  instrument,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lineRefs = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const priceLineRefs = useRef<Map<string, ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>>>(new Map());
  const lastInstrument = useRef<string>(instrument);

  // --- chart lifecycle ------------------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: "#0d1117" },
        textColor: "#8b949e",
      },
      grid: {
        vertLines: { color: "rgba(110, 118, 129, 0.12)" },
        horzLines: { color: "rgba(110, 118, 129, 0.12)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(110, 118, 129, 0.3)" },
      timeScale: { borderColor: "rgba(110, 118, 129, 0.3)" },
    });

    const candles = chart.addCandlestickSeries({
      upColor: COLORS.buy,
      downColor: COLORS.sell,
      borderUpColor: COLORS.buy,
      borderDownColor: COLORS.sell,
      wickUpColor: COLORS.buy,
      wickDownColor: COLORS.sell,
    });
    candleRef.current = candles;
    chartRef.current = chart;

    const resize = new ResizeObserver(() => {
      if (!containerRef.current) return;
      chart.applyOptions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      });
    });
    resize.observe(containerRef.current);

    return () => {
      resize.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      lineRefs.current.clear();
      priceLineRefs.current.clear();
    };
  }, []);

  // --- candle data ----------------------------------------------------------
  useEffect(() => {
    const candles = candleRef.current;
    if (!candles) return;
    const data: CandlestickData[] = bars.map((b) => ({
      time: toTime(b.timestamp),
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    candles.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  // --- AMT overlay lines (VWAP / bands) -------------------------------------
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const seriesList = [
      { key: "vwap", color: COLORS.vwap, width: 2, dash: undefined },
      { key: "upper_1", color: COLORS.band1, width: 1, dash: LineStyle.Dotted },
      { key: "lower_1", color: COLORS.band1, width: 1, dash: LineStyle.Dotted },
      { key: "upper_2", color: COLORS.band2, width: 1, dash: LineStyle.Dotted },
      { key: "lower_2", color: COLORS.band2, width: 1, dash: LineStyle.Dotted },
    ] as const;

    // remove stale line series (instrument changed)
    for (const [key, series] of lineRefs.current) {
      if (!seriesList.some((s) => s.key === key)) {
        chart.removeSeries(series);
        lineRefs.current.delete(key);
      }
    }

    for (const { key, color, width, dash } of seriesList) {
      let series = lineRefs.current.get(key);
      if (!series) {
        series = chart.addLineSeries({
          color,
          lineWidth: width,
          lineStyle: dash,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        lineRefs.current.set(key, series);
      }
      const points = snapshots
        .map((s) => {
          const value = num(s[key as keyof AMTSnapshot] as string);
          return value === null
            ? null
            : { time: toTime(s.timestamp ?? ""), value };
        })
        .filter((p): p is { time: Time; value: number } => p !== null);
      series.setData(points);
    }
  }, [snapshots]);

  // --- price levels (POC / VAH / VAL / HVN / LVN / IB) ----------------------
  useEffect(() => {
    const candles = candleRef.current;
    if (!candles) return;

    // clear previous instrument's price lines
    for (const line of priceLineRefs.current.values()) candles.removePriceLine(line);
    priceLineRefs.current.clear();

    const live_ = live ?? snapshots[snapshots.length - 1] ?? null;
    if (!live_) return;

    const add = (key: string, value: string | null, color: string, title: string, style?: LineStyle) => {
      const p = num(value);
      if (p === null) return;
      const line = candles.createPriceLine({
        price: p,
        color,
        lineWidth: 1,
        lineStyle: style ?? LineStyle.Solid,
        axisLabelVisible: true,
        title,
      });
      priceLineRefs.current.set(key, line);
    };

    add("poc", live_.poc, COLORS.poc, "POC", LineStyle.Solid);
    add("vah", live_.vah, COLORS.vah, "VAH", LineStyle.Dashed);
    add("val", live_.val, COLORS.val, "VAL", LineStyle.Dashed);
    add("ib_high", live_.ib_high, COLORS.ib, "IB-H", LineStyle.SparseDotted);
    add("ib_low", live_.ib_low, COLORS.ib, "IB-L", LineStyle.SparseDotted);
    for (const [i, level] of live_.hvn_levels.entries()) {
      add(`hvn-${i}`, level, COLORS.hvn, "HVN");
    }
    for (const [i, level] of live_.lvn_levels.entries()) {
      add(`lvn-${i}`, level, COLORS.lvn, "LVN");
    }
  }, [live, snapshots]);

  // --- decision markers (triple-A / pyramid / VA-fade entries) ---------------
  useEffect(() => {
    const candles = candleRef.current;
    if (!candles) return;
    const markers: SeriesMarker<Time>[] = snapshots
      .filter((s) => s.absorption_side && s.absorption_side !== "NONE")
      .map((s) => ({
        time: toTime(s.timestamp ?? ""),
        position: (s.absorption_side === "BUY"
          ? "belowBar"
          : "aboveBar") as SeriesMarkerPosition,
        color: s.absorption_side === "BUY" ? COLORS.buy : COLORS.sell,
        shape: "arrowUp",
        text: `ABS ${s.absorption_strength}`,
      }));
    for (const d of decisions) {
      if (!d.approved || !d.timestamp) continue;
      const isLong = d.direction === "LONG";
      let shape: SeriesMarker<Time>["shape"] = "arrowUp";
      let color = COLORS.tripleA;
      let text = `${d.setup} @${d.entry ?? "?"}`;
      if (d.setup === "PYRAMID") {
        shape = "square";
        color = COLORS.pyramid;
        text = `PYRAMID ${isLong ? "L" : "S"} @${d.entry ?? "?"}`;
      } else if (d.setup === "VA_FADE") {
        shape = "circle";
        color = COLORS.vaFade;
        text = `VA_FADE ${isLong ? "L" : "S"} @${d.entry ?? "?"}`;
      } else if (d.setup === "TRIPLE_A") {
        shape = "arrowUp";
        color = COLORS.tripleA;
        text = `TRIPLE_A ${isLong ? "L" : "S"} @${d.entry ?? "?"}`;
      }
      markers.push({
        time: toTime(d.timestamp),
        position: (isLong ? "belowBar" : "aboveBar") as SeriesMarkerPosition,
        color,
        shape,
        text,
      });
    }
    candles.setMarkers(markers);
  }, [snapshots, decisions]);

  // reset on instrument switch
  useEffect(() => {
    if (lastInstrument.current !== instrument) {
      lastInstrument.current = instrument;
      candleRef.current?.setData([]);
    }
  }, [instrument]);

  return (
    <div className="chart-wrap">
      <div className="chart-head">
        <span className="chart-title">{instrument}</span>
        {live && (
          <span className={`phase-badge phase-${live.phase.toLowerCase()}`}>
            {live.phase}
          </span>
        )}
      </div>
      <div ref={containerRef} className="chart-canvas" />
    </div>
  );
}
