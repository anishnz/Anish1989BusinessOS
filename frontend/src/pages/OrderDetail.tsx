import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, money, quantity, when } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import { STATUS_LABELS, type Order } from "../types";

const CANCEL = ["cancelled_by_customer", "cancelled_by_shop"];
const METHODS: [string, string][] = [["cash", "Cash"], ["card", "Card (EFTPOS)"], ["bank_transfer", "Bank transfer"], ["other", "Other"]];

export default function OrderDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data: order, setData, error } = useData<Order>(`/api/orders/${id}/`);
  const [message, setMessage] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [method, setMethod] = useState("cash");
  const [weights, setWeights] = useState<Record<number, string>>({});

  if (error) return <p className="error">{error}</p>;
  if (!order) return <p className="muted">Loading…</p>;
  const canEdit = can("orders.edit");

  async function act(path: string, body: unknown, done: string) {
    setBusy(true);
    setProblem("");
    setMessage("");
    try {
      setData(await api<Order>(`/api/orders/${id}/${path}/`, { method: "POST", body }));
      setMessage(done);
      setReason("");
      setWeights({});
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const forward = order.next_statuses.filter((s) => !CANCEL.includes(s));
  const canCancel = order.next_statuses.some((s) => CANCEL.includes(s));
  const kgLines = order.lines.filter((l) => l.unit === "kg");
  const weighing = canEdit && order.status === "preparing" && kgLines.length > 0;
  const changed = order.total !== order.estimated_total;

  return (
    <div className="grid">
      <p className="small"><Link to="/orders">← Orders</Link></p>
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Order #{order.number}</h1>
        <span className="pill on">{order.status_label}</span>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        {order.customer_name ? `${order.customer_name}${order.customer_phone ? " · " + order.customer_phone : ""}` : "Walk-in customer"}
        {" · "}{order.channel}{order.pickup_at ? ` · pickup ${when(order.pickup_at)}` : ""}
      </p>
      {order.notes && <div className="notice">Note: {order.notes}</div>}
      {message && <p role="status" style={{ color: "var(--good)" }}>{message}</p>}
      {problem && <p className="error" role="alert">{problem}</p>}

      <div className="card table-wrap">
        <table className="stack">
          <thead><tr><th>Product</th><th className="num">Ordered</th><th className="num">Real weight</th><th className="num">Price</th><th className="num">Line total</th></tr></thead>
          <tbody>
            {order.lines.map((l) => (
              <tr key={l.id}>
                <td className="lead">{l.product_name}{l.note && <div className="muted small">{l.note}</div>}</td>
                <td className="num" data-label="Ordered">{quantity(l.quantity, l.unit)}</td>
                <td className="num" data-label="Real weight">
                  {weighing && l.unit === "kg" ? (
                    <input aria-label={`Real weight of ${l.product_name} in kg`} inputMode="decimal" style={{ width: 90, textAlign: "right" }}
                      value={weights[l.id] ?? (l.final_quantity ? String(Number(l.final_quantity)) : "")} onChange={(e) => setWeights({ ...weights, [l.id]: e.target.value })} />
                  ) : l.final_quantity ? quantity(l.final_quantity, l.unit) : <span className="muted">–</span>}
                </td>
                <td className="num" data-label="Price">{money(l.unit_price)}{l.unit === "kg" ? "/kg" : ""}</td>
                <td className="num" data-label="Line total">{money(l.line_total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr><td colSpan={4} className="num"><strong>Total</strong>{changed && <div className="muted small">Estimate was {money(order.estimated_total)}</div>}</td><td className="num"><strong>{money(order.total)}</strong></td></tr>
            <tr><td colSpan={4} className="num muted small">GST included</td><td className="num muted small">{money(order.gst_total)}</td></tr>
          </tfoot>
        </table>
        {weighing && (
          <p className="row" style={{ justifyContent: "flex-end" }}>
            <button className="primary" disabled={busy || Object.keys(weights).length === 0}
              onClick={() => act("weights", { weights }, "Weights saved.")}>Save weights</button>
          </p>
        )}
      </div>

      {canEdit && (forward.length > 0 || canCancel) && (
        <div className="card">
          <h2>Next step</h2>
          <div className="row">
            {forward.map((s) => (
              <button key={s} className="primary" disabled={busy} onClick={() => act("status", { to: s }, `Now: ${STATUS_LABELS[s]}.`)}>{STATUS_LABELS[s]}</button>
            ))}
          </div>
          {canCancel && (
            <div className="row" style={{ marginTop: 12 }}>
              <input aria-label="Reason for cancelling" placeholder="Reason for cancelling" value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
              <button className="danger" disabled={busy || !reason.trim()} onClick={() => act("status", { to: "cancelled_by_customer", note: reason }, "Cancelled.")}>Customer cancelled</button>
              <button className="danger" disabled={busy || !reason.trim()} onClick={() => act("status", { to: "cancelled_by_shop", note: reason }, "Cancelled.")}>Shop cancelled</button>
            </div>
          )}
        </div>
      )}

      {canEdit && !["draft", "awaiting_confirmation", "cancelled_by_customer", "cancelled_by_shop", "expired"].includes(order.status) && (
        <div className="card">
          <h2>Payment</h2>
          {order.is_paid ? (
            <div className="row">
              <span>Paid ({METHODS.find(([k]) => k === order.payment_method)?.[1] ?? order.payment_method}) {when(order.paid_at)}</span>
              <button disabled={busy} onClick={() => act("payment", { paid: false }, "Marked as not paid.")}>Mark as not paid (refund)</button>
            </div>
          ) : (
            <div className="row">
              <select aria-label="Paid by" value={method} onChange={(e) => setMethod(e.target.value)}>{METHODS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
              <button className="primary" disabled={busy} onClick={() => act("payment", { paid: true, method }, "Marked as paid.")}>Mark as paid</button>
            </div>
          )}
        </div>
      )}

      <div className="card">
        <h2>History</h2>
        <ol className="history">
          {order.events?.map((e, i) => (
            <li key={i}>
              <strong>{STATUS_LABELS[e.to_status] ?? e.to_status}</strong>
              <span className="muted small"> · {when(e.at)} · {e.actor_email || "system"}</span>
              {e.note && <div>{e.note}</div>}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
