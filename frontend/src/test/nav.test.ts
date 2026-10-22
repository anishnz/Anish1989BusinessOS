import { describe, expect, it } from "vitest";

import { homePath, visibleNav } from "../nav";

describe("menu", () => {
  it("shows only what the person can use", () => {
    const shopStaff = ["products.view", "crm.view", "crm.create", "crm.edit", "orders.view", "orders.create", "orders.edit"];
    expect(visibleNav(shopStaff).map((i) => i.label)).toEqual(["Orders", "Board", "Inbox", "Products", "Customers"]);
    expect(homePath(shopStaff)).toBe("/orders");
  });

  it("owners land on the dashboard; people with nothing see the empty page", () => {
    expect(homePath(["reports.view", "orders.view"])).toBe("/");
    expect(visibleNav([])).toEqual([]);
    expect(homePath([])).toBe("/nothing");
  });
});
