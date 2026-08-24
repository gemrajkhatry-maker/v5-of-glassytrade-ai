/**
 * Drawing controller — the interaction and persistence layer over
 * `DrawingLayer`. It is **headless**: no DOM, no toolbar. A host sets the
 * active tool (from its own button, a shortcut, a command palette) and the
 * controller runs placement, selection, dragging, undo, and serialisation.
 *
 * It listens on the chart's event bus (`click`, `crosshair:move`, `drag`,
 * `drag:end`) rather than the single-slot `subscribeClick`/`subscribeDrag`
 * callbacks, so a host keeps using those for its own order lines.
 */
// Shared types come from the package entry, not a relative path: each tier
// bundles its own .d.ts, so a relative import gets *inlined* as a second
// declaration. Classes with private members are nominal, so that second copy
// is a different type — and a consumer passing the real one got "separate
// declarations of a private property". The entry is external to tier builds,
// so this survives as `from 'openalgo-charts'` and stays one identity.
import type { IPrimitive, DataLayer } from 'openalgo-charts';
import type { Drawing, DrawingPoint, DrawingStyle, DrawingTool } from './types';
import { DrawingLayer } from './layer';
import { getDrawingTool, hasDrawingTool } from './tools';
import { DrawingClipboard, type ClipboardPort } from './clipboard';

/**
 * The slice of the chart this controller needs.
 *
 * Declared structurally rather than as `Chart` on purpose. Each tier ships its
 * own bundled `.d.ts`, so naming the class here made the draw tier re-declare
 * `Chart` — and because `Chart` has private members, TypeScript treats the two
 * declarations as *different* types. A TS consumer passing the chart from
 * `createChart()` got "separate declarations of a private property", which made
 * the tier unusable from TypeScript at all. An interface with no private
 * members is structural, so the real `Chart` satisfies it with nothing to cast.
 */
export interface DrawingChartHost {
  on(event: string, handler: (payload: unknown) => void): () => void;
  emit(event: string, payload: unknown): void;
  addPrimitive(primitive: IPrimitive, paneIndex?: number): void;
  removePrimitive(primitive: IPrimitive): void;
  readonly dataLayer: DataLayer;
  getVisibleLogicalRange(): { from: number; to: number } | null;
  drawingState(): unknown;
  setDrawingState(state: unknown): void;
  setPlacementMode?(active: boolean): void;
  /**
   * Optional, and used only to offset a paste by a fixed screen distance. Going
   * through pixels rather than adding a price delta keeps the offset the same
   * visible nudge on a log scale as on a linear one. A host without them still
   * gets the time half of the offset.
   */
  priceToCoordinate?(price: number, paneIndex?: number): number | null;
  coordinateToPrice?(y: number, paneIndex?: number): number | null;
  /**
   * Optional, and used only to keep a paste from a chart with more panes than
   * this one landing on a pane the user cannot see. Adding a primitive creates
   * the pane it names, so without this a drawing copied out of an indicator
   * pane would conjure an empty pane in a single-pane chart.
   */
  panes?(): readonly unknown[];
}

export interface DrawingControllerOptions {
  /**
   * Snap new anchors to the nearest O/H/L/C of the bar under the cursor.
   * Default false.
   */
  magnet?: boolean;
  /** Style merged under every tool's own defaults. */
  defaultStyle?: DrawingStyle;
  /** Stay in the active tool after finishing a drawing. Default false. */
  stayInDrawingMode?: boolean;
  /** Undo depth. Default 50. */
  historyLimit?: number;
  /**
   * Where copy and paste move text. Defaults to `navigator.clipboard`; pass a
   * port to route through a host's own transfer, or `null` to stay in the
   * process-local clipboard entirely.
   */
  clipboard?: ClipboardPort | null;
  /**
   * Whether a refused or failing clipboard write still lands in the in-process
   * clipboard. Defaults to true, which is what makes copy and paste work between
   * two charts on a page where the browser has denied clipboard permission.
   *
   * Pass false for a host that would rather a failed copy be a failed copy: with
   * it off, `cut` leaves the drawing alone when the write does not land, so a
   * shape is never destroyed for a transfer that did not happen.
   */
  clipboardFallbackToMemory?: boolean;
  /**
   * How far a pasted copy lands from its original, in bars along time and in
   * screen pixels down the price axis. A paste that lands exactly on top of the
   * original reads as nothing having happened. Defaults: 2 bars, 16 px.
   */
  pasteOffsetBars?: number;
  pasteOffsetPixels?: number;
}

