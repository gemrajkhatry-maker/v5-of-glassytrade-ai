// TradeX backend client — REST + WebSocket.
// The backend enables CORS for all origins, so the dev server can call it
// directly. Override the base URL with VITE_API_BASE when it's not :8000.

import type {
  AMTDecision,
  AMTScanRow,
  AMTSnapshot,
  Account,
  CandleBar,
  Order,
  Position,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { signal });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${body ? `: ${body}` : ""}`);
  }
  return (await res.json()) as T;
}

/** getJson variant that returns a fallback instead of throwing. */
async function getJsonOr<T>(path: string, fallback: T): Promise<T> {
  try {
    return await getJson<T>(path);
  } catch {
    return fallback;
  }
}

export const api = {
  base: BASE,

  history: (
    instrument: string,
    timeframe = "1m",
    limit = 200,
    signal?: AbortSignal,
  ): Promise<CandleBar[]> =>
    getJson<CandleBar[]>(
      `/history/${encodeURIComponent(instrument)}?timeframe=${timeframe}&limit=${limit}`,
      signal,
    ).catch(() => []),

  amtSnapshot: (instrument: string): Promise<AMTSnapshot | null> =>
    getJsonOr<AMTSnapshot | null>(`/amt/snapshot/${encodeURIComponent(instrument)}`, null),

  amtHistory: (instrument: string, limit = 200): Promise<AMTSnapshot[]> =>
    getJson(`/amt/history/${encodeURIComponent(instrument)}?limit=${limit}`),

  amtDecisions: (instrument: string, limit = 200): Promise<AMTDecision[]> =>
    getJson(`/amt/decisions/${encodeURIComponent(instrument)}?limit=${limit}`),

  amtScanner: (limit = 50): Promise<AMTScanRow[]> =>
    getJson(`/amt/scanner?limit=${limit}`),

  positions: (): Promise<Position[]> => getJsonOr<Position[]>("/positions", []),

  orders: (): Promise<Order[]> => getJsonOr<Order[]>("/orders", []),

  account: (): Promise<Account | null> => getJsonOr<Account | null>("/account", null),
};

/** WebSocket client with auto-reconnect + backoff, replaying the latest
 *  snapshot on (re)connect so the UI never sits stale. */
export class ReconnectingSocket<T> {
  private ws: WebSocket | null = null;
  private closedByUser = false;
  private retries = 0;
  private reconnectTimer: number | null = null;
  private latest: T | null = null;

  constructor(
    private readonly path: string,
    private readonly onMessage: (msg: T) => void,
    private readonly onStatus: (status: "connecting" | "open" | "closed") => void,
    private readonly replayLatest: boolean,
  ) {}

  connect(): void {
    this.closedByUser = false;
    this.open();
  }

  disconnect(): void {
    this.closedByUser = true;
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  private open(): void {
    this.onStatus("connecting");
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const host = new URL(BASE).host;
    this.ws = new WebSocket(`${proto}://${host}${this.path}`);

    this.ws.onopen = () => {
      this.retries = 0;
      this.onStatus("open");
      if (this.replayLatest && this.latest !== null) {
        this.onMessage(this.latest);
      }
    };

    this.ws.onmessage = (ev) => {
      try {
        this.latest = JSON.parse(ev.data as string) as T;
        this.onMessage(this.latest);
      } catch {
        // ignore malformed frames
      }
    };

    this.ws.onclose = () => {
      this.onStatus("closed");
      if (this.closedByUser) return;
      const delay = Math.min(1000 * 2 ** this.retries, 15_000);
      this.retries += 1;
      this.reconnectTimer = window.setTimeout(() => this.open(), delay);
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }
}
