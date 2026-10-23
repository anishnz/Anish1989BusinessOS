/** Helpers for the enquiry pages (task 3.1). */
import type { Enquiry } from "./types";

/** The fields staff can change, in screen order. */
export const DETAIL_FIELDS = [
  "contact_name", "contact_phone", "contact_email", "event_type", "event_date", "start_time", "end_time",
  "guests", "budget", "venue", "menu", "dietary_needs", "message",
] as const;

export type DetailField = (typeof DETAIL_FIELDS)[number];
export type DetailForm = Record<DetailField, string>;

/** The enquiry as form text ("" for empty; times as HH:MM). */
export function toForm(e: Enquiry): DetailForm {
  const out = {} as DetailForm;
  for (const key of DETAIL_FIELDS) {
    const value = e[key];
    let text = value === null || value === undefined ? "" : String(value);
    if ((key === "start_time" || key === "end_time") && text) text = text.slice(0, 5);
    out[key] = text;
  }
  return out;
}

/** Only what changed, so a save never overwrites a change someone else made to another field. */
export function changes(before: DetailForm, after: DetailForm): Partial<DetailForm> {
  const out: Partial<DetailForm> = {};
  for (const key of DETAIL_FIELDS) {
    if (before[key].trim() !== after[key].trim()) out[key] = after[key].trim();
  }
  return out;
}

/** The tabs above the list: open ones first, with their counts. */
export function tabs(counts: Record<string, number>): { value: string; label: string; count: number }[] {
  const open = (counts.new ?? 0) + (counts.contacted ?? 0) + (counts.quoted ?? 0);
  return [
    { value: "open", label: "Open", count: open },
    { value: "new", label: "New", count: counts.new ?? 0 },
    { value: "contacted", label: "Contacted", count: counts.contacted ?? 0 },
    { value: "quoted", label: "Quoted", count: counts.quoted ?? 0 },
    { value: "won", label: "Won", count: counts.won ?? 0 },
    { value: "lost", label: "Lost", count: counts.lost ?? 0 },
    { value: "", label: "All", count: open + (counts.won ?? 0) + (counts.lost ?? 0) },
  ];
}

/** "Saturday 12 Dec 2026, 6:30 pm" (New Zealand time is how the date was entered). */
export function eventWhen(date: string | null, time: string | null): string {
  if (!date) return "Date not given";
  const [y, m, d] = date.split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-NZ", { weekday: "long", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  if (!time) return day;
  const [h, min] = time.split(":").map(Number);
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${day}, ${hour}:${String(min).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}