interface ClickPayload {
  id: string | null;
  time: number;
  price: number | null;
  paneIndex: number;
  point: { x: number; y: number };
  /** Set on the release half of a press-drag-release gesture. */
  viaDrag?: boolean;
}

interface DragPayload {
  id: string;
  price: number;
  time: number;
  paneIndex: number;
  /** Where the gesture was grabbed; deltas measure from here, not frame one. */
  fromPrice?: number;
  fromTime?: number;
}

let nextId = 1;

export class DrawingController {
  private readonly _chart: DrawingChartHost;
  private _opts: Required<Omit<DrawingControllerOptions, 'defaultStyle' | 'clipboard' | 'clipboardFallbackToMemory'>> & { defaultStyle: DrawingStyle };
  private readonly _clipboard: DrawingClipboard;
  private readonly _layers = new Map<number, DrawingLayer>();
  private _drawings: Drawing[] = [];
  private _tool: string | null = null;
  private _pending: DrawingPoint[] = [];
  private _pendingPane = 0;
  private _selected: string | null = null;
  /** Snapshots for undo/redo; each is a full drawing list (they are small). */
  private _undo: string[] = [];
  private _redo: string[] = [];
  private _dragStart: { id: string; handle: number | null; points: DrawingPoint[]; from: DrawingPoint } | null = null;
  private readonly _off: (() => void)[] = [];
  private _lastCursor: { time: number; price: number; paneIndex: number } | null = null;
  /** Bar under the cursor, carried by the crosshair event — used by magnet. */
  private _lastBar: { open: number; high: number; low: number; close: number } | null = null;

  public constructor(chart: DrawingChartHost, options: DrawingControllerOptions = {}) {
    this._chart = chart;
    this._opts = {
      magnet: options.magnet ?? false,
      stayInDrawingMode: options.stayInDrawingMode ?? false,
      historyLimit: options.historyLimit ?? 50,
      pasteOffsetBars: options.pasteOffsetBars ?? 2,
      pasteOffsetPixels: options.pasteOffsetPixels ?? 16,
      defaultStyle: options.defaultStyle ?? {},
    };
    this._clipboard = new DrawingClipboard({
      ...(options.clipboard === undefined ? {} : { port: options.clipboard }),
      ...(options.clipboardFallbackToMemory === undefined
        ? {}
        : { fallbackToMemory: options.clipboardFallbackToMemory }),
    });
    this._off.push(chart.on('click', (p) => this._onClick(p as ClickPayload)));
    this._off.push(chart.on('crosshair:move', (p) => this._onCrosshair(p as Record<string, unknown>)));
    this._off.push(chart.on('drag', (p) => this._onDrag(p as DragPayload)));
    this._off.push(chart.on('drag:end', () => this._onDragEnd()));
    this._off.push(chart.on('dblclick', () => { this.finish(); }));
    // Restore anything a previous session left in the chart state.
    const saved = chart.drawingState();
    if (Array.isArray(saved)) this._drawings = (saved as Drawing[]).map((d) => ({ ...d }));
    this._sync();
  }

  // ── public API ──────────────────────────────────────────────────────────

  /** Arm a tool for placement, or pass null to return to the cursor. */
  public setTool(toolId: string | null): void {
    if (toolId !== null && !hasDrawingTool(toolId)) {
      throw new Error(`openalgo-charts: unknown drawing tool "${toolId}"`);
    }
    this._tool = toolId;
    this._pending = [];
    this._setPlacementMode(toolId !== null);
    this._syncPreview();
    this._chart.emit('draw:tool', { tool: toolId });
  }

