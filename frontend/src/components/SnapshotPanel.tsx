import type { AMTSnapshot } from "../types";

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="snap-row">
      <span className="snap-label">{label}</span>
      <span className={`snap-value${strong ? " snap-strong" : ""}`}>{value}</span>
    </div>
  );
}

export default function SnapshotPanel({ snapshot }: { snapshot: AMTSnapshot | null }) {
  if (!snapshot) {
    return (
      <div className="panel">
        <h3>AMT Analysis</h3>
        <p className="muted">No snapshot yet — waiting for market data.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h3>AMT Analysis</h3>
      <Row label="Phase" value={snapshot.phase} strong />
      <Row label="Direction" value={snapshot.direction} />
      <Row label="Location" value={snapshot.location} />
      <Row label="Profile" value={snapshot.profile_shape} />
      <Row label="Close" value={snapshot.close ?? "—"} />
      <Row label="VWAP" value={snapshot.vwap} />
      <Row label="POC" value={snapshot.poc ?? "—"} />
      <Row label="VAH / VAL" value={`${snapshot.vah ?? "—"} / ${snapshot.val ?? "—"}`} />
      <Row label="Delta" value={snapshot.delta} />
      <Row label="CVD" value={snapshot.cvd} />
      <Row label="CVD slope" value={snapshot.cvd_slope} />
      <Row
        label="Divergence"
        value={snapshot.cvd_divergence}
        strong={snapshot.cvd_divergence !== "NONE"}
      />
      <Row label="Absorption" value={snapshot.absorption_side ?? "NONE"} />
      <Row label="Abs strength" value={snapshot.absorption_strength} />
      <Row label="Abs age" value={String(snapshot.absorption_age)} />
      <Row label="Aggression" value={snapshot.aggression_score} />
      <Row label="Book imbalance" value={snapshot.book_imbalance} />
      <Row label="Book PoLR" value={snapshot.book_polr} />
      <Row
        label="Book swept"
        value={`B ${snapshot.book_swept_bids} / A ${snapshot.book_swept_asks}`}
      />
      <Row label="IB" value={snapshot.ib_complete ? `${snapshot.ib_low}–${snapshot.ib_high}` : "forming"} />
      <Row label="LVN" value={snapshot.lvn_levels.join(", ") || "—"} />
      <Row label="HVN" value={snapshot.hvn_levels.join(", ") || "—"} />
    </div>
  );
}
