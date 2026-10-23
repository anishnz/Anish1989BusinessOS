import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, money, when } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import { eventWhen, tabs } from "../enquiries";
import type { Enquiry, EnquiryPage } from "../types";

/** Event and catering enquiries (task 3.1): from the website form, WhatsApp and staff. */
export default function Enquiries() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const { can } = useAuth();
  const navigate = useNavigate();
  const status = params.get("status") ?? "open";
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (params.get("q")) query.set("q", params.get("q")!);
  if (params.get("page")) query.set("page", params.get("page")!);
  const { data, error } = useData<EnquiryPage>(`/api/events/enquiries/?${query}`);

  function update(changes: Record<string, string>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) next.set(k, v);
    if (!next.get("q")) next.delete("q");
    next.delete("page");
    setParams(next);
  }

  async function add() {
    setBusy(true);
    setProblem("");
    try {
      const made = await api<Enquiry>("/api/events/enquiries/", { method: "POST", body: {} });
      navigate(`/enquiries/${made.id}`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Something went wrong.");
      setBusy(false);
    }
  }

  const page = Number(params.get("page") ?? 1);
  return (
    <div className="grid">
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Enquiries</h1>
        {can("events.create") && <button className="primary" disabled={busy} onClick={add}>+ New enquiry</button>}
      </div>
      {problem && <p className="error">{problem}</p>}
      <div className="row" role="tablist" aria-label="Which enquiries">
        {tabs(data?.counts ?? {}).map((t) => (
          <button key={t.value} role="tab" aria-selected={status === t.value} className={status === t.value ? "primary" : ""}
            onClick={() => update({ status: t.value })}>
            {t.label} · {t.count}
          </button>
        ))}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); update({ q }); }}>
        <input aria-label="Search" placeholder="#12, name, phone or email" value={q} onChange={(e) => setQ(e.target.value)} />
        <button type="submit">Search</button>
      </form>
      {error && <p className="error">{error}</p>}
      <div className="card table-wrap">
        <table>
          <thead><tr><th>Enquiry</th><th>Received</th><th>Name</th><th>Event</th><th>When</th><th className="num">Guests</th><th className="num">Budget</th><th>Status</th></tr></thead>
          <tbody>
            {data?.results.map((e) => (
              <tr key={e.id} className="link" onClick={() => navigate(`/enquiries/${e.id}`)}>
                <td><Link to={`/enquiries/${e.id}`} onClick={(ev) => ev.stopPropagation()}>#{e.id}</Link> <span className="muted small">{e.source_label}</span></td>
                <td>{when(e.created_at)}</td>
                <td>{e.name || <span className="muted">No name yet</span>}</td>
                <td>{e.event_type_label || <span className="muted">–</span>}</td>
                <td>{eventWhen(e.event_date, e.start_time)}</td>
                <td className="num">{e.guests ?? "–"}</td>
                <td className="num">{e.budget ? money(e.budget) : "–"}</td>
                <td><span className={`pill${e.status === "new" ? " needs" : ""}`}>{e.status_label}</span></td>
              </tr>
            ))}
            {data && data.results.length === 0 && <tr><td colSpan={8} className="muted">No enquiries here.</td></tr>}
            {!data && !error && <tr><td colSpan={8} className="muted">Loading…</td></tr>}
          </tbody>
        </table>
      </div>
      {data && (data.next || data.previous) && (
        <div className="row">
          <button disabled={!data.previous} onClick={() => { const n = new URLSearchParams(params); n.set("page", String(page - 1)); setParams(n); }}>Previous</button>
          <span className="muted">Page {page} · {data.count} enquiries</span>
          <button disabled={!data.next} onClick={() => { const n = new URLSearchParams(params); n.set("page", String(page + 1)); setParams(n); }}>Next</button>
        </div>
      )}
    </div>
  );
}
