import { describe, expect, it } from "vitest";

import { changes, eventWhen, tabs, toForm } from "../enquiries";
import type { Enquiry } from "../types";

const base = {
  id: 7, name: "Sita", status: "new", status_label: "New", source: "website", source_label: "Website form",
  event_type: "wedding", event_type_label: "Wedding", event_date: "2026-12-12", start_time: "18:30:00", guests: 120,
  budget: "4500.00", customer: 3, conversation: null, created_at: "", updated_at: "", contact_name: "Sita", contact_phone: "+64211234567",
  contact_email: "", end_time: null, venue: "Mt Roskill hall", menu: "", dietary_needs: "", message: "", lost_reason: "",
  status_changed_at: "", activities: [], missing: [],
} as Enquiry;

describe("enquiry helpers", () => {
  it("turns an enquiry into form text, with times as HH:MM and empty values as blank", () => {
    const form = toForm(base);
    expect(form.start_time).toBe("18:30");
    expect(form.end_time).toBe("");
    expect(form.guests).toBe("120");
    expect(form.budget).toBe("4500.00");
  });

  it("sends only the fields that changed, trimmed", () => {
    const before = toForm(base);
    expect(changes(before, { ...before })).toEqual({});
    expect(changes(before, { ...before, guests: " 150 ", venue: "Mt Roskill hall " })).toEqual({ guests: "150" });
    expect(changes(before, { ...before, start_time: "" })).toEqual({ start_time: "" });
  });

  it("counts open enquiries and all enquiries for the tabs", () => {
    const t = tabs({ new: 2, contacted: 1, quoted: 3, won: 4, lost: 5 });
    expect(t[0]).toEqual({ value: "open", label: "Open", count: 6 });
    expect(t.find((x) => x.value === "")?.count).toBe(15);
    expect(tabs({})[0].count).toBe(0);
  });

  it("writes the event day and time in New Zealand style", () => {
    expect(eventWhen(null, null)).toBe("Date not given");
    expect(eventWhen("2026-12-12", null)).toMatch(/Saturday.*12.*Dec.*2026/);
    expect(eventWhen("2026-12-12", "18:30:00")).toMatch(/6:30 pm$/);
    expect(eventWhen("2026-12-12", "00:05")).toMatch(/12:05 am$/);
    expect(eventWhen("2026-12-12", "12:00")).toMatch(/12:00 pm$/);
  });
});
