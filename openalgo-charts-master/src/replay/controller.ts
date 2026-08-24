/**
 * Market replay: walk a historical session forward bar by bar so a trader can
 * practise on it, and so every indicator redraws exactly as it stood at that
 * past moment.
 *
 * Headless, in the spirit of `DrawingController` (src/draw/controller.ts): it
 * owns the playhead and the transitions and ships no DOM, so the host renders
 * its own transport bar, scrub slider and clock from `state()` and the events.
 *
 * The mechanic is deliberately boring. Replay feeds the chart a **prefix** of
 * the full bar array through the ordinary `series.setData` path, and that is
 * what makes indicators free: `Chart._setData` calls `_recomputeIndicators` for
 * the primary series, and `IndicatorInstance.recompute` re-reads the whole
 * history from `sourceBars()`. Shorten that history and every indicator, level,
 * fill, marker and legend reconstructs itself as it was at that bar, with no
 * replay-aware code anywhere in the indicator tier.
 */
import type { Bar } from '../model/bar';
import type { SeriesApi } from '../model/series';
import { clamp } from '../helpers/math';

/** Schedules a repeating callback and returns its canceller. Inject in tests. */
export type ReplayScheduler = (cb: () => void, intervalMs: number) => () => void;

const defaultScheduler: ReplayScheduler = (cb, ms) => {
  const id = setInterval(cb, ms);
  return () => clearInterval(id);
};

/**
 * Most bars a single timer tick may consume. A backgrounded tab throttles its
 * timers to about one call a second, so without a ceiling the first tick after
 * the user comes back would fast-forward minutes of the session in one frame.
 */
const CATCH_UP_LIMIT = 10;

/**
 * The slice of the time scale replay saves and restores. Declared structurally
 * rather than as `TimeScale` so nothing here depends on the scale's shape
 * beyond the two numbers that *are* the viewport.
 */
export interface ReplayViewport {
  readonly barSpacing: number;
  readonly rightOffset: number;
  setBarSpacing(value: number): void;
  setRightOffset(value: number): void;
}

/**
 * The slice of the chart this controller needs. `Chart` satisfies it; declaring
 * it structurally keeps the controller testable against a stub and free of a
 * circular import back into core.
 */
export interface ReplayChartHost {
  emit(event: string, payload: unknown): void;
  readonly timeScale: ReplayViewport;
  /**
   * Optional. When the chart can name its own primary price series, `series`
   * may be omitted and replay drives that one.
   */
  primarySeries?(): SeriesApi | null;
}

/** Everything a transport bar and a clock need, in one object. */
export interface ReplayState {
  /** 0-based index of the newest bar currently on the chart. */
  index: number;
  /** Bars in the replay set (the scrub bar's maximum is `total - 1`). */
  total: number;
  playing: boolean;
  /** Multiplier over `barMs`: 2 plays two bars per `barMs`. */
  speed: number;
  /** The bar at `index`, the replay clock's "now". Null when there is no data. */
  bar: Bar | null;
}

export interface ReplayOptions {
  /**
   * The series replay drives. The first one owns the timeline; any others (a
   * volume histogram, a comparison line) are truncated to the same instant by
   * time, because the shared DataLayer merges *every* series onto one axis and
   * a series left at full length would drag future timestamps back onto it.
   *
   * Optional only if the host chart implements `primarySeries()`.
   */
  series?: SeriesApi | readonly SeriesApi[];
  /**
   * The full session. Defaults to the primary series' current data. Never
   * mutated, and never handed to the chart as-is: each frame gets its own slice.
   */
  bars?: readonly Bar[];
  /** Bar to open at (0-based). Default 0. */
  startIndex?: number;
  /** Wall-clock milliseconds per bar at speed 1. Default 1000. */
  barMs?: number;
  /** Initial speed multiplier. Default 1. */
  speed?: number;
  /** Called on every playhead move, after the chart has been updated. */
  onFrame?: (state: ReplayState) => void;
  /** Playback clock. Default `performance.now`. */
  now?: () => number;
  /** Playback timer. Default `setInterval`. */
  scheduler?: ReplayScheduler;
}

