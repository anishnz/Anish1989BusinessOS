import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { money, when } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import { STATUS_LABELS, type Order, type Page } from "../types";

export default function Orders() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const { can } = useAuth();
  const navigate = useNavigate();
  const status = params.get("status") ?? "";
  const show = params.get("show") ?? (status ? "" : "open");
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (show === "open") query.set("open", "true");
  if (params.get("q")) query.set("q", params.get("q")!);
  if (params.get("page")) query.set("page", params.get("page")!);
  const { data, error } = useData<Page<Order>>(`/api/orders/?${query}`);

  function update(changes: Record<string, string>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    next.delete("page");
    setParams(next);
  }

  const page = Number(params.get("page") ?? 1);
  return (
    <div className="grid">
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Orders</h1>
        {can("orders.create") && <Link className="button primary" to="/orders/new">+ New order</Link>}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); update({ q }); }}>
        <select aria-label="Which orders" value={show} onChange={(e) => update({ show: e.target.value, status: "" })}>
          <option value="open">Open orders</option>
          <option value="">All orders</option>
        </select>
        <select aria-label="Status" value={status} onChange={(e) => update({ status: e.target.value, show: e.target.value ? "" : show })}>
          <option value="">Any status</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input aria-label="Search" placeholder="#1001 or customer name" value={q} onChange={(e) => setQ(e.target.value)} />
        <button type="submit">Search</button>
      </form>
      {error && <p className="error">{error}</p>}
      <div className="card table-wrap">
        <table>
          <thead><tr><th>Order</th><th>Created</th><th>Customer</th><th>Status</th><th>Pickup or delivery</th><th className="num">Total</th><th>Paid</th></tr></thead>
          <tbody>
            {data?.results.map((o) => (
              <tr key={o.id} className="link" onClick={() => navigate(`/orders/${o.id}`)}>
                <td><Link to={`/orders/${o.id}`} onClick={(e) => e.stopPropagation()}>#{o.number}</Link></td>
                <td>{when(o.created_at)}</td>
                <td>{o.customer_name || <span className="muted">Walk-in</span>}</td>
                <td><span className="pill">{o.status_label}</span></td>
                <td>{o.fulfilment === "delivery" ? "Delivery" : "Pickup"}{o.due_at ? <span className="muted"> · {o.due_text}</span> : null}</td>
                <td className="num">{money(o.total)}</td>
                <td>{o.is_paid ? "Yes" : "No"}</td>
              </tr>
            ))}
            {data && data.results.length === 0 && <tr><td colSpan={7} className="muted">No orders.</td></tr>}
            {!data && !error && <tr><td colSpan={7} className="muted">Loading…</td></tr>}
          </tbody>
        </table>
      </div>
      {data && (data.next || data.previous) && (
        <div className="row">
          <button disabled={!data.previous} onClick={() => { const n = new URLSearchParams(params); n.set("page", String(page - 1)); setParams(n); }}>Previous</button>
          <span className="muted">Page {page} · {data.count} orders</span>
          <button disabled={!data.next} onClick={() => { const n = new URLSearchParams(params); n.set("page", String(page + 1)); setParams(n); }}>Next</button>
        </div>
      )}
    </div>
  );
}
