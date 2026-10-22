import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import type { Customer, Order, Page } from "../types";

export default function Customers() {
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const { can } = useAuth();
  const { data, error } = useData<Page<Customer>>(`/api/customers/?q=${encodeURIComponent(q)}`);
  const navigate = useNavigate();
  const [problem, setProblem] = useState("");

  /** Order again (task 2.5): copy the customer's last order at today's prices. */
  async function orderAgain(orderId: number, number: number) {
    setProblem("");
    try {
      const copy = await api<Order>(`/api/orders/${orderId}/reorder/`, { method: "POST" });
      const left = copy.left_out?.length ? ` Left out: ${copy.left_out.join("; ")}.` : "";
      navigate(`/orders/${copy.id}`, { state: { note: `New draft from order #${number} at today's prices. Choose the time.${left}` } });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Something went wrong.");
    }
  }
  return (
    <div className="grid">
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Customers</h1>
        {can("crm.edit") && <a className="button" href="/admin/customers/customer/">Edit customers (classic admin)</a>}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); setQ(term); }}>
        <input aria-label="Search customers" placeholder="Name, phone, email or tag" value={term} onChange={(e) => setTerm(e.target.value)} />
        <button type="submit">Search</button>
      </form>
      {error && <p className="error">{error}</p>}
      {problem && <p className="error" role="alert">{problem}</p>}
      <div className="card table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Phone</th><th>Email</th><th>Tags</th><th>Marketing OK</th><th>Last order</th></tr></thead>
          <tbody>
            {data?.results.map((c) => (
              <tr key={c.id}><td>{c.name}</td><td>{c.phone || "–"}</td><td>{c.email || "–"}</td><td>{c.tags || "–"}</td><td>{c.marketing_consent ? "Yes" : "No"}</td>
                <td>{c.last_order ? (
                  <span className="row" style={{ gap: 6 }}>
                    <Link to={`/orders/${c.last_order.id}`}>#{c.last_order.number}</Link>
                    {can("orders.create") && <button onClick={() => orderAgain(c.last_order!.id, c.last_order!.number)}>Order again</button>}
                  </span>
                ) : <span className="muted">–</span>}</td></tr>
            ))}
            {data && data.results.length === 0 && <tr><td colSpan={6} className="muted">No customers.</td></tr>}
          </tbody>
        </table>
      </div>
      {data && data.count > data.results.length && <p className="muted small">Showing {data.results.length} of {data.count}. Search to narrow down.</p>}
    </div>
  );
}
