import { describe, expect, it } from "vitest";

import { needsSecondTap, newOrders, readChoice, saveChoice } from "../board";
import type { Board, BoardCard } from "../types";

function card(id: number, extra: Partial<BoardCard> = {}): BoardCard {
  return {
    id, number: 1000 + id, status: "confirmed", status_label: "Confirmed", customer: "Sita R.", fulfilment: "pickup", suburb: "",
    due_at: null, time_text: "No time", late: false, lines: [], notes: "", is_paid: false, total: "10.00",
    next: { to: "preparing", label: "Start preparing" }, confirmed_at: null, ...extra,
  };
}

function board(toPrepare: number[], ready: number[] = []): Board {
  return {
    now: "", today: "", tomorrow: false, count: toPrepare.length + ready.length, late: 0,
    columns: [
      { key: "ready", label: "Ready", orders: ready.map((id) => card(id, { status: "ready" })) }, // first here, so the code must find "To prepare" by its key
      { key: "to_prepare", label: "To prepare", orders: toPrepare.map((id) => card(id)) },
    ],
  };
}

describe("order board", () => {
  it("chimes only for orders that are new in To prepare, never on the first load", () => {
    const seen = new Set<number>();
    expect(newOrders(board([1, 2]), seen, true)).toEqual([]);
    expect(newOrders(board([1, 2]), seen, false)).toEqual([]);
    expect(newOrders(board([1, 2, 3], [9]), seen, false)).toEqual([3]); // a new Ready order is not a new order
    expect(newOrders(board([2, 3]), seen, false)).toEqual([]);
    expect(newOrders(board([1]), seen, false)).toEqual([]); // seen before: no second chime
  });

  it("asks twice before completing an order that is not paid", () => {
    expect(needsSecondTap(card(1, { next: { to: "completed", label: "Picked up" } }))).toBe(true);
    expect(needsSecondTap(card(1, { next: { to: "completed", label: "Delivered" }, is_paid: true }))).toBe(false);
    expect(needsSecondTap(card(1, { next: { to: "ready", label: "Ready for pickup" } }))).toBe(false);
  });

  it("remembers the screen's choices", () => {
    expect(readChoice("tv", false)).toBe(false);
    saveChoice("tv", true);
    expect(readChoice("tv", false)).toBe(true);
    saveChoice("tv", false);
    expect(readChoice("tv", true)).toBe(false);
  });
});
