import { useState } from "react";

import { useAuth } from "../auth";
import { useData } from "../components/useData";
import type { Customer, Page } from "../types";

export default function Customers() {
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const { can } = useAuth();
  const { data, error } = useData<Page<Customer>>(`/api/customers/?q=${encodeURIComponent(q)}`);
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
      <div className="card table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Phone</th><th>Email</th><th>Tags</th><th>Marketing OK</th></tr></thead>
          <tbody>
            {data?.results.map((c) => (
              <tr key={c.id}><td>{c.name}</td><td>{c.phone || "–"}</td><td>{c.email || "–"}</td><td>{c.tags || "–"}</td><td>{c.marketing_consent ? "Yes" : "No"}</td></tr>
            ))}
            {data && data.results.length === 0 && <tr><td colSpan={5} className="muted">No customers.</td></tr>}
          </tbody>
        </table>
      </div>
      {data && data.count > data.results.length && <p className="muted small">Showing {data.results.length} of {data.count}. Search to narrow down.</p>}
    </div>
  );
}
