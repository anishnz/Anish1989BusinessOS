import { describe, expect, it, vi } from "vitest";

import { counter, debounce, SECTIONS } from "../website";

describe("website editor", () => {
  it("counts characters against the limit", () => {
    expect(counter("Hello", 60)).toEqual({ text: "5 / 60", over: false });
    expect(counter("x".repeat(60), 60).over).toBe(false); // exactly at the limit is fine
    expect(counter("x".repeat(61), 60)).toEqual({ text: "61 / 60", over: true });
  });

  it("saves once after typing stops", () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const run = debounce(fn, 800);
    run("a");
    run("ab");
    vi.advanceTimersByTime(799);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith("ab");
    run("abc");
    run.cancel();
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("lists every text once, SEO last", () => {
    const keys = SECTIONS.flatMap((s) => s.keys);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.slice(-2)).toEqual(["seo_title", "seo_description"]);
  });
});
