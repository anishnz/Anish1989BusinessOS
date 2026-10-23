import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, when } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import type { ChatAI, Conversation, Enquiry } from "../types";

/** "Make enquiry": turn this chat into an event or catering enquiry (task 3.1). */
function MakeEnquiry({ id }: { id: string }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  async function make() {
    setBusy(true);
    setProblem("");
    try {
      const made = await api<Enquiry>("/api/events/enquiries/from-chat/", { method: "POST", body: { conversation: Number(id) } });
      navigate(`/enquiries/${made.id}`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <>
      <button disabled={busy} onClick={make}>Make enquiry</button>
      {problem && <span className="error small">{problem}</span>}
    </>
  );
}

/** The AI assistant's state in this chat, with the button to hand it over or give it back (task 2.4). */
function AIBar({ id, canEdit }: { id: string; canEdit: boolean }) {
  const { data, setData } = useData<ChatAI>(`/api/ai/chats/${id}/`);
  const [busy, setBusy] = useState(false);
  if (!data || !data.ai_on) return null;

  async function set(answer: boolean) {
    setBusy(true);
    try {
      setData(await api<ChatAI>(`/api/ai/chats/${id}/`, { method: "POST", body: { answer } }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="notice row" role="status" style={{ margin: 0 }}>
      <span style={{ marginRight: "auto" }}>
        {data.state === "answering" ? <><strong>The AI assistant answers this chat.</strong>{data.order_number ? ` It is making order #${data.order_number}.` : ""}</>
          : <><strong>Staff answer this chat</strong> ({data.reason}). The AI is quiet.</>}
      </span>
      {canEdit && (data.state === "answering"
        ? <button disabled={busy} onClick={() => set(false)}>I will answer</button>
        : <button disabled={busy} onClick={() => set(true)}>Let the AI answer again</button>)}
    </div>
  );
}

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
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>{data.customer_name || data.customer_phone}</h1>
        {id && can("events.create") && <MakeEnquiry id={id} />}
      </div>
      <p className="muted" style={{ margin: 0 }}>{data.customer_phone} · {data.status === "open" ? "Open" : "Closed"}{data.assigned_to_email ? ` · assigned to ${data.assigned_to_email}` : ""}</p>
      {id && <AIBar id={id} canEdit={can("crm.edit")} />}
      <div className="card bubbles">
        {data.messages?.map((m) => (
          <div key={m.id} className={`bubble ${m.direction}`}>
            {m.kind !== "text" && <em>[{m.kind}] </em>}{m.text}
            <small>{when(m.created_at)}{m.direction === "out" ? ` · ${m.status}${m.sent_by_email ? " · " + m.sent_by_email : m.bot ? " · AI assistant" : ""}${m.error ? " · " + m.error : ""}` : ""}</small>
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
