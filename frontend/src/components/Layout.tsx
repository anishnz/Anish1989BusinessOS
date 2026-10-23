import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { api } from "../api";
import { useAuth } from "../auth";
import { visibleNav } from "../nav";
import { useUnread } from "./useUnread";
import { useWaiting } from "./useWaiting";

const ICONS: Record<string, string> = { "/": "◧", "/orders": "≡", "/board": "▤", "/inbox": "✉", "/products": "▦", "/customers": "☺", "/website": "◎" };

function readPref(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writePref(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private window: the choice simply is not remembered */
  }
}

export default function Layout() {
  const { state, perms, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(readPref("sidebar") === "collapsed");
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState(readPref("theme") || "auto");
  const location = useLocation();
  const unread = useUnread(perms?.usable.includes("crm.view") ?? false);
  const waiting = useWaiting(perms?.usable.includes("crm.view") ?? false).length;

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    writePref("theme", theme);
  }, [theme]);

  const items = visibleNav(perms?.usable ?? []);

  async function backToSuperAdmin() {
    const done = await api<{ back: string }>(state?.login_as?.stop_url ?? "/login-as/stop/", { method: "POST" });
    window.location.href = done.back;
  }
  const name = state?.user.first_name || state?.user.email;
  const themePicker = (
    <select aria-label="Colour theme" value={theme} onChange={(e) => setTheme(e.target.value)}>
      <option value="auto">Theme: device</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
  );

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}`}>
      <nav className={`side${open ? " open" : ""}`} aria-label="Main menu">
        <div className="brand" title={perms?.business?.name}><span className="label">{perms?.business?.name ?? "Business OS"}</span></div>
        {items.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === "/"} className="nav" title={item.label}>
            <span className="icon" aria-hidden="true">{ICONS[item.to]}</span>
            <span className="label">{item.label}</span>
            {item.to === "/inbox" && unread > 0 && <span className="pill on badge" aria-label={`${unread} unread`}>{unread}</span>}
            {item.to === "/inbox" && waiting > 0 && <span className="pill badge needs" title="Chats waiting for staff" aria-label={`${waiting} waiting for staff`}>{waiting}</span>}
          </NavLink>
        ))}
        <div style={{ flex: 1 }} />
        <div className="side-account">
          <div className="muted small" title={state?.user.email}>{name}</div>
          {themePicker}
          <a className="small" href="/account/mfa/">Two-step verification</a>
        </div>
        <a className="nav" href="/guide/" title="User guide: how to use the system">
          <span className="icon" aria-hidden="true">?</span><span className="label">Help</span>
        </a>
        <a className="nav" href="/admin/" title="Classic admin (settings, roles, users)">
          <span className="icon" aria-hidden="true">⚙</span><span className="label">Classic admin</span>
        </a>
      </nav>
      {open && <div className="scrim" onClick={() => setOpen(false)} aria-hidden="true" />}
      <div className="page">
        <header className="top">
          <button className="menu-button" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Menu">☰</button>
          <button className="collapse-button" onClick={() => { setCollapsed(!collapsed); writePref("sidebar", collapsed ? "open" : "collapsed"); }}
            aria-label={collapsed ? "Show menu labels" : "Hide menu labels"}>{collapsed ? "»" : "«"}</button>
          <span className="top-brand">{perms?.business?.name}</span>
          <div className="spacer" />
          <span className="top-extra">{themePicker}</span>
          <span className="muted small top-extra" title={state?.user.email}>{name}</span>
          <a className="small top-extra" href="/account/mfa/">Two-step verification</a>
          <a className="small" href="/guide/">Help</a>
          <button onClick={() => logout()}>Log out</button>
        </header>
        {state?.login_as && (
          <div className="login-as" role="alert">
            <span><strong>You are logged in as {state.user.email}</strong> (Super Admin {state.login_as.by}, “Log in as”).</span>
            <button onClick={backToSuperAdmin}>Back to Super Admin</button>
          </div>
        )}
        <main>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
