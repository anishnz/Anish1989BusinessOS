import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError, when } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import { changes, eventWhen, toForm, type DetailField, type DetailForm } from "../enquiries";
import type { Choice, Enquiry } from "../types";

const STATUSES: Choice[] = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "quoted", label: "Quoted" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
];

const EVENT_TYPES: Choice[] = [
  { value: "wedding", label: "Wedding" },
  { value: "birthday", label: "Birthday" },
  { value: "corporate", label: "Work or corporate" },
  { value: "cultural", label: "Cultural or festival" },
  { value: "religious", label: "Religious (puja, bratabandha)" },
  { value: "memorial", label: "Funeral or memorial" },
  { value: "party", label: "Party or gathering" },
  { value: "other", label: "Other" },
];

function fieldErrors(e: unknown): Record<string, string> {
  if (e instanceof ApiError && e.data && typeof e.data === "object" && "fields" in e.data) {
    return (e.data as { fields: Record<string, string> }).fields;
  }
  return {};
}

export default function EnquiryDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data, setData, error } = useData<Enquiry>(`/api/events/enquiries/${id}/`);
  const [form, setForm] = useState<DetailForm | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [lost, setLost] = useState(false);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const editable = can("events.edit");

  useEffect(() => {
    if (data) setForm(toForm(data));
  }, [data]);

  async function run(work: () => Promise<Enquiry>, done = "") {
    setBusy(true);
    setProblem("");
    setErrors({});
    setSaved("");
    try {
      setData(await work());
      setSaved(done);
      return true;
    } catch (e) {
      setErrors(fieldErrors(e));
      setProblem(e instanceof Error ? e.message : "Something went wrong.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  function save(e: FormEvent) {
    e.preventDefault();
    if (!data || !form) return;
    const body = changes(toForm(data), form);
    if (Object.keys(body).length === 0) {
      setSaved("Nothing to save.");
      return;
    }
    run(() => api<Enquiry>(`/api/events/enquiries/${id}/`, { method: "PATCH", body }), "Saved.");
  }

  async function move(status: string) {
    if (status === "lost" && !lost) {
      setLost(true);
      return;
    }
    const ok = await run(() => api<Enquiry>(`/api/events/enquiries/${id}/status/`, { method: "POST", body: { status, reason } }));
    if (ok) {
      setLost(false);
      setReason("");
    }
  }

  async function addNote(e: FormEvent) {
    e.preventDefault();
    const ok = await run(() => api<Enquiry>(`/api/events/enquiries/${id}/notes/`, { method: "POST", body: { text: note } }));
    if (ok) setNote("");
  }

  if (error) return <p className="error">{error}</p>;
  if (!data || !form) return <p className="muted">Loading…</p>;

  const set = (key: DetailField) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const field = (key: DetailField, label: string, props: Record<string, unknown> = {}, long = false) => (
    <div>
      <label htmlFor={`f-${key}`}>{label}</label>
      {long
        ? <textarea id={`f-${key}`} rows={3} value={form[key]} onChange={set(key)} disabled={!editable} style={{ width: "100%" }} {...props} />
        : <input id={`f-${key}`} value={form[key]} onChange={set(key)} disabled={!editable} style={{ width: "100%" }} {...props} />}
      {errors[key] && <p className="error small" style={{ margin: "4px 0 0" }}>{errors[key]}</p>}
    </div>
  );

  return (
    <div className="grid" style={{ maxWidth: 980 }}>
      <p className="small"><Link to="/enquiries">← Enquiries</Link></p>
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Enquiry #{data.id}{data.name ? ` · ${data.name}` : ""}</h1>
        <span className={`pill${data.status === "new" ? " needs" : ""}`}>{data.status_label}</span>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        {data.source_label} · received {when(data.created_at)} · {eventWhen(data.event_date, data.start_time)}{data.guests ? ` · ${data.guests} guests` : ""}
        {data.conversation && can("crm.view") ? <> · <Link to={`/inbox/${data.conversation}`}>Open the WhatsApp chat</Link></> : null}
      </p>
      {data.status === "lost" && data.lost_reason && <p className="notice" style={{ margin: 0 }}>Lost: {data.lost_reason}</p>}
      {data.missing.length > 0 && data.status !== "lost" && (
        <p className="notice" style={{ margin: 0 }}>Still needed for a quote: {data.missing.join(", ")}.</p>
      )}

      {editable && (
        <div className="card">
          <div className="row" aria-label="Status">
            <span>Move to:</span>
            {STATUSES.filter((s) => s.value !== data.status).map((s) => (
              <button key={s.value} disabled={busy} onClick={() => move(s.value)}>{s.label}</button>
            ))}
          </div>
          {lost && (
            <div className="row" style={{ marginTop: 10 }}>
              <label htmlFor="lost-reason" style={{ margin: 0 }}>Why was it lost?</label>
              <input id="lost-reason" value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)}
                placeholder="For example booked another caterer" style={{ flex: 1, minWidth: 220 }} />
              <button className="primary" disabled={busy || !reason.trim()} onClick={() => move("lost")}>Mark as lost</button>
              <button onClick={() => { setLost(false); setReason(""); }}>Cancel</button>
            </div>
          )}
        </div>
      )}
      {problem && <p className="error" role="alert">{problem}</p>}

      <div className="two">
        <form className="card" onSubmit={save}>
          <h2 style={{ marginTop: 0 }}>Details</h2>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "0 14px" }}>
            {field("contact_name", "Name", { maxLength: 150 })}
            {field("contact_phone", "Phone", { type: "tel" })}
            {field("contact_email", "Email", { type: "email" })}
            <div>
              <label htmlFor="f-event_type">Type of event</label>
              <select id="f-event_type" value={form.event_type} onChange={set("event_type")} disabled={!editable} style={{ width: "100%" }}>
                <option value="">Not given</option>
                {EVENT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
              {errors.event_type && <p className="error small">{errors.event_type}</p>}
            </div>
            {field("event_date", "Date", { type: "date" })}
            {field("start_time", "Start time", { type: "time" })}
            {field("end_time", "End time", { type: "time" })}
            {field("guests", "Guests", { type: "number", min: 1, max: 10000 })}
            {field("budget", "Budget (NZ$)", { inputMode: "decimal" })}
          </div>
          {field("venue", "Venue", { maxLength: 300 })}
          {field("menu", "Food and drinks", { maxLength: 2000 }, true)}
          {field("dietary_needs", "Dietary needs", { maxLength: 1000 }, true)}
          {field("message", "Message", { maxLength: 3000 }, true)}
          {editable && (
            <div className="row" style={{ marginTop: 12 }}>
              <button className="primary" type="submit" disabled={busy}>Save</button>
              {saved && <span className="muted" role="status">{saved}</span>}
            </div>
          )}
        </form>

        <div className="card">
          <h2 style={{ marginTop: 0 }}>History and notes</h2>
          {editable && (
            <form onSubmit={addNote}>
              <label htmlFor="note">Add a note</label>
              <textarea id="note" rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} style={{ width: "100%" }}
                placeholder="For example: called, sending a quote tomorrow" />
              <button type="submit" disabled={busy || !note.trim()} style={{ marginTop: 6 }}>Add note</button>
            </form>
          )}
          <ol className="history">
            {[...data.activities].reverse().map((a) => (
              <li key={a.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                <strong>{a.kind_label}</strong>{a.text ? `: ${a.text}` : ""}
                <div className="muted small">{when(a.created_at)}{a.by_email ? ` · ${a.by_email}` : ""}</div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
