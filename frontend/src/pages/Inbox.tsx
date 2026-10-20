import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { when } from "../api";
import { useData } from "../components/useData";
import type { Conversation, Page } from "../types";

export default function Inbox() {
  const [status, setStatus] = useState("open");
  const navigate = useNavigate();
  const { data, error, reload } = useData<Page<Conversation>>(`/api/inbox/conversations/?status=${status}`);
  return (
    <div className="grid">
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Inbox</h1>
        <select aria-label="Which conversations" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">Open</option><option value="closed">Closed</option>
        </select>
        <button onClick={() => reload()}>Refresh</button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="card table-wrap">
        <table>
          <thead><tr><th>Customer</th><th>Last message</th><th>Unread</th><th>Assigned</th><th>When</th></tr></thead>
          <tbody>
            {data?.results.map((c) => (
              <tr key={c.id} className="link" onClick={() => navigate(`/inbox/${c.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate(`/inbox/${c.id}`)}>
                <td><strong>{c.customer_name || c.customer_phone || "Unknown"}</strong></td>
                <td>{c.last_message_preview}</td>
                <td>{c.unread_count > 0 && <span className="pill on">{c.unread_count}</span>}</td>
                <td className="muted">{c.assigned_to_email || "–"}</td>
                <td>{when(c.last_message_at)}</td>
              </tr>
            ))}
            {data && data.results.length === 0 && <tr><td colSpan={5} className="muted">No conversations.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
