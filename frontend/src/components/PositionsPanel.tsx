import { useEffect, useState } from "react";
import { api } from "../api";
import type { Account, Order, Position } from "../types";

export default function PositionsPanel() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [account, setAccount] = useState<Account | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const [pos, ord, acc] = await Promise.all([
        api.positions(),
        api.orders(),
        api.account(),
      ]);
      if (cancelled) return;
      setPositions(pos);
      setOrders(ord);
      setAccount(acc);
    };
    void load();
    const timer = window.setInterval(load, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const equity = account?.equity ?? account?.margin_available;

  return (
    <div className="panel positions">
      <div className="positions-head">
        <h3>Positions</h3>
        {equity !== undefined && (
          <span className="muted">Equity: {Number(equity).toFixed(2)}</span>
        )}
      </div>
      {positions.length === 0 ? (
        <p className="muted">No open positions.</p>
      ) : (
        <table className="pos-table">
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Avg</th>
              <th>uPnL</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p, i) => (
              <tr key={`${p.instrument}-${i}`}>
                <td>{p.instrument.replace(/^NSE:/, "")}</td>
                <td className={p.side === "BUY" ? "buy-text" : "sell-text"}>{p.side}</td>
                <td>{p.quantity}</td>
                <td>{Number(p.avg_price).toFixed(2)}</td>
                <td
                  className={
                    (p.unrealized_pnl ?? 0) >= 0 ? "buy-text" : "sell-text"
                  }
                >
                  {p.unrealized_pnl !== undefined
                    ? Number(p.unrealized_pnl).toFixed(2)
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="orders-block">
        <h4>Recent orders</h4>
        {orders.length === 0 ? (
          <p className="muted">No orders yet.</p>
        ) : (
          <table className="pos-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.slice(-8).reverse().map((o) => (
                <tr key={o.order_id}>
                  <td className="muted">{o.order_id.slice(0, 8)}</td>
                  <td className={o.side === "BUY" ? "buy-text" : "sell-text"}>
                    {o.side}
                  </td>
                  <td>{o.quantity}</td>
                  <td>{o.status ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
