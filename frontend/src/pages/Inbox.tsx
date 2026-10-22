import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { when } from "../api";
import { useData } from "../components/useData";
import type { Conversation, Page, WaitingChat } from "../types";

/** Chats the AI handed to staff that nobody picked up yet, oldest first (task 2.5). */
function NeedsStaff() {
  const navigate = useNavigate();
  const { data, error } = useData<{ count: number; results: WaitingChat[] }>("/api/ai/waiting/");
  return (
    <div className="card table-wrap">
      {error && <p className="error">{error}</p>}
      <table>
        <thead><tr><th>Customer</th><th>Why</th><th>Waiting since</th><th>Unread</th></tr></thead>
        <tbody>
          {data?.results.map((c) => (
            <tr key={c.conversation} className="link" onClick={() => navigate(`/inbox/${c.conversation}`)} tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && navigate(`/inbox/${c.conversation}`)}>
              <td><strong>{c.customer_name || c.customer_phone || "Unknown"}</strong></td>
              <td>{c.reason}</td>
              <td>{when(c.since)}</td>
              <td>{(c.unread_count ?? 0) > 0 && <span className="pill on">{c.unread_count}</span>}</td>
            </tr>
          ))}
          {data && data.results.length === 0 && <tr><td colSpan={4} className="muted">No chats are waiting for staff.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function Inbox() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState(params.get("show") === "needs_staff" ? "needs_staff" : "open");
  const navigate = useNavigate();
  const { data, error, reload } = useData<Page<Conversation>>(`/api/inbox/conversations/?status=${status === "needs_staff" ? "open" : status}`);
  const { data: waiting } = useData<{ count: number; results: WaitingChat[] }>("/api/ai/waiting/");
  const waitingIds = new Set(waiting?.results.map((c) => c.conversation) ?? []);
  return (
    <div className="grid">
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Inbox</h1>
        <select aria-label="Which conversations" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">Open</option><option value="needs_staff">Needs staff{waiting?.count ? ` (${waiting.count})` : ""}</option><option value="closed">Closed</option>
        </select>
        <button onClick={() => reload()}>Refresh</button>
      </div>
      {error && <p className="error">{error}</p>}
      {status === "needs_staff" ? <NeedsStaff /> : <div className="card table-wrap">
        <table>
          <thead><tr><th>Customer</th><th>Last message</th><th>Unread</th><th>Assigned</th><th>When</th></tr></thead>
          <tbody>
            {data?.results.map((c) => (
              <tr key={c.id} className="link" onClick={() => navigate(`/inbox/${c.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate(`/inbox/${c.id}`)}>
                <td><strong>{c.customer_name || c.customer_phone || "Unknown"}</strong>{waitingIds.has(c.id) && <> <span className="pill needs">Needs staff</span></>}</td>
                <td>{c.last_message_preview}</td>
                <td>{c.unread_count > 0 && <span className="pill on">{c.unread_count}</span>}</td>
                <td className="muted">{c.assigned_to_email || "–"}</td>
                <td>{when(c.last_message_at)}</td>
              </tr>
            ))}
            {data && data.results.length === 0 && <tr><td colSpan={5} className="muted">No conversations.</td></tr>}
          </tbody>
        </table>
      </div>}
    </div>
  );
}