  /**
   * Ask the chart to stop panning and report gestures as anchor placement.
   * Guarded so a base bundle predating `setPlacementMode` still loads the tier.
   */
  private _setPlacementMode(active: boolean): void {
    const chart = this._chart as unknown as { setPlacementMode?: (a: boolean) => void };
    chart.setPlacementMode?.(active);
  }

  public activeTool(): string | null {
    return this._tool;
  }

  public setOptions(patch: DrawingControllerOptions): void {
    // `clipboard` is a port, not a stored option: it is applied to the live
    // clipboard so a host can hand one over after the user grants permission.
    const { clipboard, ...rest } = patch;
    this._opts = { ...this._opts, ...rest, defaultStyle: patch.defaultStyle ?? this._opts.defaultStyle };
    if (clipboard !== undefined) this._clipboard.setPort(clipboard);
  }

  /** The clipboard behind copy / cut / paste, for a host reporting failures. */
  public clipboard(): DrawingClipboard {
    return this._clipboard;
  }

  /** Every drawing, in creation order. */
  public drawings(): readonly Drawing[] {
    return this._drawings;
  }

  public get(id: string): Drawing | undefined {
    return this._drawings.find((d) => d.id === id);
  }

  /** Add a fully-specified drawing (import, or a host-authored one). */
  public add(drawing: Omit<Drawing, 'id'> & { id?: string }): Drawing {
    this._pushUndo();
    const created = this._insert(drawing);
    this._sync();
    this._chart.emit('draw:add', { drawing: created });
    return created;
  }

  /**
   * Append one drawing without touching history or the layers. Split out so a
   * paste of several drawings is a single undo step rather than one per shape.
   */
  private _insert(drawing: Omit<Drawing, 'id'> & { id?: string }): Drawing {
    const tool = getDrawingTool(drawing.tool);
    const created: Drawing = {
      ...drawing,
      id: drawing.id ?? `d${nextId++}`,
      style: { ...this._opts.defaultStyle, ...tool.defaultStyle, ...drawing.style },
    };
    this._drawings.push(created);
    return created;
  }

  public update(id: string, patch: Partial<Pick<Drawing, 'points' | 'style' | 'locked' | 'visible'>>): boolean {
    const d = this.get(id);
    if (d === undefined) return false;
    this._pushUndo();
    if (patch.points !== undefined) d.points = patch.points.map((p) => ({ ...p }));
    if (patch.style !== undefined) d.style = { ...d.style, ...patch.style };
    if (patch.locked !== undefined) d.locked = patch.locked;
    if (patch.visible !== undefined) d.visible = patch.visible;
    this._sync();
    this._chart.emit('draw:update', { drawing: d });
    return true;
  }

  public remove(id: string): boolean {
    const i = this._drawings.findIndex((d) => d.id === id);
    if (i < 0) return false;
    this._pushUndo();
    const [removed] = this._drawings.splice(i, 1);
    if (this._selected === id) this._selected = null;
    this._sync();
    this._chart.emit('draw:remove', { drawing: removed });
    return true;
  }

  public clear(): void {
    if (this._drawings.length === 0) return;
    this._pushUndo();
    this._drawings = [];
    this._selected = null;
    this._sync();
  }

  public select(id: string | null): void {
    this._selected = id;
    for (const layer of this._layers.values()) layer.setSelected(id);
    this._chart.emit('draw:select', { id });
  }

  public selected(): string | null {
    return this._selected;
  }

  // ── clipboard ───────────────────────────────────────────────────────────
  //
  // Async because the OS clipboard is: `navigator.clipboard` returns promises
  // and can reject on a permission the user has not granted. The host owns the
  // key bindings (the engine installs no listeners), so these are plain calls.

  /**
   * Put drawings on the clipboard. Defaults to the selection; pass an id or a
   * list of ids to copy something else. Resolves false when there was nothing
   * to copy, or when the payload could not be stored anywhere.
   */
  public async copy(target?: string | string[] | null): Promise<boolean> {
    const list = this._targets(target);
    if (list.length === 0) return false;
    const ok = await this._clipboard.write(list);
    if (ok) {
      this._chart.emit('draw:copy', {
        drawings: list.map((d) => ({ ...d, points: d.points.map((p) => ({ ...p })), style: { ...d.style } })),
      });
    }
    return ok;
  }

