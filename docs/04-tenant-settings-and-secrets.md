# 04. Tenant settings and secret vault

Last updated: 21 October 2026

> **Status:** the vault, settings page, test button and first providers were built in task 1.5. How it works: [13-developer-setup.md](13-developer-setup.md#secret-vault-and-integrations-task-15). How to use it: [user guide chapter 4](user-guide/04-integrations-and-api-keys.md). Card payments, the usage and cost meter and key health checks come later.

## Goal

Each tenant (business) manages its own API keys and provider accounts from a **Settings** page. They can add, test, rotate and remove keys themselves. The platform never needs to know the tenant's keys in plain text, and the design lets us change or add providers later without rewriting modules.

## Provider categories

| Category | Providers (first version) | Later |
|---|---|---|
| AI models | OpenAI, Anthropic Claude, Google Gemini, local/open models (for example Ollama) | Others behind the same interface |
| Messaging | WhatsApp Business, Viber, Telegram | Facebook Messenger, Instagram |
| Email | SMTP or tenant's email service | Gmail and Outlook (OAuth) |
| SMS | Tenant's SMS provider | More providers |
| Payments | Manual bank transfer (bank details and payment reference format) | Stripe, Windcave, PayPal |
| Search and maps | Places or search API used by competitor intelligence | More providers |

## Settings page (per tenant)

For each connection the tenant sees:

- Provider name and category
- Status: Not set up, Connected, Failed, Expired, Disabled
- Masked key (for example `sk-...a9f2`); the full key is never shown again after saving
- Buttons: Test connection, Rotate key, Disable, Delete
- Last tested time and last error
- Usage this month and estimated cost
- Which modules use this connection (for example "WhatsApp ordering" and "Daily owner summary")
- Primary and backup provider (for AI fallback)

## Security rules

1. Keys are encrypted at rest (envelope encryption: a master key in a key management service or environment secret, plus a key per tenant).
2. Keys are decrypted only on the server, only at the moment of use.
3. Keys never go to the browser, logs, error reports or AI prompts.
4. Only roles with the "Manage integrations" permission can add or change keys.
5. Every add, change, test, rotate and delete is written to the audit log (without the key value).
6. A tenant can never read or use another tenant's keys.
7. Webhook endpoints are unique per tenant and check signatures where the provider supports them.

## Adapter design

Each category has one interface. Modules only talk to the interface, never to a provider directly.

| Interface | Example methods |
|---|---|
| `AIProvider` | `chat()`, `embed()`, `estimate_cost()`, `health_check()` |
| `MessagingChannel` | `send_text()`, `send_template()`, `parse_webhook()`, `health_check()` |
| `PaymentProvider` | `create_invoice_payment()`, `parse_webhook()`, `refund()`, `health_check()` |
| `PlacesSearch` | `search_nearby()`, `get_place()`, `health_check()` |

Adding a new provider means writing one new adapter class and registering it. No module needs to change.

## Usage and cost meter

- Every AI call and outgoing message is recorded as a usage event (tenant, provider, module, tokens or message count, estimated cost, time).
- Tenants see daily and monthly totals and can set a budget limit with alerts at 80% and 100%.
- When the limit is reached, the configured rule applies: stop, ask an admin, or allow and warn.

## Key health checks

- A scheduled job tests each active connection (for example daily).
- If a key fails or expires, the tenant admin gets an in-app alert and an email.
- Failed connections show the reason in plain words.
