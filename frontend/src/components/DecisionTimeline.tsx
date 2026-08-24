import type { AMTDecision } from "../types";

interface Props {
  decisions: AMTDecision[];
}

const SETUP_CLASS: Record<string, string> = {
  TRIPLE_A: "dec-triplea",
  PYRAMID: "dec-pyramid",
  VA_FADE: "dec-vafade",
};

function timeLabel(ts: string | null): string {
  if (!ts) return "—";
  const iso = ts.includes("T") ? ts : ts.replace(" ", "T");
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function DecisionTimeline({ decisions }: Props) {
  const approved = decisions.filter((d) => d.approved);

  return (
    <div className="panel decisions">
      <div className="decisions-head">
        <h3>Decision timeline</h3>
        {approved.length === 0 && <span className="muted">No entries yet</span>}
      </div>
      {approved.length > 0 && (
        <div className="dec-timeline">
          {approved.map((d, i) => (
            <div
              key={`${d.timestamp}-${i}`}
              className={`dec-entry ${SETUP_CLASS[d.setup] ?? ""}`}
              title={`${d.setup} ${d.direction ?? ""} @${d.entry ?? "?"} · SL ${
                d.stop_loss ?? "?"
              } · TP ${d.take_profit ?? "?"} · R:R ${d.risk_reward}${
                d.cushion !== "0" && d.cushion !== "0.0"
                  ? ` · cushion ${d.cushion}`
                  : ""
              }`}
            >
              <span className="dec-time">{timeLabel(d.timestamp)}</span>
              <span className="dec-setup">{d.setup}</span>
              <span className={`dec-dir ${d.direction === "LONG" ? "buy-text" : "sell-text"}`}>
                {d.direction === "LONG" ? "L" : "S"}
              </span>
              <span className="dec-entry">@{d.entry ?? "?"}</span>
              <span className="dec-rr">R:R {d.risk_reward}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