  /**
   * Copy, then delete. The delete happens **only** after the clipboard write
   * resolves successfully, so a refused write leaves the model exactly as it
   * was rather than destroying a drawing that went nowhere.
   */
  public async cut(target?: string | string[] | null): Promise<boolean> {
    const list = this._targets(target);
    if (list.length === 0) return false;
    const ok = await this._clipboard.write(list);
    if (!ok) return false;
    // One undo step for the whole cut, and the drawings are re-read here
    // because the await above gave other code a chance to change the model.
    const ids = new Set(list.map((d) => d.id));
    const removed = this._drawings.filter((d) => ids.has(d.id));
    if (removed.length === 0) return false;
    this._pushUndo();
    this._drawings = this._drawings.filter((d) => !ids.has(d.id));
    if (this._selected !== null && ids.has(this._selected)) this._selected = null;
    this._sync();
    for (const d of removed) this._chart.emit('draw:remove', { drawing: d });
    this._chart.emit('draw:cut', { drawings: removed });
    return true;
  }

  /**
   * Paste whatever is on the clipboard into this chart, offset from the
   * original so the copy is visibly a second object. Each pasted drawing is a
   * fresh object with a fresh id, never a second reference to the one copied,
   * so editing the paste cannot alter its source (or the clipboard).
   *
   * Anything that is not our payload (foreign text, a truncated or hand-edited
   * copy, a newer format) pastes nothing and resolves to an empty array: a
   * paste shortcut must not throw at the host because the user last copied a
   * spreadsheet cell.
   */
  public async paste(): Promise<Drawing[]> {
    const entries = await this._clipboard.read();
    if (entries === null || entries.length === 0) return [];
    // Everything is prepared before the model is touched: a tool that has since
    // been unregistered would throw inside `_insert` and leave a half-applied
    // paste plus an undo entry describing a state that never existed.
    for (const e of entries) {
      if (!hasDrawingTool(e.tool)) return [];
    }
    const prepared = entries.map((e) => {
      const paneIndex = this._clampPane(e.paneIndex);
      return { ...e, paneIndex, points: this._offsetPoints(e.points, paneIndex) };
    });
    this._pushUndo();
    const created = prepared.map((p) => this._insert(p));
    this._sync();
    for (const d of created) this._chart.emit('draw:add', { drawing: d });
    this._chart.emit('draw:paste', { drawings: created });
    this.select(created[created.length - 1].id);
    return created;
  }

  /** Resolve a copy/cut target to live drawings; defaults to the selection. */
  private _targets(target?: string | string[] | null): Drawing[] {
    if (target === undefined || target === null) {
      const sel = this._selected === null ? undefined : this.get(this._selected);
      return sel === undefined ? [] : [sel];
    }
    const ids = typeof target === 'string' ? [target] : target;
    const out: Drawing[] = [];
    for (const id of ids) {
      const d = this.get(id);
      if (d !== undefined) out.push(d);
    }
    return out;
  }

  /** Fold a pane index from another chart onto a pane this one actually has. */
  private _clampPane(paneIndex: number): number {
    const panes = this._chart.panes;
    if (panes === undefined) return paneIndex;
    const n = panes.call(this._chart).length;
    return n === 0 ? 0 : Math.min(paneIndex, n - 1);
  }

  /** Nudge every anchor so a pasted copy is not hidden under its original. */
  private _offsetPoints(points: readonly DrawingPoint[], paneIndex: number): DrawingPoint[] {
    const dt = this._barSeconds() * this._opts.pasteOffsetBars;
    const px = this._opts.pasteOffsetPixels;
    return points.map((p) => ({ time: p.time + dt, price: this._offsetPrice(p.price, paneIndex, px) }));
  }

