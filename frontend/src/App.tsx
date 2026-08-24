import { useCallback, useEffect, useRef, useState } from "react";
import { ReconnectingSocket, api } from "./api";
import AMTChart from "./components/AMTChart";
import DecisionTimeline from "./components/DecisionTimeline";
import PositionsPanel from "./components/PositionsPanel";
import ScannerPanel from "./components/ScannerPanel";
import SnapshotPanel from "./components/SnapshotPanel";
import type { AMTDecision, AMTScanRow, AMTSnapshot, CandleBar } from "./types";

const DEFAULT_INSTRUMENT = "NSE:RELIANCE";

export default function App() {
  const [instrument, setInstrument] = useState<string>(DEFAULT_INSTRUMENT);
  const [bars, setBars] = useState<CandleBar[]>([]);
  const [history, setHistory] = useState<AMTSnapshot[]>([]);
  const [decisions, setDecisions] = useState<AMTDecision[]>([]);
  const [live, setLive] = useState<AMTSnapshot | null>(null);
  const [scanRows, setScanRows] = useState<AMTScanRow[]>([]);
  const [scanLoading, setScanLoading] = useState(true);
  const [wsStatus, setWsStatus] = useState<"connecting" | "open" | "closed">("connecting");
  const wsRef = useRef<ReconnectingSocket<AMTSnapshot> | null>(null);

  // --- instrument data (bars + snapshot history) ----------------------------
  useEffect(() => {
    const ctrl = new AbortController();
    setBars([]);
    setHistory([]);
    setDecisions([]);
    setLive(null);
    void (async () => {
      const [barData, snapData, decData] = await Promise.all([
        api.history(instrument, "1m", 200, ctrl.signal).catch(() => []),
        api.amtHistory(instrument, 200).catch(() => []),
        api.amtDecisions(instrument, 200).catch(() => []),
      ]);
      if (ctrl.signal.aborted) return;
      setBars(barData);
      setHistory(snapData);
      setDecisions(decData);
      const last = snapData[snapData.length - 1] ?? null;
      setLive(last);
      const current = await api.amtSnapshot(instrument);
      if (!ctrl.signal.aborted && current) setLive(current);
    })();
    return () => ctrl.abort();
  }, [instrument]);

  // --- scanner poll ----------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const rows = await api.amtScanner(50).catch(() => []);
      if (!cancelled) {
        setScanRows(rows);
        setScanLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(load, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  // --- live WS stream ---------------------------------------------------------
  useEffect(() => {
    const ws = new ReconnectingSocket<AMTSnapshot>(
      "/ws/amt",
      (snapshot) => {
        // live-update the selected instrument; keep a bounded history
        setLive(snapshot);
        if (snapshot.instrument === instrument) {
          setHistory((prev) => {
            const next = [...prev, snapshot];
            return next.length > 200 ? next.slice(next.length - 200) : next;
          });
        }
      },
      setWsStatus,
      true,
    );
    ws.connect();
    wsRef.current = ws;
    return () => ws.disconnect();
  }, [instrument]);

  const onSelect = useCallback((iid: string) => {
    setInstrument(iid);
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <h1>TradeX <span className="accent">AMT</span> Terminal</h1>
        <div className="header-right">
          <span className={`ws-dot ws-${wsStatus}`} title={`WebSocket: ${wsStatus}`} />
          <span className="muted">{wsStatus}</span>
          <span className="muted">{api.base}</span>
        </div>
      </header>

      <main className="layout">
        <section className="chart-col">
          <AMTChart
            bars={bars}
            snapshots={history}
            live={live}
            decisions={decisions}
            instrument={instrument}
          />
          <DecisionTimeline decisions={decisions} />
          <PositionsPanel />
        </section>

        <aside className="side-col">
          <ScannerPanel
            rows={scanRows}
            selected={instrument}
            onSelect={onSelect}
            loading={scanLoading}
          />
          <SnapshotPanel snapshot={live} />
        </aside>
      </main>
    </div>
  );
}
