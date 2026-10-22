export interface Mfa {
  required: boolean;
  enabled: boolean;
  verified: boolean;
  setup_required: boolean;
  backup_codes_remaining: number;
}

export interface AuthState {
  user: { id: number; email: string; first_name: string; last_name: string; is_staff: boolean };
  mfa: Mfa;
  /** Set while the platform's Super Admin uses "Log in as" (task 1.18). */
  login_as?: { by: string; stop_url: string } | null;
}

export interface MyPermissions {
  permissions: string[];
  usable: string[];
  business: { name: string; id: string } | null;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface OrderLine {
  id: number;
  product: number;
  product_name: string;
  unit: "kg" | "each" | "pack";
  unit_price: string;
  quantity: string;
  final_quantity: string | null;
  effective_quantity: string;
  note: string;
  line_total: string;
}

export interface OrderEvent {
  from_status: string;
  to_status: string;
  note: string;
  actor_email: string;
  at: string;
}

/** A WhatsApp message to the customer about an order (task 2.3). */
export interface OrderMessage {
  id: number;
  kind: string;
  label: string;
  status: "queued" | "sent" | "failed" | "skipped";
  result: string;
  via: "" | "message" | "template";
  is_open: boolean;
  answer: "" | "yes" | "no";
  created_at: string;
  sent_at: string | null;
  answered_at: string | null;
}

export interface Order {
  id: number;
  number: number;
  status: string;
  status_label: string;
  next_statuses: string[];
  channel: string;
  customer: number | null;
  customer_name: string;
  customer_phone: string;
  fulfilment: "pickup" | "delivery";
  due_at: string | null;
  due_until: string | null;
  due_text: string;
  delivery_address: string;
  delivery_suburb: string;
  delivery_postcode: string;
  delivery_area: number | null;
  delivery_area_name: string;
  delivery_fee: string;
  notes: string;
  lines: OrderLine[];
  estimated_total: string;
  total: string;
  gst_total: string;
  is_paid: boolean;
  payment_method: string;
  paid_at: string | null;
  created_at: string;
  events?: OrderEvent[];
  warnings?: string[];
  messages?: OrderMessage[];
  left_out?: string[];
}

export interface DeliveryArea {
  id: number;
  name: string;
  fee: string;
  minimum_order: string;
  free_over: string | null;
  postcodes: string[];
  suburbs: string[];
}

export interface FulfilmentInfo {
  pickup_enabled: boolean;
  delivery_enabled: boolean;
  pickup_slot_minutes: number;
  delivery_slot_minutes: number;
  lead_minutes: number;
  days_ahead: number;
  areas: DeliveryArea[];
}

export interface Slot {
  kind: "pickup" | "delivery";
  start: string;
  end: string;
  label: string;
  taken: number;
  capacity: number;
  full: boolean;
  past: boolean;
  too_soon: boolean;
}

export interface SlotDay {
  kind: "pickup" | "delivery";
  date: string;
  enabled: boolean;
  closed: boolean;
  closed_reason: string;
  slots: Slot[];
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  category_name: string;
  unit: "kg" | "each" | "pack";
  price: string;
  gst_amount: string;
  min_quantity: string;
  quantity_step: string;
  is_available: boolean;
  /** Stock (task 2.2): only when "Count stock" is on. */
  track_stock?: boolean;
  stock_quantity?: string;
  low_stock_level?: string | null;
  stock_state?: "not_counted" | "below_zero" | "out" | "low" | "ok";
  stock_text?: string;
}

export interface StockMovement {
  id: number;
  reason: string;
  reason_label: string;
  change: string;
  quantity_after: string;
  order_number: number | null;
  note: string;
  actor_email: string;
  at: string;
}

export interface Customer {
  id: number;
  name: string;
  phone: string;
  email: string;
  address?: string;
  tags: string;
  marketing_consent: boolean;
  last_order?: { id: number; number: number } | null;
}

/** A chat the AI handed to staff that nobody picked up yet (task 2.5). */
export interface WaitingChat {
  conversation: number;
  customer_name: string;
  customer_phone?: string;
  reason: string;
  since: string;
  unread_count?: number;
}

export interface Conversation {
  id: number;
  customer_name: string;
  customer_phone: string;
  status: "open" | "closed";
  unread_count: number;
  last_message_at: string | null;
  last_message_preview: string;
  can_reply_freely: boolean;
  assigned_to_email: string;
  messages?: Message[];
}

export interface Message {
  id: number;
  direction: "in" | "out";
  kind: string;
  text: string;
  status: string;
  error: string;
  sent_by_email: string;
  bot?: boolean;
  created_at: string;
}

/** Is the AI assistant answering a chat, or are staff? (task 2.4) */
export interface ChatAI {
  ai_on: boolean;
  state: "off" | "answering" | "staff";
  reason: string;
  since: string | null;
  order_number: number | null;
}

export interface Dashboard {
  date: string;
  sales: { total: string; gst: string; count: number; unpaid: string; average: string; change: { before: string; difference: string; percent: number | null } };
  orders: { count: number; change: { before: number; difference: number; percent: number | null } };
  week: { date: string; label: string; total: string; is_today: boolean }[];
  week_total: string;
  top_products: { product_id: number; name: string; unit: string; sales: string; quantity: string; orders: number }[];
  attention: { status: string; label: string; count: number }[];
  pickups_due_today: number;
  deliveries_due_today: number;
  low_stock?: { product_id: number; name: string; unit: string; state: string; state_text: string; stock: string; warn_at: string | null }[];
  unread_conversations?: number;
  waiting_chats?: { count: number; oldest: WaitingChat[] };
  definitions: { sales: string; orders: string; compared_with: string };
}

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  awaiting_confirmation: "Awaiting customer confirmation",
  confirmed: "Confirmed",
  preparing: "Being prepared",
  final_price_sent: "Final price sent",
  final_price_accepted: "Final price accepted",
  ready: "Ready",
  out_for_delivery: "Out for delivery",
  completed: "Completed",
  cancelled_by_customer: "Cancelled by customer",
  cancelled_by_shop: "Cancelled by shop",
  expired: "Expired",
};

/** A status in words for one order ("Ready for pickup" or "Ready for delivery"). */
export function statusLabel(status: string, fulfilment: string): string {
  if (status === "ready") return fulfilment === "delivery" ? "Ready for delivery" : "Ready for pickup";
  return STATUS_LABELS[status] ?? status;
}
