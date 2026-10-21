import { describe, expect, it } from "vitest";

import { feeText } from "../components/FulfilmentEditor";
import { statusLabel, type DeliveryArea } from "../types";

const area: DeliveryArea = { id: 1, name: "Central", fee: "8.00", minimum_order: "30.00", free_over: "100.00", postcodes: ["1010"], suburbs: [] };

describe("pickup and delivery", () => {
  it("says what the order is ready for", () => {
    expect(statusLabel("ready", "pickup")).toBe("Ready for pickup");
    expect(statusLabel("ready", "delivery")).toBe("Ready for delivery");
    expect(statusLabel("out_for_delivery", "delivery")).toBe("Out for delivery");
    expect(statusLabel("something_new", "pickup")).toBe("something_new");
  });

  it("explains the delivery fee", () => {
    expect(feeText(area, 50)).toBe("fee $8.00, free from $100.00, minimum order $30.00");
    expect(feeText(area, 100)).toBe("free delivery");
    expect(feeText({ ...area, free_over: null, minimum_order: "0.00" }, 500)).toBe("fee $8.00");
  });
});