  /**
   * Move a price down the screen by `px`. Done per anchor rather than as one
   * price delta so the paste is a rigid *screen* translation, which is what the
   * eye expects and what keeps a shape's proportions on a log scale.
   */
  private _offsetPrice(price: number, paneIndex: number, px: number): number {
    if (px === 0) return price;
    const toY = this._chart.priceToCoordinate;
    const toPrice = this._chart.coordinateToPrice;
    if (toY === undefined || toPrice === undefined) return price;   // time offset only
    const y = toY.call(this._chart, price, paneIndex);
    if (y === null || !Number.isFinite(y)) return price;
    const moved = toPrice.call(this._chart, y + px, paneIndex);
    if (moved === null || !Number.isFinite(moved)) return price;
    return moved;
  }

  public undo(): boolean {
    const snap = this._undo.pop();
    if (snap === undefined) return false;
    this._redo.push(JSON.stringify(this._drawings));
    this._drawings = JSON.parse(snap) as Drawing[];
    if (!this._drawings.some((d) => d.id === this._selected)) this._selected = null;
    this._sync();
    return true;
  }

  public redo(): boolean {
    const snap = this._redo.pop();
    if (snap === undefined) return false;
    this._undo.push(JSON.stringify(this._drawings));
    this._drawings = JSON.parse(snap) as Drawing[];
    this._sync();
    return true;
  }

  public canUndo(): boolean { return this._undo.length > 0; }
  public canRedo(): boolean { return this._redo.length > 0; }

  /** Serialisable payload — the same shape `ChartState.drawings` carries. */
  public toJSON(): Drawing[] {
    return this._drawings.map((d) => ({ ...d, points: d.points.map((p) => ({ ...p })), style: { ...d.style } }));
  }

  public fromJSON(data: unknown): void {
    this._drawings = Array.isArray(data) ? (data as Drawing[]).map((d) => ({ ...d })) : [];
    this._selected = null;
    this._undo = [];
    this._redo = [];
    this._sync();
  }

  public destroy(): void {
    this._setPlacementMode(false);   // never leave the chart unable to pan
    for (const off of this._off) off();
    this._off.length = 0;
    for (const [pane, layer] of this._layers) {
      void pane;
      this._chart.removePrimitive(layer);
    }
    this._layers.clear();
  }

  // ── interaction ─────────────────────────────────────────────────────────

  private _onCrosshair(p: Record<string, unknown>): void {
    const time = p.time as number | null;
    const price = p.price as number | null;
    const paneIndex = (p.paneIndex as number | null) ?? null;
    this._lastCursor = time === null || price === null || paneIndex === null
      ? null : { time, price, paneIndex };
    this._lastBar = (p.bar as { open: number; high: number; low: number; close: number } | null) ?? null;
    // Freehand tools ink while the pointer is held rather than on clicks.
    if (this._tool !== null && p.pressed === true && this._isFreehand()
      && time !== null && price !== null && paneIndex !== null
      && Number.isFinite(time) && Number.isFinite(price)) {
      this._inkPoint({ time, price }, paneIndex);
      return;
    }
    // A tool mid-placement previews against the live cursor.
    if (this._tool !== null && this._pending.length > 0) this._syncPreview();
  }

  /**
   * Let a tool turn the clicked anchors into its full set (the position tools
   * build a 1:1 box off one click). Identity for tools without the hook.
   */
  private _expand(tool: DrawingTool, clicked: DrawingPoint[]): DrawingPoint[] {
    if (tool.expand === undefined) return clicked;
    const range = this._chart.getVisibleLogicalRange();
    const visibleBars = range === null ? 60 : Math.max(1, range.to - range.from);
    return tool.expand(clicked, { barSeconds: this._barSeconds(), visibleBars });
  }

  /**
   * Bar spacing in seconds, read from the last gap in the data. A one-bar chart
   * has no gap to read, so fall back to a minute rather than answering zero and
   * producing zero-width defaults and invisible paste offsets.
   */
  private _barSeconds(): number {
    const dl = this._chart.dataLayer;
    const n = dl.baseIndex;
    const a = n > 0 ? dl.indexToTime(n - 1) : undefined;
    const b = n >= 0 ? dl.indexToTime(n) : undefined;
    return a !== undefined && b !== undefined && b > a ? b - a : 60;
  }

