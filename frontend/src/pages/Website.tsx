import { useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError, when } from "../api";
import type { WebsiteState, WebsiteVersion } from "../types";
import { counter, debounce, SECTIONS } from "../website";

type Content = Record<string, string | boolean>;

/** The website editor (task 2.9): fields on the left, the draft's preview on the right. Changes are drafts until published. */
export default function Website() {
  const [state, setState] = useState<WebsiteState | null>(null);
  const [draft, setDraft] = useState<Content>({});
  const [saving, setSaving] = useState<"" | "saving" | "saved" | "error">("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState("");
  const [message, setMessage] = useState("");
  const [suggesting, setSuggesting] = useState("");
  const [suggestion, setSuggestion] = useState<{ key: string; text: string } | null>(null);
  const [versions, setVersions] = useState<WebsiteVersion[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const latest = useRef<Content>({});

  useEffect(() => {
    api<WebsiteState>("/api/website/").then((s) => {
      setState(s);
      setDraft(s.content);
      latest.current = s.content;
    }).catch((e) => setProblem(e instanceof Error ? e.message : "Could not load the website."));
  }, []);

  const save = useMemo(() => debounce(async (content: Content) => {
    setSaving("saving");
    try {
      const s = await api<WebsiteState>("/api/website/draft/", { method: "PUT", body: { content } });
      setState(s);
      setErrors({});
      setSaving("saved");
      setPreviewKey((k) => k + 1);
    } catch (e) {
      setSaving("error");
      const fields = e instanceof ApiError ? ((e.data as { fields?: Record<string, string> })?.fields ?? {}) : {};
      setErrors(fields);
    }
  }, 800), []);

  useEffect(() => () => save.cancel(), [save]);

  function change(key: string, value: string | boolean) {
    const next = { ...latest.current, [key]: value };
    latest.current = next;
    setDraft(next);
    setMessage("");
    save(next);
  }

  async function suggest(key: string) {
    setSuggesting(key);
    setProblem("");
    try {
      const r = await api<{ text: string }>("/api/website/generate/", { method: "POST", body: { field: key } });
      setSuggestion({ key, text: r.text });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The AI did not answer.");
    } finally {
      setSuggesting("");
    }
  }

  async function publish() {
    save.cancel();
    try {
      await api("/api/website/draft/", { method: "PUT", body: { content: latest.current } });
      const s = await api<WebsiteState>("/api/website/publish/", { method: "POST" });
      setState(s);
      setMessage(`Published. Version ${s.live?.number} is live.`);
      if (showHistory) loadHistory();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not publish.");
    }
  }

  async function loadHistory() {
    const r = await api<{ results: WebsiteVersion[] }>("/api/website/versions/");
    setVersions(r.results);
  }

  async function restore(n: number) {
    try {
      const s = await api<WebsiteState>(`/api/website/versions/${n}/restore/`, { method: "POST" });
      setState(s);
      setDraft(s.content);
      latest.current = s.content;
      setPreviewKey((k) => k + 1);
      setMessage(`Version ${n} is in the draft now. Check the preview, then click Publish.`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not restore.");
    }
  }

  if (problem && !state) return <p className="error">{problem}</p>;
  if (!state) return <p className="muted">Loading…</p>;
  const fields = Object.fromEntries(state.fields.map((f) => [f.key, f]));
  const readOnly = !state.can_edit;

  return (
    <div className="grid">
      <div className="row">
        <div style={{ marginRight: "auto" }}>
          <h1>Website</h1>
          <div className="muted small">
            {state.live ? `Live: version ${state.live.number}, ${when(state.live.published_at)}` : "Not published yet: visitors see a first version made from your business details."}
            {" · "}{saving === "saving" ? "Saving…" : saving === "error" ? <span className="error">Not saved: fix the texts in red</span> : state.unpublished_changes ? "Draft has changes that are not published" : "Draft is the same as the live website"}
          </div>
        </div>
        <a className="button" href="/" target="_blank" rel="noopener">Open website</a>
        <button onClick={() => { setShowHistory(!showHistory); if (!showHistory) loadHistory(); }}>History</button>
        {state.can_publish && <button className="primary" disabled={!state.unpublished_changes || saving === "saving" || saving === "error"} onClick={publish}>Publish</button>}
      </div>
      {message && <p role="status" style={{ color: "var(--good)", margin: 0 }}>{message}</p>}
      {problem && <p className="error" role="alert" style={{ margin: 0 }}>{problem}</p>}
      {readOnly && <p className="muted small">You can look. Changing the website needs Websites – Edit; publishing needs Websites – Publish.</p>}

      {showHistory && (
        <div className="card">
          <h2>Published versions</h2>
          <table className="small">
            <tbody>
              {versions.map((v) => (
                <tr key={v.number}>
                  <td>Version {v.number}</td><td>{when(v.published_at)}</td><td className="muted">{v.published_by}</td>
                  <td>{state.can_edit && <button onClick={() => restore(v.number)}>Put in the draft</button>}</td>
                </tr>
              ))}
              {versions.length === 0 && <tr><td className="muted">Nothing published yet.</td></tr>}
            </tbody>
          </table>
          <p className="muted small">The last 20 versions are kept.</p>
        </div>
      )}

      <div className="website-editor">
        <div className="grid">
          {SECTIONS.map((section) => (
            <div className="card" key={section.title}>
              <h2>{section.title}</h2>
              {section.keys.map((key) => {
                const f = fields[key];
                if (!f) return null;
                const value = String(draft[key] ?? "");
                const count = counter(value, f.limit);
                return (
                  <div key={key} className="website-field">
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <label htmlFor={`w-${key}`} style={{ margin: 0 }}>{f.label}</label>
                      {state.can_edit && (
                        <button className="small" disabled={suggesting !== ""} onClick={() => suggest(key)}>
                          {suggesting === key ? "Writing…" : "✨ Generate with AI"}
                        </button>
                      )}
                    </div>
                    {f.long ? (
                      <textarea id={`w-${key}`} rows={Math.min(8, Math.max(3, Math.ceil(f.limit / 120)))} value={value} readOnly={readOnly}
                        onChange={(e) => change(key, e.target.value)} />
                    ) : (
                      <input id={`w-${key}`} value={value} readOnly={readOnly} onChange={(e) => change(key, e.target.value)} />
                    )}
                    <div className="row small" style={{ justifyContent: "space-between" }}>
                      <span className={errors[key] ? "error" : "muted"}>{errors[key] || f.help}</span>
                      <span className={count.over ? "error" : "muted"}>{count.text}</span>
                    </div>
                    {suggestion?.key === key && (
                      <div className="notice small">
                        <div style={{ whiteSpace: "pre-wrap" }}>{suggestion.text}</div>
                        <div className="row" style={{ marginTop: 6 }}>
                          <button className="primary" onClick={() => { change(key, suggestion.text); setSuggestion(null); }}>Use this</button>
                          <button onClick={() => setSuggestion(null)}>Discard</button>
                          <span className="muted">AI suggestion: check the facts before you publish.</span>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
          <div className="card">
            <h2>What the page shows</h2>
            {state.switches.map((s) => (
              <label key={s.key} className="check" style={{ display: "flex", margin: "6px 0" }}>
                <input type="checkbox" checked={Boolean(draft[s.key])} disabled={readOnly} onChange={(e) => change(s.key, e.target.checked)} /> {s.label}
              </label>
            ))}
            <label htmlFor="w-whatsapp">WhatsApp number for the button</label>
            <input id="w-whatsapp" value={String(draft.whatsapp_number ?? "")} readOnly={readOnly} placeholder="021 123 4567"
              onChange={(e) => change("whatsapp_number", e.target.value)} />
            {errors.whatsapp_number && <div className="error small">{errors.whatsapp_number}</div>}
            <p className="muted small">Products, prices, opening hours and delivery areas come from the system, so they are always up to date.</p>
          </div>
        </div>
        <div className="website-preview card">
          <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>Preview of the draft</h2></div>
          <iframe key={previewKey} title="Preview of the draft" src="/website/preview/" />
        </div>
      </div>
    </div>
  );
}
