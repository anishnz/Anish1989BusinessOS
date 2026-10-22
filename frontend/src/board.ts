/**
 * Helpers for the live order board (task 2.6): which orders are new, when to
 * ask twice, the chime, and the remembered choices.
 */
import type { Board, BoardCard } from "./types";

/** Orders in "To prepare" that were not seen before. The first load only records what is there (no chime). */
export function newOrders(board: Board, seen: Set<number>, firstLoad: boolean): number[] {
  const column = board.columns.find((c) => c.key === "to_prepare");
  const fresh = (column?.orders ?? []).map((o) => o.id).filter((id) => !seen.has(id));
  fresh.forEach((id) => seen.add(id));
  return firstLoad ? [] : fresh;
}

/** Completing an order that is not paid needs a second tap, so nobody forgets to take the money. */
export function needsSecondTap(card: BoardCard): boolean {
  return card.next.to === "completed" && !card.is_paid;
}

/** A short two-note chime made in the browser (no sound file). Browsers only allow sound after a click on the page. */
let audio: AudioContext | null = null;

/** Call from a click or tap. Resolves to true when the board can play sound. */
export async function unlockSound(): Promise<boolean> {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return false;
    audio = audio ?? new Ctx();
    if (audio.state === "suspended") await audio.resume();
    return audio.state === "running";
  } catch {
    return false;
  }
}

export function soundReady(): boolean {
  return audio !== null && audio.state === "running";
}

export function chime(): void {
  if (!audio || audio.state !== "running") return;
  const start = audio.currentTime;
  [880, 1320].forEach((freq, n) => {
    const osc = audio!.createOscillator();
    const gain = audio!.createGain();
    const at = start + n * 0.18;
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(0.3, at + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.35);
    osc.connect(gain).connect(audio!.destination);
    osc.start(at);
    osc.stop(at + 0.4);
  });
}

/** Choices this screen remembers (TV mode, sound, tomorrow). A private window may not keep them; that is fine. */
export function readChoice(key: string, fallback: boolean): boolean {
  try {
    const value = window.localStorage.getItem(`board-${key}`);
    return value === null ? fallback : value === "on";
  } catch {
    return fallback;
  }
}

export function saveChoice(key: string, on: boolean): void {
  try {
    window.localStorage.setItem(`board-${key}`, on ? "on" : "off");
  } catch {
    /* not remembered */
  }
}
