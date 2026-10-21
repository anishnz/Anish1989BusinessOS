# 05. WhatsApp AI ordering

Last updated: 22 October 2026

## Goal

Customers order by chatting on WhatsApp. They do not need to open the website or fill in a form. The website backend is the central management system, WhatsApp is the customer-facing channel, and the AI agent connects the two.

## Customer workflow

1. **Scan QR code.** The customer scans the shop's QR code, and WhatsApp opens a chat with the business.
2. **Verify identity.** The customer verifies with a one-time code (OTP) sent through WhatsApp, where supported.
3. **Place an order.** The customer types a message, for example "I need 1 kg of meat".
4. **AI understands the message.** The AI finds the product, quantity and any other details. If something is unclear, it asks (for example "Which cut: lamb leg or goat curry cut?").
5. **Stock check.** The AI checks live stock. If an item is not available, it suggests an alternative.
6. **Confirm by WhatsApp.** The AI sends an order summary and asks the customer to confirm or edit it.
7. **Record the order.** After confirmation, the order is saved in the backend with the customer details, order history and sales records.
8. **Manage the order.** Staff process the order in the dashboard.
9. **Final weight and price.** For items sold by weight, staff enter the real weight, and the customer gets the final price on WhatsApp to accept.
10. **Status updates.** Received, being prepared, ready for pickup, or out for delivery.
11. **Feedback.** After pickup, the customer is asked for a 1 to 5 star rating.
12. **Analyse.** All orders and chats feed sales reports, customer analysis, inventory and demand forecasts.

## Extra features

| Feature | How it works |
|---|---|
| Weight-based pricing | An order of "1 kg" may weigh 1.08 kg. Staff enter the real weight, and the customer accepts the final price. |
| Stock-aware AI | The AI checks stock before confirming and offers alternatives. |
| Quick reorder | "Same as last week" rebuilds the customer's last order. |
| Pickup and delivery slots | The customer chooses pickup or delivery and a time slot. The shop sets opening hours, capacity per slot, delivery areas and fees (D-120 to D-122). |
| Human handover | If the AI is unsure, or the customer is upset, a staff member takes over the chat in the unified inbox. |
| Languages | English and Nepali, including Nepali written in English letters. The AI answers in the customer's language (D-119). |
| Payment | No payment in the chat. The customer pays at pickup or on delivery, and staff mark the order as paid (D-117). |

## Order states

`Draft` → `Awaiting customer confirmation` → `Confirmed` → `Being prepared` → `Final price sent` → `Final price accepted` → `Ready for pickup` → `Completed`

Delivery orders: `Ready for delivery` → `Out for delivery` → `Completed` (D-123).

Other states: `Cancelled by customer`, `Cancelled by shop`, `Expired` (no confirmation in time).

## Rules

- The AI never confirms an order on its own. The customer must confirm the summary.
- The AI never changes prices, gives refunds or promises discounts outside the approved rules.
- Prices and stock are always checked on the server, not taken from the AI's text.
- All chats and AI decisions are logged per tenant.
- The tenant uses its own WhatsApp Business account and keys (see [Settings and secrets](04-tenant-settings-and-secrets.md)).

## WhatsApp platform notes

- Use the official WhatsApp Business Platform (Cloud API) or an authorised partner.
- When a customer messages first, the business can reply freely for 24 hours. Messages sent outside that window need pre-approved templates (for example status updates and the daily owner summary).
- WhatsApp has a special "authentication" template type for sending OTP codes.
- Marketing messages need the customer's opt-in. Customers can type STOP to opt out, and this is recorded in the consent log.
- WhatsApp rules and prices change, so check the current Meta documentation before building.
