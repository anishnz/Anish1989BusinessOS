# 03. Feature catalogue

Last updated: 21 October 2026

Every module and feature in scope. Phases follow the roadmap in [Master spec v2.0](reference/03-master-spec-v2.0.md) and will be finalised during planning.

**Phase key:** P0 = secure foundation, P1 = first commercial release, P2 = later.

## 1. Multi-tenant core

| Feature | Description | Phase |
|---|---|---|
| Authentication | Login, logout, password recovery, sessions, MFA for admins | P0 |
| Tenants and licences | Create, suspend and renew tenants; plan limits | P0 |
| Roles and permissions | Role-based access checked on every API call (deny by default) | P0 |
| Module registry | Turn modules on or off per tenant | P0 |
| Audit log | Record important actions, who did them and when | P0 |
| Onboarding wizard | New tenant picks an industry template, imports products by CSV, connects keys step by step | P1 |
| Sandbox mode | Test keys and workflows with no real customers or money | P1 |
| Data export and offboarding | A tenant can download all its data if it leaves | P0 |

## 2. Settings and secret vault

See [04. Tenant settings and secret vault](04-tenant-settings-and-secrets.md).

| Feature | Description | Phase |
|---|---|---|
| Own API keys | Tenants add AI, messaging and payment keys themselves | P1 |
| Key health checks | "Test connection" button; alerts when a key fails, expires or hits a limit | P1 |
| Usage and cost meter | Shows how much AI and messaging each tenant used | P1 |
| AI fallback provider | If the main AI provider fails, switch to the tenant's backup provider | P2 |

## 3. Adapters, messaging and inbox

| Feature | Description | Phase |
|---|---|---|
| WhatsApp Business adapter | Official WhatsApp Business Platform (Cloud API) or an authorised partner | P1 |
| Viber, Telegram adapters | Business messaging bots | P1 |
| Email and SMS adapters | Tenant's own email and SMS provider | P1 |
| Unified inbox | All channels in one screen for staff, with assignment and notes | P1 |
| Tenant API and webhooks | Tenants connect their own tools to the platform | P2 |

## 4. WhatsApp AI ordering

See [05. WhatsApp AI ordering](05-whatsapp-ai-ordering.md).

| Feature | Description | Phase |
|---|---|---|
| QR to WhatsApp | Customer scans a shop QR code and the chat opens | P1 |
| OTP verification | Verify the customer with a one-time code | P1 |
| AI order taking | AI understands products and quantities from chat | P1 |
| Confirm before recording | Order stays a draft until the customer confirms | P1 |
| Weight-based final price | Staff enter the real weight; customer accepts the final price | P1 |
| Stock-aware AI | AI checks live stock and suggests alternatives | P1 |
| Quick reorder | "Same as last week" rebuilds the last order | P1 |
| Order status updates | Received, being prepared, ready for pickup | P1 |
| Pickup time slots | Customer picks a time; shop sets capacity per slot | P1 |
| Human handover | Staff take over when AI is unsure or the customer is upset | P1 |

## 5. Business modules

| Module | Main features | Phase |
|---|---|---|
| CRM and sales | Contacts, leads, pipeline, activities, follow-ups | P1 |
| Products and inventory | SKU, cost and sell price, stock, kg/pack/item units, suppliers, wastage, reorder alerts | P1 |
| Sales records | CSV or POS import, discounts, refunds | P1 |
| Subscriptions and billing | Plans, 30-day trial, hybrid pricing, invoices | P1 |
| Bank reconciliation | Bank CSV import, matching by reference, review queue | P1 |
| Commerce | Catalogue, cart, checkout, orders, coupons | P1 |
| Referral and rewards | Referral links, codes, QR, commission ledger | P1 |
| QR loyalty and games | Unique expiring coupons first, games later | P2 |
| HR and attendance | Employees, shifts, QR check-in | P1 |
| Websites and chatbot | Multiple websites, themes, public AI chatbot | P1 |
| Staff mobile app (PWA) | Handle orders and scan QR attendance on a phone | P2 |

## 6. AI layer

| Feature | Description | Phase |
|---|---|---|
| AI Agent Studio | Create and configure agents | P1 |
| Multiple AI providers | OpenAI, Claude, Gemini, local models; tenant's own key | P1 |
| Tool permissions | Each agent can only use approved tools | P1 |
| Approval queue | Humans approve refunds, payments, publishing, purchases | P1 |
| Cost limits | Per-tenant AI budget and rate limits | P1 |

## 7. Business intelligence

See [06. Business intelligence](06-business-intelligence.md).

| Feature | Description | Phase |
|---|---|---|
| Dashboards and many chart types | Drag-and-drop dashboards, drill-down, export | P1 |
| Customer response analytics | NPS, CSAT, reviews, chat replies, campaign results | P1 |
| Post-order feedback | 1 to 5 star rating by WhatsApp after each order | P1 |
| Customer segments | Loyal, new, at risk, lost (RFM) | P1 |
| Basket analysis | Products bought together | P2 |
| Demand forecast | Expected sales next week, to reduce wastage | P2 |
| Anomaly alerts | For example "Sales are 30% lower than a normal Tuesday" | P2 |
| Daily owner summary | Sales, top products and low stock sent by WhatsApp each evening | P1 |

## 8. Competitor intelligence

See [07. Competitor intelligence](07-competitor-intelligence.md).

| Feature | Description | Phase |
|---|---|---|
| Location search | Owner chooses suburb, city or radius | P2 |
| Find similar businesses | Search for competitors in that area | P2 |
| Crawl public websites | Collect prices, products, offers, hours | P2 |
| Ask the AI | "Check my competitors near Papatoetoe" | P2 |
| Weekly report | Automatic report showing changes since last week | P2 |
| Logs and history | Every search, crawl, result and report saved | P2 |

## 9. Learning and jobs

See [09. Industry templates](09-industry-templates.md).

| Feature | Description | Phase |
|---|---|---|
| Courses and lessons | Lessons with embedded YouTube videos, links and PDFs | P1 |
| Quizzes and progress | Assessments, completion tracking, certificates | P1 |
| Job board | Employers post jobs with location, type and pay range | P1 |
| Job listings by location | Auckland jobs on a map and list, from legal sources only | P1 |
| ATS-friendly resume builder | Simple templates, PDF and DOCX export, keyword check | P1 |
| Applications and job alerts | Apply online; opt-in alerts by email or WhatsApp | P1 |

## 10. Security and compliance

| Feature | Description | Phase |
|---|---|---|
| MFA, encryption, tenant isolation | Core protections | P0 |
| Consent log and STOP opt-out | Customers type STOP to stop marketing (NZ messaging rules) | P1 |
| Backups and tested restore | Regular backups and restore tests | P0 |
| Automated tests and CI/CD | Permission, isolation and critical workflow tests | P0 |
| Monitoring and alerts | Errors, workers, integrations | P1 |
