/**
 * Clipboard transfer for drawings: the layer between the drawing model and the
 * OS clipboard.
 *
 * Two things make this more than `JSON.stringify`:
 *
 * 1. **The OS clipboard is shared with everything else on the machine.** A
 *    paste can arrive from a spreadsheet, another charting product, or a
 *    hand-edited copy of our own payload. So the payload is written under a
 *    namespaced key and everything read back is validated field by field before
 *    it can reach the model. Foreign text is *not ours* and is ignored, never an
 *    exception the host has to catch on every Ctrl+V.
 * 2. **Clipboard access is async and permission-gated.** `navigator.clipboard`
 *    rejects when the document is not focused, the page is not secure, or the
 *    user denied the permission. Copy must still work inside the tab, so every
 *    write also lands in a module-level in-memory clipboard which is shared by
 *    every controller in the page. That is what makes chart-to-chart paste work
 *    with the permission denied, and it is why the memory store is a singleton
 *    rather than per-controller state.
 */
import type { Drawing, DrawingPoint, DrawingStyle } from './types';
import { hasDrawingTool } from './tools';

/**
 * Top-level key of the JSON payload. Namespaced so a paste of arbitrary text,
 * or of JSON belonging to some other application, is recognisable as not ours
 * by looking at one property.
 */
export const DRAWING_CLIPBOARD_KEY = 'openalgo-charts/drawings';

/** Payload format version. Bumped only when the on-clipboard shape changes. */
export const DRAWING_CLIPBOARD_VERSION = 1;

/**
 * Caps applied to anything crossing the process boundary. They exist to keep a
 * hostile or corrupt payload from turning into a multi-megabyte model, not to
 * constrain honest use: the largest built-in tool is a freehand path, and a
 * stroke of 20k samples is already far past what a pointer can produce.
 */
const MAX_DRAWINGS = 512;
const MAX_POINTS = 20000;
const MAX_STYLE_KEYS = 64;
const MAX_STRING = 4096;
const MAX_ARRAY = 64;

/** The async slice of `navigator.clipboard` this module uses. */
export interface ClipboardPort {
  writeText(text: string): Promise<void>;
  readText(): Promise<string>;
}

/**
 * Process-wide fallback store. Shared deliberately: two charts in one page must
 * be able to exchange a drawing even when the OS clipboard is unavailable.
 */
let memoryText: string | null = null;

/** Test seam: drop whatever the in-memory clipboard is holding. */
export function clearMemoryClipboard(): void {
  memoryText = null;
}

/** `navigator.clipboard` when the browser exposes it, else null. */
export function systemClipboard(): ClipboardPort | null {
  const nav = (globalThis as { navigator?: { clipboard?: Partial<ClipboardPort> } }).navigator;
  const c = nav?.clipboard;
  if (c === undefined || typeof c.writeText !== 'function' || typeof c.readText !== 'function') return null;
  return c as ClipboardPort;
}

/** Serialise drawings into the namespaced payload written to the clipboard. */
export function encodeClipboardPayload(drawings: readonly Drawing[]): string {
  return JSON.stringify({
    [DRAWING_CLIPBOARD_KEY]: {
      version: DRAWING_CLIPBOARD_VERSION,
      drawings: drawings.map((d) => ({
        tool: d.tool,
        points: d.points.map((p) => ({ time: p.time, price: p.price })),
        style: d.style ?? {},
        paneIndex: d.paneIndex,
        ...(d.locked === undefined ? {} : { locked: d.locked }),
        ...(d.visible === undefined ? {} : { visible: d.visible }),
      })),
    },
  });
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

const isFinite_ = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/**
 * One style value survives only if it is a primitive we know how to render, or
 * a short array of numbers (`levels`). Functions, nested objects and giant
 * strings are dropped rather than rejected: an unknown key is far more likely to
 * be a newer version's style property than an attack, and dropping it still
 * yields a drawing the current renderer can handle.
 */
function sanitizeStyle(value: unknown): DrawingStyle | null {
  if (value === undefined) return {};
  if (!isRecord(value)) return null;
  const out: Record<string, unknown> = {};
  let n = 0;
  for (const [key, v] of Object.entries(value)) {
    // Never let a payload reach Object.prototype through a spread.
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
    if (++n > MAX_STYLE_KEYS) return null;
    if (typeof v === 'string') {
      if (v.length > MAX_STRING) return null;
      out[key] = v;
    } else if (typeof v === 'boolean') {
      out[key] = v;
    } else if (isFinite_(v)) {
      out[key] = v;
    } else if (Array.isArray(v)) {
      if (v.length > MAX_ARRAY || !v.every(isFinite_)) return null;
      out[key] = v.slice();
    }
    // Anything else (null, undefined, object, function) is simply not copied.
  }
  return out as DrawingStyle;
}

function sanitizePoints(value: unknown): DrawingPoint[] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_POINTS) return null;
  const out: DrawingPoint[] = [];
  for (const p of value) {
    if (!isRecord(p) || !isFinite_(p.time) || !isFinite_(p.price)) return null;
    out.push({ time: p.time, price: p.price });
  }
  return out;
}

/**
 * Validate one entry into a drawing with no id. Returns null for anything that
 * cannot be rendered: an unknown tool would throw inside the controller, and a
 * NaN anchor produces a drawing that can never be drawn or hit-tested again.
 */
