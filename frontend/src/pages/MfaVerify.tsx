import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api";
import { isReady, useAuth } from "../auth";

export default function MfaVerify() {
  const { state, verify, logout } = useAuth();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from || "/";

  if (!state) return <Navigate to="/login" replace />;
  if (isReady(state)) return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await verify(code);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form className="card login" onSubmit={submit}>
        <h1>Two-step verification</h1>
        <p className="muted">Type the 6-digit code from your authenticator app, or one of your backup codes.</p>
        <label htmlFor="code">Code</label>
        <input id="code" inputMode="text" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
        {error && <p className="error" role="alert">{error}</p>}
        <p className="row">
          <button className="primary" type="submit" disabled={busy}>Verify</button>
          <button type="button" onClick={() => logout()}>Cancel</button>
        </p>
      </form>
    </div>
  );
}
