import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api";
import { isReady, useAuth } from "../auth";

export default function Login() {
  const { state, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from || "/";

  if (isReady(state)) return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const s = await login(email, password);
      if (s.mfa.setup_required) window.location.assign(`/account/mfa/setup/?next=${encodeURIComponent("/app" + from)}`);
      else if (s.mfa.required && !s.mfa.verified) navigate("/mfa", { state: { from } });
      else navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server. Check your connection.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form className="card login" onSubmit={submit}>
        <h1>Log in</h1>
        <p className="muted small">Anish1989 Business OS</p>
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="error" role="alert">{error}</p>}
        <p><button className="primary" type="submit" disabled={busy}>{busy ? "Logging in…" : "Log in"}</button></p>
        <p className="small"><a href="/admin/password_reset/">Forgotten your password?</a></p>
      </form>
    </div>
  );
}