  private _isFreehand(): boolean {
    return this._tool !== null && getDrawingTool(this._tool).freehand === true;
  }

  /**
   * Append one sample to the stroke in progress. Points arriving closer than a
   * bar-eighth apart in time carry no shape and would bloat the saved drawing,
   * so they collapse into the last one — a pointer can fire far faster than the
   * stroke actually changes direction.
   */
  private _inkPoint(point: DrawingPoint, paneIndex: number): void {
    if (this._pending.length === 0) {
      this._pendingPane = paneIndex;
    } else if (paneIndex !== this._pendingPane) {
      return;                       // a stroke belongs to the pane it started in
    } else {
      const last = this._pending[this._pending.length - 1];
      if (last.time === point.time && last.price === point.price) return;
    }
    this._pending.push(point);
    this._syncPreview();
  }

  /** Commit `pts` as a drawing of the armed tool and leave placement. */
  private _commit(pts: DrawingPoint[]): void {
    const tool = getDrawingTool(this._tool as string);
    const created = this.add({ tool: tool.id, points: pts, style: {}, paneIndex: this._pendingPane });
    this._pending = [];
    if (!this._opts.stayInDrawingMode) {
      this._tool = null;
      this._setPlacementMode(false);   // hand panning back to the chart
    }
    this._syncPreview();
    this.select(created.id);
    this._chart.emit('draw:tool', { tool: this._tool });
  }

  /** Commit the stroke a freehand gesture built, if it has any extent. */
  private _finishFreehand(): void {
    const pts = this._pending;
    this._pending = [];
    if (pts.length < 2) {           // a tap is not a stroke
      this._syncPreview();
      return;
    }
    this._commit(pts);
  }

  /**
   * End a variable-anchor shape (polyline, path) at the anchors placed so far.
   * Those tools declare `points: 0`, so nothing else can ever complete them —
   * without this they collected vertices forever. Bound to double-click, and
   * public so a host can offer Esc / Enter too. No-op when there is nothing
   * placeable, so a stray double-click costs nothing.
   */
  public finish(): boolean {
    if (this._tool === null || this._pending.length === 0) return false;
    const tool = getDrawingTool(this._tool);
    if (tool.points !== 0 || tool.freehand === true) return false;
    const pts = this._pending;
    if (pts.length < 2) {           // a single vertex is not a shape
      this._pending = [];
      this._syncPreview();
      return false;
    }
    this._commit(pts);
    return true;
  }

  private _onClick(p: ClickPayload): void {
    // Placement takes precedence: while a tool is armed, a click is an anchor.
    if (this._tool !== null) {
      // A freehand stroke was already collected move-by-move; the click pair a
      // drag produces is its end signal, not two more anchors.
      if (this._isFreehand()) {
        if (p.viaDrag === true) this._finishFreehand();
        return;
      }
      // The release half of a drag only means something while a shape is part
      // way through. A single-anchor tool (text, horizontal line) is already
      // finished by the press, so treating the release as another anchor would
      // drop a second drawing wherever the user let go.
      if (p.viaDrag === true && this._pending.length === 0) return;
      // Reject an unmappable click outright — a NaN anchor serialises as null
      // and produces a drawing that can never be rendered or hit-tested.
      if (p.price === null || !Number.isFinite(p.price) || !Number.isFinite(p.time)) return;
      this._placePoint({ time: p.time, price: this._snap(p.price, p.paneIndex) }, p.paneIndex);
      return;
    }
    if (p.id !== null && p.id.startsWith('draw:')) {
      this.select(p.id.slice('draw:'.length).split('#')[0]);
      return;
    }
    if (p.id === null) this.select(null); // click on empty space clears
  }

  private _placePoint(point: DrawingPoint, paneIndex: number): void {
    if (this._pending.length === 0) this._pendingPane = paneIndex;
    this._pending.push(point);
    const tool = getDrawingTool(this._tool as string);
    if (tool.points > 0 && this._pending.length >= tool.points) {
      this._commit(this._expand(tool, this._pending));
    } else {
      this._syncPreview();
    }
  }

