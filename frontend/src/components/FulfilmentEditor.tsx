import { useEffect, useState } from "react";

import { api, money } from "../api";
import type { DeliveryArea, FulfilmentInfo, Order, SlotDay } from "../types";
import { useData } from "./useData";

/**
 * Pickup or delivery, the time slot and the delivery address (task 2.1).
 * Staff may choose a full slot or type another time; the server then shows
 * a warning on the order (D-121). The delivery fee always comes from the server.
 * Typing a new address finds the area again; choosing an area keeps it.
 */
export interface FulfilmentValue {
  fulfilment: "pickup" | "delivery";
  due_at: string | null;
  delivery_address: string;
  delivery_suburb: string;
  delivery_postcode: string;
  delivery_area: number | null;
}

export const EMPTY_FULFILMENT: FulfilmentValue = {
  fulfilment: "pickup", due_at: null, delivery_address: "", delivery_suburb: "", delivery_postcode: "", delivery_area: null,
};

export function fromOrder(o: Order): FulfilmentValue {
  return {
    fulfilment: o.fulfilment, due_at: o.due_at, delivery_address: o.delivery_address, delivery_suburb: o.delivery_suburb,
    delivery_postcode: o.delivery_postcode, delivery_area: o.delivery_area,
  };
}

/** The local date of a time as YYYY-MM-DD. */
function localDay(iso: string | null): string {
  const d = iso ? new Date(iso) : new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** An ISO time as the value of a datetime-local box. */
function localInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${localDay(iso)}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function sameTime(a: string | null, b: string): boolean {
  return !!a && new Date(a).getTime() === new Date(b).getTime();
}

export function feeText(area: DeliveryArea, productsTotal: number): string {
  if (area.free_over !== null && productsTotal >= Number(area.free_over)) return "free delivery";
  const parts = [`fee ${money(area.fee)}`];
  if (area.free_over !== null) parts.push(`free from ${money(area.free_over)}`);
  if (Number(area.minimum_order) > 0) parts.push(`minimum order ${money(area.minimum_order)}`);
  return parts.join(", ");
}

interface Props {
  value: FulfilmentValue;
  onChange: (value: FulfilmentValue) => void;
  orderId?: number;
  productsTotal: number;
}

export default function FulfilmentEditor({ value, onChange, orderId, productsTotal }: Props) {
  const { data: info } = useData<FulfilmentInfo>("/api/orders/fulfilment/");
  const [day, setDay] = useState(localDay(value.due_at));
  const [otherTime, setOtherTime] = useState(false);
  const [found, setFound] = useState<DeliveryArea | null>(null);
  const kind = value.fulfilment;
  const { data: slotDay, error: slotError } = useData<SlotDay>(`/api/orders/slots/?kind=${kind}&date=${day}${orderId ? `&order=${orderId}` : ""}`);
  const set = (changes: Partial<FulfilmentValue>) => onChange({ ...value, ...changes });

  // The area for the postcode or suburb, when staff did not choose one.
  useEffect(() => {
    if (kind !== "delivery" || value.delivery_area !== null || (!value.delivery_postcode.trim() && !value.delivery_suburb.trim() && !value.delivery_address.trim())) {
      setFound(null);
      return;
    }
    const timer = window.setTimeout(() => {
      const q = new URLSearchParams({ postcode: value.delivery_postcode, suburb: value.delivery_suburb, address: value.delivery_address });
      api<{ area: DeliveryArea | null }>(`/api/orders/delivery-areas/find/?${q}`).then((r) => setFound(r.area)).catch(() => setFound(null));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [kind, value.delivery_area, value.delivery_postcode, value.delivery_suburb, value.delivery_address]);

  const chosenArea = value.delivery_area !== null ? info?.areas.find((a) => a.id === value.delivery_area) ?? null : found;
  const switchedOff = info && !(kind === "delivery" ? info.delivery_enabled : info.pickup_enabled);
  const word = kind === "delivery" ? "delivery" : "pickup";
  const slotOf = slotDay?.slots.find((s) => sameTime(value.due_at, s.start));
  const typedTime = value.due_at && !slotOf && localDay(value.due_at) === day;

  return (
    <div className="grid" style={{ gap: 8 }}>
      <div className="row" role="radiogroup" aria-label="Pickup or delivery">
        {(["pickup", "delivery"] as const).map((k) => (
          <button key={k} type="button" role="radio" aria-checked={kind === k} className={kind === k ? "primary" : ""}
            onClick={() => k !== kind && set({ fulfilment: k })}>
            {k === "pickup" ? "Pickup" : "Delivery"}
            {info && !(k === "delivery" ? info.delivery_enabled : info.pickup_enabled) && <span className="small"> (switched off)</span>}
          </button>
        ))}
      </div>
      {switchedOff && <p className="notice small" style={{ margin: 0 }}>{kind === "delivery" ? "Delivery" : "Pickup"} is switched off in the pickup and delivery settings. Staff can still book it.</p>}

      {kind === "delivery" && (
        <div className="grid" style={{ gap: 4 }}>
          <label htmlFor="delivery-address" style={{ marginBottom: 0 }}>Delivery address</label>
          <input id="delivery-address" placeholder="Street and number, flat or unit" value={value.delivery_address}
            onChange={(e) => set({ delivery_address: e.target.value, delivery_area: null })} maxLength={200} />
          <div className="row">
            <input aria-label="Suburb" placeholder="Suburb" value={value.delivery_suburb} onChange={(e) => set({ delivery_suburb: e.target.value, delivery_area: null })} style={{ flex: 2, minWidth: 140 }} />
            <input aria-label="Postcode" placeholder="Postcode" inputMode="numeric" maxLength={4} value={value.delivery_postcode}
              onChange={(e) => set({ delivery_postcode: e.target.value.replace(/\D/g, ""), delivery_area: null })} style={{ width: 110 }} />
            <select aria-label="Delivery area" value={value.delivery_area ?? ""} onChange={(e) => set({ delivery_area: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Area: find from postcode or suburb</option>
              {info?.areas.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
          <p className="small" style={{ margin: 0 }} role="status">
            {chosenArea ? <><strong>{chosenArea.name}</strong>: {feeText(chosenArea, productsTotal)}</>
              : value.delivery_postcode || value.delivery_suburb ? <span className="error">No delivery area for this postcode or suburb. Choose an area, or check the address.</span>
              : <span className="muted">Type the suburb or postcode to find the area and its fee.</span>}
          </p>
        </div>
      )}

      <div className="row">
        <label htmlFor="due-day" style={{ margin: 0 }}>{kind === "delivery" ? "Delivery day" : "Pickup day"}</label>
        <input id="due-day" type="date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
        {value.due_at && <span className="muted small">Chosen: {slotOf ? slotOf.label : new Date(value.due_at).toLocaleString("en-NZ", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>}
        {value.due_at && kind === "pickup" && <button type="button" onClick={() => set({ due_at: null })}>No time</button>}
      </div>
      {slotError && <p className="error small">{slotError}</p>}
      {slotDay && (slotDay.closed ? <p className="muted small" style={{ margin: 0 }}>Closed that day{slotDay.closed_reason ? ` (${slotDay.closed_reason})` : ""}.</p>
        : slotDay.slots.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No {word} hours that day (see the pickup and delivery settings).</p>
        : (
          <div className="slots" role="group" aria-label={`${word} times`}>
            {slotDay.slots.map((s) => {
              const chosen = sameTime(value.due_at, s.start);
              const note = s.past ? "past" : s.too_soon ? "too soon" : s.full ? "full" : s.capacity ? `${s.taken} of ${s.capacity}` : `${s.taken} booked`;
              return (
                <button key={s.start} type="button" className={`slot${chosen ? " primary" : ""}${s.full || s.past || s.too_soon ? " dim" : ""}`}
                  aria-pressed={chosen} onClick={() => set({ due_at: s.start })} title={s.label}>
                  {s.label.split(" ").slice(3).join(" ")}<small>{note}</small>
                </button>
              );
            })}
          </div>
        ))}
      <div className="row">
        {otherTime || typedTime ? (
          <label style={{ margin: 0 }}>Another time <input type="datetime-local" value={localInput(value.due_at)}
            onChange={(e) => {
              if (!e.target.value) return;
              const iso = new Date(e.target.value).toISOString();
              set({ due_at: iso });
              setDay(localDay(iso));
            }} /></label>
        ) : (
          <button type="button" className="small" onClick={() => setOtherTime(true)}>Type another time</button>
        )}
      </div>
    </div>
  );
}
