import type { AMTScanRow } from "../types";

interface Props {
  rows: AMTScanRow[];
  selected: string | null;
  onSelect: (instrument: string) => void;
  loading: boolean;
}

const SETUP_COLORS: Record<string, string> = {
  TRIPLE_A: "setup-triplea",
  ACCUMULATING: "setup-accum",
  ABSORBING: "setup-absorb",
  ABSORPTION: "setup-absorb",
};

export default function ScannerPanel({ rows, selected, onSelect, loading }: Props) {
  return (
    <div className="panel scanner">
      <h3>AMT Scanner</h3>
      {loading && rows.length === 0 ? (
        <p className="muted">Scanning…</p>
      ) : rows.length === 0 ? (
        <p className="muted">No setups detected.</p>
      ) : (
        <table className="scan-table">
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Phase</th>
              <th>Setup</th>
              <th>Score</th>
              <th>Dir</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.instrument}
                className={selected === r.instrument ? "scan-selected" : ""}
                onClick={() => onSelect(r.instrument)}
              >
                <td>{r.instrument.replace(/^NSE:/, "")}</td>
                <td>{r.phase}</td>
                <td>
                  <span className={`setup-chip ${SETUP_COLORS[r.setup] ?? ""}`}>
                    {r.setup}
                  </span>
                </td>
                <td>{r.score}</td>
                <td>{r.direction}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
