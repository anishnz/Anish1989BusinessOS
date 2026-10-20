import { useState } from "react";
import { Link } from "react-router-dom";

import { money, quantity } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import type { Dashboard } from "../types";

function Change({ diff, text }: { diff: number; text: string }) {
  const arrow = diff > 0 ? <span style={{ color: "var(--good)" }} aria-hidden="true">▲ </span> : diff < 0 ? <span style={{ color: "var(--bad)" }} aria-hidden="true">▼ </span> : null;
  return <div className="muted small">{arrow}{text}</div>;
}

function WeekChart({ week }: { week: Dashboard["week"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...week.map((w) => Number(w.total)), 0);
  const top = max <= 0 ? 100 : Math.pow(10, Math.floor(Math.log10(max))) * ([1, 2, 2.5, 5, 10].find((m) => Math.pow(10, Math.floor(Math.log10(max))) * m >= max) ?? 10);
  const W = 640, H = 220, L = 56, B = 28, T = 16, plotW = W - L - 8, plotH = H - T - B, slot = plotW / week.length, bw = Math.min(24, slot * 0.5);
  return (
    <div style={{ position: "relative" }}>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Sales per day for the last 7 days">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - 8} y1={T + plotH - plotH * f} y2={T + plotH - plotH * f} />
            <text x={L - 8} y={T + plotH - plotH * f} textAnchor="end" dominantBaseline="middle">{money(top * f).replace(".00", "")}</text>
          </g>
        ))}
        {week.map((w, i) => {
          const h = (Number(w.total) / top) * plotH;
          const x = L + slot * i + (slot - bw) / 2, y = T + plotH - h, r = Math.min(4, h);
          return (
            <g key={w.date}>
              {h > 0 && <path d={`M${x},${T + plotH} V${y + r} Q${x},${y} ${x + r},${y} H${x + bw - r} Q${x + bw},${y} ${x + bw},${y + r} V${T + plotH} Z`} />}
              <text x={x + bw / 2} y={H - 8} textAnchor="middle">{w.label}</text>
              {w.is_today && h > 0 && <text x={x + bw / 2} y={y - 6} textAnchor="middle" style={{ fill: "var(--ink)", fontWeight: 600 }}>{money(w.total)}</text>}
              <rect x={L + slot * i} y={T} width={slot} height={plotH} fill="transparent" tabIndex={0}
                onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}>
                <title>{`${w.label}: ${money(w.total)}`}</title>
              </rect>
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div className="card small" style={{ position: "absolute", top: 8, left: `${((L + slot * hover + slot / 2) / W) * 100}%`, transform: "translateX(-50%)", padding: "6px 10px", pointerEvents: "none" }}>
          <strong>{money(week[hover].total)}</strong> <span className="muted">{week[hover].label}</span>
        </div>
      )}
      <details><summary className="muted small">Show as a table</summary>
        <table><tbody>{week.map((w) => <tr key={w.date}><td>{w.label}</td><td className="num">{money(w.total)}</td></tr>)}</tbody></table>
      </details>
    </div>
  );
}

export default function DashboardPage() {
  const [day, setDay] = useState("");
  const { can } = useAuth();
  const { data, error } = useData<Dashboard>(`/api/reports/dashboard/${day ? `?date=${day}` : ""}`);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  const s = data.sales, diff = Number(s.change.difference);
  const salesChange = `${diff >= 0 ? "+" : "−"}${money(Math.abs(diff))}${s.change.percent !== null ? ` (${s.change.percent > 0 ? "+" : ""}${s.change.percent}%)` : ""} vs last week · GST ${money(s.gst)}`;
  const o = data.orders.change;
  return (
    <div className="grid">
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Dashboard</h1>
        <label className="row" style={{ margin: 0 }}>Day <input type="date" value={day || data.date} onChange={(e) => setDay(e.target.value)} /></label>
        {day && <button onClick={() => setDay("")}>Today</button>}
      </div>
      <p className="muted small" style={{ margin: 0 }}>{data.definitions.sales} Orders: {data.definitions.orders}</p>
      <div className="tiles">
        <div className="card tile hero"><div className="muted">Sales</div><div className="value">{money(s.total)}</div><Change diff={diff} text={salesChange} /></div>
        <div className="card tile"><div className="muted">Orders confirmed</div><div className="value">{data.orders.count}</div>
          <Change diff={o.difference} text={o.difference ? `${o.difference > 0 ? "+" : ""}${o.difference} vs last week (${o.before})` : `Same as last week (${o.before})`} /></div>
        <div className="card tile"><div className="muted">Average sale</div><div className="value">{money(s.average)}</div><div className="muted small">{s.count} completed</div></div>
        <div className="card tile"><div className="muted">Completed, not paid</div><div className="value">{money(s.unpaid)}</div></div>
        {data.unread_conversations !== undefined && (
          <Link className="card tile" to="/inbox" style={{ color: "inherit", textDecoration: "none" }}><div className="muted">Unread chats</div><div className="value">{data.unread_conversations}</div></Link>
        )}
      </div>
      <div className="two">
        <div className="card"><h2>Sales, last 7 days</h2><p className="muted small">Total {money(data.week_total)}</p><WeekChart week={data.week} /></div>
        <div className="grid">
          <div className="card">
            <h2>Top products, last 7 days</h2>
            {data.top_products.length === 0 && <p className="muted">No completed orders yet.</p>}
            {data.top_products.map((p) => {
              const width = (Number(p.sales) / Number(data.top_products[0].sales)) * 100;
              return (
                <div key={p.product_id} style={{ margin: "10px 0" }}>
                  <div className="row"><strong style={{ marginRight: "auto" }}>{p.name}</strong><span>{money(p.sales)}</span></div>
                  <div className="bar-fill" style={{ width: `${width}%` }} />
                  <div className="muted small">{quantity(p.quantity, p.unit)}{p.unit === "each" ? " sold" : ""} · {p.orders} order{p.orders === 1 ? "" : "s"}</div>
                </div>
              );
            })}
          </div>
          <div className="card">
            <h2>Orders needing attention</h2>
            <table><tbody>
              {data.attention.map((a) => (
                <tr key={a.status}><td>{can("orders.view") ? <Link to={`/orders?status=${a.status}`}>{a.label}</Link> : a.label}</td><td className="num"><strong>{a.count}</strong></td></tr>
              ))}
              <tr><td>Pickups due (not completed)</td><td className="num"><strong>{data.pickups_due_today}</strong></td></tr>
            </tbody></table>
          </div>
        </div>
      </div>
    </div>
  );
}
