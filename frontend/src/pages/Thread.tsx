import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, when } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import type { Conversation } from "../types";

export default function Thread() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data, setData, error } = useData<Conversation>(`/api/inbox/conversations/${id}/`);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (data && data.unread_count > 0) api(`/api/inbox/conversations/${id}/read/`, { method: "POST" }).catch(() => undefined);
  }, [data, id]);

  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      const updated = await api<Conversation>(`/api/inbox/conversations/${id}/reply/`, { method: "POST", body: { text } });
      setData(updated);
      const last = updated.messages?.[updated.messages.length - 1];
      if (last?.status === "failed") setProblem(`Not sent: ${last.error}`);
      else setText("");
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <div className="grid" style={{ maxWidth: 820 }}>
      <p className="small"><Link to="/inbox">← Inbox</Link></p>
      <h1>{data.customer_name || data.customer_phone}</h1>
      <p className="muted" style={{ margin: 0 }}>{data.customer_phone} · {data.status === "open" ? "Open" : "Closed"}{data.assigned_to_email ? ` · assigned to ${data.assigned_to_email}` : ""}</p>
      <div className="card bubbles">
        {data.messages?.map((m) => (
          <div key={m.id} className={`bubble ${m.direction}`}>
            {m.kind !== "text" && <em>[{m.kind}] </em>}{m.text}
            <small>{when(m.created_at)}{m.direction === "out" ? ` · ${m.status}${m.sent_by_email ? " · " + m.sent_by_email : ""}${m.error ? " · " + m.error : ""}` : ""}</small>
          </div>
        ))}
        {data.messages?.length === 0 && <p className="muted">No messages yet.</p>}
      </div>
      {can("crm.edit") && (data.can_reply_freely ? (
        <form className="card" onSubmit={send}>
          <label htmlFor="reply">Reply</label>
          <textarea id="reply" rows={3} style={{ width: "100%" }} value={text} onChange={(e) => setText(e.target.value)} maxLength={4096} required />
          {problem && <p className="error" role="alert">{problem}</p>}
          <p><button className="primary" type="submit" disabled={busy || !text.trim()}>Send</button></p>
        </form>
      ) : (
        <p className="notice">More than 24 hours have passed since the customer's last message. WhatsApp only allows an approved template now; send it from the <a href={`/admin/inbox/conversation/${id}/change/`}>classic inbox page</a>.</p>
      ))}
    </div>
  );
}