/** Index of the first bar with `time` greater than `cutoff`. */
function countUpTo(bars: readonly Bar[], cutoff: number): number {
  let lo = 0;
  let hi = bars.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (bars[mid].time <= cutoff) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export class ReplayController {
  private readonly _chart: ReplayChartHost;
  private readonly _series: readonly SeriesApi[];
  private readonly _bars: readonly Bar[];
  /** What each driven series held before replay took over, for `stop()`. */
  private readonly _restore: readonly Bar[][];
  private readonly _view: { barSpacing: number; rightOffset: number };
  private readonly _onFrame: ((state: ReplayState) => void) | null;
  private readonly _now: () => number;
  private readonly _schedule: ReplayScheduler;
  private readonly _barMs: number;
  private readonly _startIndex: number;
  private _speed: number;
  private _index: number;
  private _playing = false;
  /** True once replay owns the chart's data; false before start and after stop. */
  private _active = false;
  private _cancel: (() => void) | null = null;
  private _interval = 0;
  /** Clock reading the last advance was charged to; keeps playback drift-free. */
  private _lastAdvance = 0;

  /**
   * Constructing the controller **enters replay**: it snapshots the chart's data
   * and viewport and immediately shows `startIndex`. That is the gesture a
   * replay button makes, and it means the snapshot is taken before anything has
   * moved, so `stop()` can put the user back exactly where they were.
   */
  public constructor(chart: ReplayChartHost, options: ReplayOptions = {}) {
    this._chart = chart;
    const given = options.series;
    const list: SeriesApi[] = given === undefined
      ? []
      : 'setData' in given ? [given] : [...given];
    if (list.length === 0) {
      const primary = chart.primarySeries?.() ?? null;
      if (primary === null) {
        throw new Error('openalgo-charts: replay needs a series to drive (pass options.series)');
      }
      list.push(primary);
    }
    this._series = list;
    this._restore = list.map((s) => s.getData());
    this._bars = options.bars ?? this._restore[0];
    this._view = { barSpacing: chart.timeScale.barSpacing, rightOffset: chart.timeScale.rightOffset };
    this._startIndex = clamp(Math.floor(options.startIndex ?? 0), 0, Math.max(0, this._bars.length - 1));
    this._index = this._startIndex;
    const barMs = options.barMs ?? 1000;
    this._barMs = barMs > 0 ? barMs : 1000;
    const speed = options.speed ?? 1;
    this._speed = speed > 0 ? speed : 1;
    this._onFrame = options.onFrame ?? null;
    this._now = options.now ?? (() => (typeof performance !== 'undefined' ? performance.now() : 0));
    this._schedule = options.scheduler ?? defaultScheduler;
    this._apply(this._startIndex);
  }

  // ── transport ───────────────────────────────────────────────────────────

  /** Jump the playhead to a bar. Out-of-range values clamp to the session. */
  public seek(index: number): void {
    this._apply(index);
  }

  /** Move `n` bars forward. Stops dead at the last bar. */
  public step(n = 1): void {
    this._apply(this._index + n);
  }

  /** Move `n` bars back. Stops dead at the first bar. */
  public stepBack(n = 1): void {
    this._apply(this._index - n);
  }

  /**
   * Start (or re-speed) playback. Calling it on the last bar plays nothing and
   * reports `replay:end` instead of arming a timer that could never advance.
   */
  public play(options: { speed?: number } = {}): void {
    const speed = options.speed;
    if (speed !== undefined && speed > 0) this._speed = speed;
    if (this._bars.length === 0) return;
    this._apply(this._index); // a host may go straight to play() after stop()
    if (this._index >= this._bars.length - 1) {
      this._end();
      return;
    }
    this._stopTimer();
    this._interval = this._barMs / this._speed;
    this._lastAdvance = this._now();
    this._playing = true;
    this._cancel = this._schedule(this._tick, this._interval);
    this._chart.emit('replay:play', this.state());
  }

  /** Halt playback, leaving the playhead (and the chart) where it is. */
  public pause(): void {
    if (!this._playing) return;
    this._playing = false;
    this._stopTimer();
    this._chart.emit('replay:pause', this.state());
  }

  /**
   * Leave replay: every driven series gets its pre-replay data back and the
   * viewport is restored to the pixel, so a user who exits does not lose their
   * place. Safe to call twice; a later `seek`/`step`/`play` re-enters replay
   * from `startIndex`.
   */
  public stop(): void {
    this._playing = false;
    this._stopTimer();
    if (!this._active) return;
    this._active = false;
    this._index = this._startIndex;
    for (let i = 0; i < this._series.length; i++) this._series[i].setData(this._restore[i]);
    // Bar spacing and right offset *are* the viewport: the visible logical
    // range is (baseIndex + rightOffset) back by width / barSpacing, and
    // restoring the data restores baseIndex.
    const ts = this._chart.timeScale;
    ts.setBarSpacing(this._view.barSpacing);
    ts.setRightOffset(this._view.rightOffset);
    this._chart.emit('replay:stop', this.state());
  }

  public state(): ReplayState {
    const total = this._bars.length;
    return {
      index: this._index,
      total,
      playing: this._playing,
      speed: this._speed,
      bar: total === 0 ? null : this._bars[this._index],
    };
  }

  // ── plumbing ────────────────────────────────────────────────────────────

  /**
   * Put the chart at `index`. Every transition goes through here (seek, step
   * and each played frame alike), so arriving at a bar leaves the chart in the
   * same state however the user got there.
   */
  private _apply(index: number): void {
    const total = this._bars.length;
    if (total === 0) return;
    const next = clamp(Math.floor(index), 0, total - 1);
    if (this._active && next === this._index) return;
    const first = !this._active;
    this._active = true;
    this._index = next;
    this._series[0].setData(this._bars.slice(0, next + 1));
    // Followers cut by time, not by count: a volume series may be shorter than
    // the price series, or start later.
    const cutoff = this._bars[next].time;
    for (let i = 1; i < this._series.length; i++) {
      const snap = this._restore[i];
      this._series[i].setData(snap.slice(0, countUpTo(snap, cutoff)));
    }
    if (first) this._chart.emit('replay:start', this.state());
    const s = this.state();
    this._onFrame?.(s);
    this._chart.emit('replay:frame', s);
  }

  /**
   * One timer tick. The number of bars owed comes from the clock, not from the
   * tick count, so a coarse or throttled timer still plays at the requested
   * speed, and a host may drive this from rAF instead with no change here.
   */
  private readonly _tick = (): void => {
    if (!this._playing) return;
    const t = this._now();
    let due = Math.floor((t - this._lastAdvance) / this._interval);
    if (due <= 0) return;
    if (due > CATCH_UP_LIMIT) {
      due = CATCH_UP_LIMIT;
      this._lastAdvance = t; // drop the unplayable backlog rather than owing it forever
    } else {
      this._lastAdvance += due * this._interval;
    }
    this._apply(this._index + due);
    if (this._index >= this._bars.length - 1) this._end();
  };

  /** The session is over: stop the timer and tell the host once. */
  private _end(): void {
    this.pause();
    this._chart.emit('replay:end', this.state());
  }

  private _stopTimer(): void {
    this._cancel?.();
    this._cancel = null;
  }
}