  /** Snap to the nearest O/H/L/C of the hovered bar when magnet is on. */
  private _snap(price: number, paneIndex: number): number {
    if (!this._opts.magnet || paneIndex !== 0) return price;
    const bar = this._lastBar;
    if (bar === null) return price;
    let best = price;
    let bestD = Infinity;
    for (const v of [bar.open, bar.high, bar.low, bar.close]) {
      const d = Math.abs(v - price);
      if (d < bestD) { bestD = d; best = v; }
    }
    return best;
  }

  private _onDrag(p: DragPayload): void {
    if (!p.id.startsWith('draw:')) return;
    const [rawId, handleStr] = p.id.slice('draw:'.length).split('#');
    const d = this.get(rawId);
    if (d === undefined || d.locked === true) return;
    const handle = handleStr === undefined ? null : Number(handleStr);

    if (this._dragStart === null || this._dragStart.id !== rawId || this._dragStart.handle !== handle) {
      // Snapshot once per gesture so undo restores the pre-drag position, not
      // an intermediate frame.
      this._pushUndo();
      this._dragStart = {
        id: rawId, handle,
        points: d.points.map((q) => ({ ...q })),
        from: {
          time: p.fromTime ?? p.time,
          price: p.fromPrice ?? p.price,
        },
      };
    }
    const start = this._dragStart;
    if (handle === null) {
      // Whole shape: translate every anchor by the cursor delta.
      const dt = p.time - start.from.time;
      const dp = p.price - start.from.price;
      d.points = start.points.map((q) => ({ time: q.time + dt, price: q.price + dp }));
    } else if (handle >= 0 && handle < d.points.length) {
      d.points = start.points.map((q, i) => (i === handle ? { time: p.time, price: p.price } : { ...q }));
    }
    this._sync();
  }

  private _onDragEnd(): void {
    if (this._dragStart === null) return;
    const d = this.get(this._dragStart.id);
    this._dragStart = null;
    if (d !== undefined) this._chart.emit('draw:update', { drawing: d });
  }

  // ── plumbing ────────────────────────────────────────────────────────────

  private _layerFor(paneIndex: number): DrawingLayer {
    let layer = this._layers.get(paneIndex);
    if (layer === undefined) {
      layer = new DrawingLayer();
      this._chart.addPrimitive(layer, paneIndex);
      this._layers.set(paneIndex, layer);
    }
    return layer;
  }

  /** Push the current list into each pane's layer and into the chart state. */
  private _sync(): void {
    const byPane = new Map<number, Drawing[]>();
    for (const d of this._drawings) {
      const list = byPane.get(d.paneIndex) ?? [];
      list.push(d);
      byPane.set(d.paneIndex, list);
    }
    for (const [pane, list] of byPane) this._layerFor(pane).setDrawings(list);
    // Panes that lost their last drawing must be cleared, not left stale.
    for (const [pane, layer] of this._layers) {
      if (!byPane.has(pane)) layer.setDrawings([]);
      layer.setSelected(this._selected);
    }
    this._chart.setDrawingState(this.toJSON());
  }

  /** Mirror the in-progress anchors (plus the cursor) into the preview slot. */
  private _syncPreview(): void {
    for (const layer of this._layers.values()) layer.setPreview(null);
    if (this._tool === null || this._pending.length === 0) return;
    const cursor = this._lastCursor;
    const points = cursor === null
      ? this._pending
      : [...this._pending, { time: cursor.time, price: cursor.price }];
    this._layerFor(this._pendingPane).setPreview({
      id: '__preview', tool: this._tool, points, style: this._opts.defaultStyle, paneIndex: this._pendingPane,
    });
  }

  private _pushUndo(): void {
    this._undo.push(JSON.stringify(this._drawings));
    if (this._undo.length > this._opts.historyLimit) this._undo.shift();
    this._redo = []; // a new edit invalidates the redo branch
  }
}
