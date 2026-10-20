import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, errorMessage, money, quantity, resetCsrf } from "../api";

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(body === undefined ? null : JSON.stringify(body), { status }));
}

describe("api client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    resetCsrf();
  });

  it("sends the CSRF token on changes, not on reads", async () => {
    const calls: [string, RequestInit][] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit = {}) => {
      calls.push([url, init]);
      if (url === "/api/auth/csrf/") return reply(200, { csrfToken: "tok-1" });
      return reply(200, { ok: true });
    }));
    await api("/api/orders/");
    await api("/api/orders/", { method: "POST", body: { lines: [] } });
    const post = calls.find(([u, i]) => u === "/api/orders/" && i.method === "POST")!;
    expect((post[1].headers as Record<string, string>)["X-CSRFToken"]).toBe("tok-1");
    const get = calls.find(([u, i]) => u === "/api/orders/" && i.method === "GET")!;
    expect((get[1].headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
    expect(post[1].credentials).toBe("same-origin");
  });

  it("fetches a new token once when the old one is refused", async () => {
    let tokens = 0;
    let posts = 0;
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url === "/api/auth/csrf/") return reply(200, { csrfToken: `tok-${++tokens}` });
      posts += 1;
      return posts === 1 ? reply(403, { detail: "CSRF Failed: CSRF token from the 'X-Csrftoken' HTTP header incorrect." }) : reply(201, { id: 7 });
    }));
    expect(await api("/api/orders/", { method: "POST", body: {} })).toEqual({ id: 7 });
    expect(tokens).toBe(2);
  });

  it("turns error answers into readable messages", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply(400, { detail: "Goat curry cut: the smallest amount is 0.5kg." })));
    await expect(api("/api/orders/", { method: "GET" })).rejects.toThrow("smallest amount");
    vi.stubGlobal("fetch", vi.fn(() => reply(403, { detail: "Multi-factor authentication is required.", code: "mfa_required" })));
    const err = (await api("/api/orders/").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("mfa_required");
    expect(errorMessage({ phone: ["'123' is not a valid phone number."] }, "x")).toBe("phone: '123' is not a valid phone number.");
  });
});

describe("formatting", () => {
  it("shows NZ money and amounts", () => {
    expect(money("1234.5")).toBe("$1,234.50");
    expect(quantity("1.500", "kg")).toBe("1.5 kg");
    expect(quantity("2", "pack")).toBe("2 packs");
    expect(quantity("20", "each")).toBe("20");
  });
});