export function sanitizeDrawing(value: unknown): Omit<Drawing, 'id'> | null {
  if (!isRecord(value)) return null;
  if (typeof value.tool !== 'string' || !hasDrawingTool(value.tool)) return null;
  const points = sanitizePoints(value.points);
  if (points === null) return null;
  const style = sanitizeStyle(value.style);
  if (style === null) return null;
  // An absent pane is pane zero; a bogus one is a rejection, because a drawing
  // parked on a pane that does not exist is invisible and unfindable.
  const paneIndex = value.paneIndex === undefined ? 0 : value.paneIndex;
  if (!isFinite_(paneIndex) || paneIndex < 0 || !Number.isInteger(paneIndex)) return null;
  if (value.locked !== undefined && typeof value.locked !== 'boolean') return null;
  if (value.visible !== undefined && typeof value.visible !== 'boolean') return null;
  return {
    tool: value.tool,
    points,
    style,
    paneIndex,
    ...(value.locked === undefined ? {} : { locked: value.locked }),
    ...(value.visible === undefined ? {} : { visible: value.visible }),
  };
}

/**
 * Parse clipboard text into drawings, or null when the text is not ours or is
 * not usable. All-or-nothing on purpose: a payload with one corrupt entry is a
 * corrupt payload, and pasting the other nine silently would be worse than
 * pasting none.
 */
export function decodeClipboardPayload(text: unknown): Omit<Drawing, 'id'>[] | null {
  if (typeof text !== 'string' || text.length === 0) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;                       // plain text from somewhere else
  }
  if (!isRecord(parsed)) return null;
  const body = parsed[DRAWING_CLIPBOARD_KEY];
  if (!isRecord(body)) return null;    // valid JSON, but not ours
  // A payload from a future version may carry fields this build cannot honour,
  // so refuse it rather than paste a half-understood drawing. Older versions
  // are accepted: every field this build reads is validated below anyway.
  if (!isFinite_(body.version) || body.version < 1 || body.version > DRAWING_CLIPBOARD_VERSION) return null;
  const list = body.drawings;
  if (!Array.isArray(list) || list.length === 0 || list.length > MAX_DRAWINGS) return null;
  const out: Omit<Drawing, 'id'>[] = [];
  for (const entry of list) {
    const d = sanitizeDrawing(entry);
    if (d === null) return null;
    out.push(d);
  }
  return out;
}

export interface DrawingClipboardOptions {
  /** Where to read and write. Defaults to `navigator.clipboard` when present. */
  port?: ClipboardPort | null;
  /**
   * Keep a copy in the shared in-memory clipboard so copy and paste keep
   * working when the OS clipboard is unavailable or the permission is refused.
   * Default true. Set false to make a failed system write a failed copy, which
   * a host that must not silently lose cross-tab transfer may prefer.
   */
  fallbackToMemory?: boolean;
}

/**
 * The clipboard as the controller sees it: drawings in, drawings out, no
 * exceptions escaping. Every failure mode (no clipboard API, refused
 * permission, foreign text, corrupt payload) reduces to `false` or `null`.
 */
export class DrawingClipboard {
  private _port: ClipboardPort | null;
  private _fallback: boolean;
  /** Why the last operation did not reach the OS clipboard, if it did not. */
  private _lastError: string | null = null;

  public constructor(options: DrawingClipboardOptions = {}) {
    this._port = options.port === undefined ? systemClipboard() : options.port;
    this._fallback = options.fallbackToMemory ?? true;
  }

  /** Swap the port at runtime (a host granting permission later, or a test). */
  public setPort(port: ClipboardPort | null): void {
    this._port = port;
  }

  /**
   * Turn the in-memory backstop off or on. With it off, a refused system write
   * is a failed copy, which is what a host wants when a cut that cannot reach
   * the OS clipboard must not delete the drawing.
   */
  public setFallbackToMemory(enabled: boolean): void {
    this._fallback = enabled;
  }

  /**
   * Why the OS clipboard was not used by the last call, or null when it was.
   * Set on a successful copy too, when the payload reached memory but not the
   * system clipboard: that copy works in this tab and will not appear in
   * another, which is exactly what a host wants to be able to tell the user.
   */
  public lastError(): string | null {
    return this._lastError;
  }

  /**
   * Write drawings out. Resolves true when the payload is retrievable by a
   * later `read()` (through the system clipboard, or through memory when the
   * fallback is on), false when it is not, so a caller doing a cut knows
   * whether it is safe to delete the original.
   */
  public async write(drawings: readonly Drawing[]): Promise<boolean> {
    if (drawings.length === 0) return false;
    let text: string;
    try {
      text = encodeClipboardPayload(drawings);
    } catch (e) {
      this._lastError = String(e);
      return false;
    }
    this._lastError = null;
    let systemOk = false;
    if (this._port !== null) {
      try {
        await this._port.writeText(text);
        systemOk = true;
      } catch (e) {
        this._lastError = String(e);   // typically a refused permission
      }
    } else {
      this._lastError = 'openalgo-charts: no system clipboard available';
    }
    if (this._fallback) {
      memoryText = text;
      return true;
    }
    return systemOk;
  }

  /**
   * Read drawings back, or null when there is nothing of ours to paste. The
   * system clipboard wins when it holds our payload, so a copy made in another
   * tab beats a stale in-tab one; memory is consulted when the read fails or
   * returns something that is not ours. That last case can paste an older copy
   * after the user has copied unrelated text elsewhere, which is the deliberate
   * trade: losing the copy whenever a browser refuses the read half of the
   * permission would be the worse surprise.
   */
  public async read(): Promise<Omit<Drawing, 'id'>[] | null> {
    this._lastError = null;
    if (this._port !== null) {
      try {
        const decoded = decodeClipboardPayload(await this._port.readText());
        if (decoded !== null) return decoded;
      } catch (e) {
        this._lastError = String(e);
      }
    }
    if (!this._fallback) return null;
    return decodeClipboardPayload(memoryText);
  }
}
