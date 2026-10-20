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
  pickup_at: string | null;
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
}

export interface Customer {
  id: number;
  name: string;
  phone: string;
  email: string;
  tags: string;
  marketing_consent: boolean;
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
  created_at: string;
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
  unread_conversations?: number;
  definitions: { sales: string; orders: string; compared_with: string };
}

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  awaiting_confirmation: "Awaiting customer confirmation",
  confirmed: "Confirmed",
  preparing: "Being prepared",
  final_price_sent: "Final price sent",
  final_price_accepted: "Final price accepted",
  ready: "Ready for pickup",
  completed: "Completed",
  cancelled_by_customer: "Cancelled by customer",
  cancelled_by_shop: "Cancelled by shop",
  expired: "Expired",
};
