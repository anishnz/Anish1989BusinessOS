import { useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { api, money, quantity, when } from "../api";
import { useAuth } from "../auth";
import FulfilmentEditor, { fromOrder, type FulfilmentValue } from "../components/FulfilmentEditor";
import { useData } from "../components/useData";
import { statusLabel, type Order } from "../types";

const CANCEL = ["cancelled_by_customer", "cancelled_by_shop"];
const ASKS = ["awaiting_confirmation", "final_price_sent"]; // these send the customer a Yes/No question (task 2.3)
const METHODS: [string, string][] = [["cash", "Cash"], ["card", "Card (EFTPOS)"], ["bank_transfer", "Bank transfer"], ["other", "Other"]];

export default function OrderDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data: order, setData, error } = useData<Order>(`/api/orders/${id}/`);
  const note = (useLocation().state as { note?: string } | null)?.note ?? "";
  const [message, setMessage] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [method, setMethod] = useState("cash");
  const [weights, setWeights] = useState<Record<number, string>>({});
  const [editing, setEditing] = useState<FulfilmentValue | null>(null);
  const navigate = useNavigate();

  if (error) return <p className="error">{error}</p>;
  if (!order) return <p className="muted">Loading…</p>;
  const canEdit = can("orders.edit");

  async function act(path: string, body: unknown, done: string, method = "POST") {
    setBusy(true);
    setProblem("");
    setMessage("");
    try {
      setData(await api<Order>(path ? `/api/orders/${id}/${path}/` : `/api/orders/${id}/`, { method, body }));
      setMessage(done);
      setReason("");
      setWeights({});
      setEditing(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  /** Order again (task 2.5): a new draft with the same products at today's prices. */
  async function orderAgain() {
    setBusy(true);
    setProblem("");
    try {
      const copy = await api<Order>(`/api/orders/${id}/reorder/`, { method: "POST" });
      const left = copy.left_out?.length ? ` Left out: ${copy.left_out.join("; ")}.` : "";
      navigate(`/orders/${copy.id}`, { state: { note: `New draft from order #${order!.number} at today's prices. Choose the time.${left}` } });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const backFromDelivery = order.status === "out_for_delivery";
  const forward = order.next_statuses.filter((s) => !CANCEL.includes(s) && !(backFromDelivery && s === "ready"));
  const canCancel = order.next_statuses.some((s) => CANCEL.includes(s));
  const canChangeHow = canEdit && !["out_for_delivery", "completed", "cancelled_by_customer", "cancelled_by_shop", "expired"].includes(order.status);
  const productsTotal = Number(order.estimated_total) - Number(order.delivery_fee);
  const kgLines = order.lines.filter((l) => l.unit === "kg");
  const weighing = canEdit && order.status === "preparing" && kgLines.length > 0;
  const changed = order.total !== order.estimated_total;

  return (
    <div className="grid">
      <p className="small"><Link to="/orders">← Orders</Link></p>
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Order #{order.number}</h1>
        <span className="pill on">{order.status_label}</span>
        {can("orders.create") && !["draft", "awaiting_confirmation"].includes(order.status) && (
          <button disabled={busy} onClick={orderAgain}>Order again</button>
        )}
      </div>
      <p className="muted" style={{ margin: 0 }}>
        {order.customer_name ? `${order.customer_name}${order.customer_phone ? " · " + order.customer_phone : ""}` : "Walk-in customer"}
        {" · "}{order.channel}
      </p>
      <div className="card">
        <div className="row">
          <h2 style={{ margin: 0, marginRight: "auto" }}>{order.fulfilment === "delivery" ? `Delivery${order.delivery_area_name ? ` to ${order.delivery_area_name}` : ""}` : "Pickup"}</h2>
          {canChangeHow && !editing && <button onClick={() => setEditing(fromOrder(order))}>Change</button>}
        </div>
        {!editing && (
          <>
            <p style={{ margin: "6px 0 0" }}>{order.due_at ? order.due_text : <span className="muted">No time chosen</span>}</p>
            {order.fulfilment === "delivery" && (
              <p style={{ margin: "4px 0 0" }}>{[order.delivery_address, order.delivery_suburb, order.delivery_postcode].filter(Boolean).join(", ") || <span className="muted">No address yet</span>}</p>
            )}
          </>
        )}
        {editing && (
          <div style={{ marginTop: 8 }}>
            <FulfilmentEditor value={editing} onChange={setEditing} orderId={order.id} productsTotal={productsTotal} />
            <p className="row" style={{ marginBottom: 0 }}>
              <button className="primary" disabled={busy} onClick={() => act("", editing, "Saved.", "PATCH")}>Save</button>
              <button disabled={busy} onClick={() => setEditing(null)}>Cancel</button>
            </p>
          </div>
        )}
      </div>
      {order.warnings && order.warnings.length > 0 && (
        <div className="notice" role="note">
          <strong>Check before you go on:</strong>
          <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>{order.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          <span className="small muted">Staff may still book this order. Customers ordering by WhatsApp or the website must follow these rules.</span>
        </div>
      )}
      {order.notes && <div className="notice">Note: {order.notes}</div>}
      {(message || note) && <p role="status" style={{ color: "var(--good)" }}>{message || note}</p>}
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
            {order.fulfilment === "delivery" && (
              <tr><td colSpan={4} className="num">Delivery fee{order.delivery_area_name ? ` (${order.delivery_area_name})` : ""}</td><td className="num">{money(order.delivery_fee)}</td></tr>
            )}
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
              <button key={s} className="primary" disabled={busy} onClick={() => act("status", { to: s }, `Now: ${statusLabel(s, order.fulfilment)}.`)}>{statusLabel(s, order.fulfilment)}</button>
            ))}
          </div>
          {order.customer && forward.some((s) => ASKS.includes(s)) && (
            <p className="small muted" style={{ margin: "8px 0 0" }}>
              {forward.includes("awaiting_confirmation") ? "Awaiting customer confirmation" : "Final price sent"} sends the customer a WhatsApp message with Yes and No buttons. Their answer moves the order on.
            </p>
          )}
          {backFromDelivery && (
            <div className="row" style={{ marginTop: 12 }}>
              <input aria-label="Why the delivery did not happen" placeholder="Why the delivery did not happen" value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
              <button disabled={busy || !reason.trim()} onClick={() => act("status", { to: "ready", note: reason }, "Back to: Ready for delivery.")}>Not delivered: back to Ready</button>
            </div>
          )}
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

      {order.messages && order.messages.length > 0 && (
        <div className="card">
          <h2>WhatsApp messages to the customer</h2>
          <table className="small">
            <tbody>
              {order.messages.map((m) => (
                <tr key={m.id}>
                  <td style={{ whiteSpace: "nowrap" }}>{when(m.sent_at ?? m.created_at)}</td>
                  <td>{m.label}{m.via === "template" && <span className="muted"> (template)</span>}</td>
                  <td className={m.status === "failed" || m.status === "skipped" ? "error" : m.answer === "no" ? "error" : ""}>{m.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {order.feedback && (
        <div className="card">
          <h2>Star feedback</h2>
          {order.feedback.stars ? (
            <p style={{ margin: 0 }}>
              <span className={order.feedback.stars <= 2 ? "error" : ""} aria-label={`${order.feedback.stars} of 5 stars`}>
                {"★".repeat(order.feedback.stars)}{"☆".repeat(5 - order.feedback.stars)}
              </span>{" "}
              <span className="muted small">{when(order.feedback.answered_at)}</span>
              {order.feedback.comment && <><br />“{order.feedback.comment}”</>}
            </p>
          ) : (
            <p className="muted small" style={{ margin: 0 }}>{order.feedback.status_label}{order.feedback.note ? `: ${order.feedback.note}` : ""}</p>
          )}
        </div>
      )}

      <div className="card">
        <h2>History</h2>
        <ol className="history">
          {order.events?.map((e, i) => (
            <li key={i}>
              <strong>{e.from_status === e.to_status ? "Update" : statusLabel(e.to_status, order.fulfilment)}</strong>
              <span className="muted small"> · {when(e.at)} · {e.actor_email || "system"}</span>
              {e.note && <div>{e.note}</div>}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
