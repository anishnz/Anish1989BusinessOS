import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError, money, quantity } from "../api";
import { useAuth } from "../auth";
import { chime, needsSecondTap, newOrders, readChoice, saveChoice, soundReady, unlockSound } from "../board";
import type { Board as BoardData, BoardCard } from "../types";

const EVERY_SECONDS = 10;

function clock(date: Date | null): string {
  return date ? date.toLocaleTimeString("en-NZ", { hour: "2-digit", minute: "2-digit", hour12: false }) : "–";
}

/** The live order board for the counter and the kitchen (task 2.6). */
export default function Board() {
  const { can, perms } = useAuth();
  const canMove = can("orders.edit");
  const [tv, setTv] = useState(() => readChoice("tv", false));
  const [sound, setSound] = useState(() => readChoice("sound", true));
  const [tomorrow, setTomorrow] = useState(() => readChoice("tomorrow", false));
  const [board, setBoard] = useState<BoardData | null>(null);
  const [error, setError] = useState("");
  const [loggedOut, setLoggedOut] = useState(false);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [armed, setArmed] = useState<number | null>(null);
  const [problem, setProblem] = useState<{ id: number; text: string } | null>(null);
  const [fresh, setFresh] = useState<number[]>([]);
  const [canPlay, setCanPlay] = useState(soundReady());
  const seen = useRef(new Set<number>());
  const firstLoad = useRef(true);
  const soundOn = useRef(sound);
  soundOn.current = sound;

  const view = useRef(0); // answers that arrive after "Show tomorrow" changed are thrown away

  const load = useCallback(async () => {
    const mine = view.current;
    try {
      const data = await api<BoardData>(`/api/orders/board/${tomorrow ? "?tomorrow=1" : ""}`);
      if (mine !== view.current) return;
      const added = newOrders(data, seen.current, firstLoad.current);
      firstLoad.current = false;
      if (added.length) {
        if (soundOn.current) chime();
        setFresh((ids) => [...ids, ...added]);
        window.setTimeout(() => setFresh((ids) => ids.filter((id) => !added.includes(id))), 120000);
      }
      setBoard(data);
      setError("");
      setLoggedOut(false);
      setUpdated(new Date());
    } catch (e) {
      if (mine !== view.current) return;
      setLoggedOut(e instanceof ApiError && (e.status === 401 || (e.status === 403 && /credentials/i.test(e.message))));
      setError(e instanceof Error ? e.message : "The server did not answer.");
    }
  }, [tomorrow]);

  useEffect(() => {
    if (armed === null) return;
    const timer = window.setTimeout(() => setArmed(null), 6000); // the second tap must come soon
    return () => window.clearTimeout(timer);
  }, [armed]);

  useEffect(() => {
    view.current += 1;
    seen.current = new Set();
    firstLoad.current = true; // a new view: what is there now is not "new"
    load();
    const timer = window.setInterval(load, EVERY_SECONDS * 1000);
    return () => window.clearInterval(timer);
  }, [load]);

  function choose(key: string, on: boolean, set: (v: boolean) => void) {
    set(on);
    saveChoice(key, on);
  }

  async function allowSound() {
    setCanPlay(await unlockSound());
  }

  function enterTv() {
    choose("tv", true, setTv);
    document.documentElement.requestFullscreen?.().catch(() => undefined);
  }

  function leaveTv() {
    choose("tv", false, setTv);
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => undefined);
  }

  async function move(card: BoardCard) {
    if (!card.next.to) return;
    if (needsSecondTap(card) && armed !== card.id) {
      setArmed(card.id);
      return;
    }
    setBusy(card.id);
    setArmed(null);
    setProblem(null);
    try {
      await api(`/api/orders/${card.id}/status/`, { method: "POST", body: { to: card.next.to } });
      await load();
    } catch (e) {
      setProblem({ id: card.id, text: e instanceof Error ? e.message : "Could not move the order." });
      await load();
    } finally {
      setBusy(null);
    }
  }

  const controls = (
    <div className="row board-controls">
      <label className="check">
        <input type="checkbox" checked={tomorrow} onChange={(e) => choose("tomorrow", e.target.checked, setTomorrow)} /> Show tomorrow
      </label>
      <button onClick={() => { choose("sound", !sound, setSound); allowSound(); }} aria-pressed={sound}>
        {sound ? "🔔 Sound on" : "🔕 Sound off"}
      </button>
      {tv ? <button onClick={leaveTv}>Exit TV mode</button> : <button className="primary" onClick={enterTv}>TV mode</button>}
    </div>
  );

  const summary = board
    ? `${board.count} order${board.count === 1 ? "" : "s"}${board.late ? ` · ${board.late} late` : ""} · ${tomorrow ? "today, tomorrow and late" : "today and late"}`
    : "Loading…";

  return (
    <div className={tv ? "board-tv" : "grid"} onPointerDown={() => { if (sound && !canPlay) allowSound(); }}>
      <div className="row board-head">
        <div style={{ marginRight: "auto" }}>
          <h1>{tv ? perms?.business?.name ?? "Order board" : "Order board"}</h1>
          <div className="muted small">{summary}</div>
        </div>
        {tv && <div className="board-clock" aria-label="Time now">{clock(updated)}</div>}
        {controls}
      </div>
      {loggedOut && (
        <p className="notice" role="alert">
          Your login has ended, so the board cannot show new orders. <button onClick={() => window.location.reload()}>Log in again</button>
        </p>
      )}
      {error && !loggedOut && (
        <p className="notice" role="alert">
          The board could not be updated: {error} It tries again every {EVERY_SECONDS} seconds. Last updated {clock(updated)}.
        </p>
      )}
      {!canMove && <p className="muted small">You can see the board. Moving orders needs the Orders – Edit permission.</p>}
      {sound && !canPlay && (
        // Fixed at the bottom, so the cards do not move when it goes away after the first tap.
        <p className="notice small board-sound-hint" role="status">Tap or click the board once so the browser lets it play the chime for new orders.</p>
      )}
      <div className="board-columns">
        {(board?.columns ?? []).map((column) => (
          <section key={column.key} className="board-column" aria-label={column.label}>
            <h2>{column.label} <span className="pill">{column.orders.length}</span></h2>
            {column.orders.map((card) => (
              <article key={card.id} className={`board-card${card.late ? " late" : ""}${fresh.includes(card.id) ? " fresh" : ""}`}>
                <div className="board-card-head">
                  <Link to={`/orders/${card.id}`} className="board-number">#{card.number}</Link>
                  {card.late && <span className="pill needs">Late</span>}
                  <span className="board-time">{card.time_text}</span>
                </div>
                <div className="muted">
                  {card.customer} · {card.fulfilment === "delivery" ? `Delivery${card.suburb ? ` · ${card.suburb}` : ""}` : "Pickup"}
                </div>
                {column.key === "preparing" && card.status !== "preparing" && <div><span className="pill">{card.status_label}</span></div>}
                <ul className="board-lines">
                  {card.lines.map((line, n) => (
                    <li key={n}>
                      <strong>{quantity(line.amount, line.unit)}</strong> {line.name}
                      {line.note && <span className="muted"> – {line.note}</span>}
                    </li>
                  ))}
                </ul>
                {card.notes && <p className="board-note">{card.notes}</p>}
                <div className={card.is_paid ? "muted small" : "error small"}>{card.is_paid ? "Paid" : "Not paid"} · {money(card.total)}</div>
                {card.next.note && (
                  <p className="muted small">
                    {card.status === "preparing" ? <Link to={`/orders/${card.id}`}>{card.next.note}</Link> : card.next.note}
                  </p>
                )}
                {canMove && card.next.to && (
                  <button className="primary board-move" disabled={busy !== null} onClick={() => move(card)}>
                    {busy === card.id ? "Moving…" : armed === card.id ? `Not paid yet. Tap again: ${card.next.label}` : card.next.label}
                  </button>
                )}
                {problem?.id === card.id && <p className="error small" role="alert">{problem.text}</p>}
              </article>
            ))}
            {column.orders.length === 0 && <p className="muted small">Nothing here.</p>}
          </section>
        ))}
      </div>
    </div>
  );
}
