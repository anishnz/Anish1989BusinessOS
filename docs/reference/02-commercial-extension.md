# Extension: Commercial, E-commerce, Referral Marketing and Complete Software Requirements Specification

## 1. Objective

Extend the Universal AI ERP, CRM and Multi-Website SaaS Platform with a complete commercial management system.

The platform must support subscription sales, software licences, one-time purchases, add-on modules, product sales, referral programmes, affiliate marketing, recurring billing, shopping carts, checkout, invoicing, coupons, discounts, commissions, renewals, refunds, and revenue analytics.

Support two separate commercial environments:

**Platform commerce:** The platform owner sells subscriptions, licences, AI credits, website plans, modules, implementation services, and add-ons to tenant organisations.

**Tenant commerce:** Each tenant can sell its own products and services, accept bookings, sell courses, manage catering orders, or operate an online store using the enabled modules.

Keep platform billing and tenant business transactions logically separate. Platform Super Admins must not automatically gain access to tenant customers' private payment details.

# 2. SaaS pricing and subscription management

## 2.1 Subscription plans

Create a Subscription and Pricing Management module accessible to authorised Super Admins.

Support configurable plans such as:

- Free or trial plan.
- Starter plan.
- Professional plan.
- Business plan.
- Enterprise plan.
- Custom negotiated plan.
- Lifetime licence, if enabled.
- Educational or nonprofit plan, if enabled.

These are examples, not fixed product tiers. The Super Admin must be able to create, rename, reorder, publish, archive, and modify plans without changing application code.

For every plan, configure:

- Plan name and description.
- Monthly, annual, quarterly, or other supported billing intervals.
- One-time setup fee.
- Regular subscription price.
- Currency and applicable tax settings.
- Number of users and administrators.
- Number of websites and custom domains.
- Enabled modules and premium features.
- Storage, API requests, and AI usage allowances.
- Maximum number of records, workflows, and AI agents where appropriate.
- Support level and service limits.
- Trial duration and eligibility.
- Discount eligibility.
- Renewal and cancellation rules.
- Overage pricing, if supported.
- Grace period and suspension policy.
- Upgrade and downgrade rules.

Show plan comparisons on the public pricing page.

## 2.2 Configurable pricing models

Support the following commercial models:

1. Fixed subscription: a recurring fee for a selected plan.
2. Per-user pricing: charge according to active or licensed users.
3. Per-module pricing: charge for selected optional modules.
4. Usage-based pricing: charge for measurable usage, such as AI tokens, storage, API calls, or messages.
5. Tiered pricing: different prices for defined usage bands.
6. Hybrid pricing: base subscription plus usage or add-on charges.
7. One-time purchase: charge for a licence, template, service, or product.
8. Setup and implementation fees: charge for onboarding, migration, training, or configuration.
9. Enterprise pricing: negotiated limits and contractual terms.
10. Performance-based pricing: support a separately agreed service fee based on verified results, with clear attribution and contract terms.
11. Marketplace pricing: sell approved extensions, templates, integrations, and industry packages.
12. Promotional pricing: apply temporary discounts, coupons, introductory rates, or approved referral rewards.

The billing engine must calculate prices from stored configuration. Do not hardcode pricing logic separately into every module.

## 2.3 Illustrative SaaS price catalogue

Provide editable sample prices for demonstration purposes. These amounts must remain unpublished until approved by the Super Admin.

| Sample plan | Monthly price | Intended use |
|---|---:|---|
| Free | NZ$0 | Evaluation with restricted usage |
| Starter | NZ$29 | Small business |
| Professional | NZ$79 | Growing business |
| Business | NZ$199 | Multi-team operations |
| Enterprise | Custom | Larger organisations |

All figures are illustrative NZD values, excluding any applicable taxes. They are not market quotations or final recommended prices.

Allow annual discounts, per-user fees, premium modules, onboarding fees, and AI usage charges to be configured independently.

## 2.4 Subscription lifecycle

Implement the following lifecycle:

Draft → Published → Trial → Active → Renewal Due → Past Due → Grace Period → Suspended → Cancelled or Expired.

Also support:

- Immediate or end-of-term cancellation.
- Renewal reminders.
- Payment retry policies.
- Failed-payment notifications.
- Subscription upgrades and downgrades.
- Prorated billing where configured.
- Invoice generation.
- Receipts and payment history.
- Refund requests and approval.
- Credit notes and account credits.
- Reactivation after suspension.
- Plan migration.
- Subscription pause, where supported.
- Export of subscription and invoice data.

All subscription state changes must be recorded in the audit log.

## 2.5 Licence enforcement

Every tenant must have a licence record that identifies:

- Tenant ID.
- Subscription and plan ID.
- Start and expiry dates.
- Enabled modules.
- User, website, storage, and usage limits.
- Trial or paid status.
- Renewal status.
- Payment status.
- Suspension reason, if applicable.

Enforce these limits on the server side. Hiding a feature in the user interface is not sufficient.

When a subscription expires, apply the configured grace and suspension policy. Preserve customer data according to the retention policy and provide authorised export or recovery procedures.

# 3. E-commerce and add-to-cart system

## 3.1 Product and service catalogue

Build a reusable commerce module that tenants can enable for their own websites.

Support:

- Physical products.
- Digital products and downloadable files.
- Software licences.
- Subscriptions.
- Courses and educational services.
- Consulting and professional services.
- Catering packages.
- Event bookings.
- Appointment-based services.
- Bundles and configurable products.

Each product or service must support:

- Name, SKU, description, category, images, and attributes.
- Price, currency, tax category, and discount eligibility.
- Variants, options, and add-ons.
- Inventory or service availability.
- Delivery, pickup, or fulfilment settings.
- Publication status.
- SEO information.
- Terms and cancellation policies.
- Related products and recommended products.
- Sales reports and conversion tracking.

## 3.2 Shopping cart

Implement a fully functional cart with:

- Add to cart.
- Remove item.
- Change quantity.
- Update product options.
- Save cart between sessions where appropriate.
- Display item prices, subtotals, discounts, shipping, tax, and final total.
- Apply valid coupon codes.
- Apply eligible referral discounts.
- Validate product availability and current prices.
- Save cart for authenticated users.
- Support guest checkout when permitted.
- Recover abandoned carts with appropriate consent and notification settings.

Recalculate prices, discounts, stock availability, and tax on the server during checkout. Never trust totals supplied by the browser.

## 3.3 Checkout and order management

Create a checkout workflow:

Cart → Customer Details → Delivery or Fulfilment → Payment → Order Confirmation → Fulfilment → Completion.

Support:

- Guest and registered-customer checkout.
- Customer addresses and contact information.
- Billing and delivery addresses.
- Pickup, delivery, digital fulfilment, and booking-specific fulfilment.
- Order notes.
- Coupon and referral validation.
- Payment provider redirects or secure payment components.
- Order confirmation and receipts.
- Order history and status tracking.
- Cancellations, refunds, exchanges, and returns where relevant.
- Partial fulfilment and partial refunds where supported.
- Staff order management.
- Customer support links.
- Automated email or other configured notifications.

Use an appropriate payment provider such as Stripe or another supported provider. Store provider transaction references rather than raw card details. Use signed webhooks and idempotent payment processing to avoid duplicate orders or charges.

## 3.4 Tenant-specific commerce settings

Every tenant must be able to configure its own:

- Storefront and product catalogue.
- Currency and tax rules.
- Prices and discount policies.
- Shipping and pickup options.
- Payment provider account.
- Order workflow.
- Customer notifications.
- Refund and cancellation rules.
- Branding and domain.
- Terms and privacy information.
- Sales reports.

One tenant must never receive another tenant's orders, customers, payment references, or commercial reports.

# 4. Referral and affiliate marketing

Create a dedicated Referral and Affiliate Management module.

## 4.1 Referral programmes

Allow the platform owner and authorised tenants to create referral programmes independently.

Support:

- Referral links.
- Referral codes.
- Invitation codes.
- QR referral codes.
- Campaign-specific referral URLs.
- Referral landing pages.
- Optional social sharing.
- Referral registration tracking.
- Referral-to-lead and referral-to-customer attribution.
- First-touch, last-touch, or configured attribution models.
- Attribution windows.
- Referral conversion reports.

Every referral code must have a unique identifier, an owner, a programme, and an eligibility policy.

## 4.2 Referral rewards

Support configurable rewards such as:

- Percentage commission.
- Fixed cash commission.
- Account credit.
- Subscription discount.
- Free subscription period.
- AI usage credits.
- One-time product discount.
- Recurring commission for a defined period.
- Tier-based rewards.
- Non-cash promotional rewards.

For each programme, configure the reward amount, currency, qualifying action, eligible products, attribution window, commission cap, payment schedule, refund treatment, and eligibility conditions.

Example:

An affiliate refers a business that purchases a NZ$79 monthly subscription. A programme offers a 15% recurring commission for the first six eligible months.

Illustrative commission: NZ$11.85 per eligible monthly payment before adjustments, assuming the commission is calculated on the full NZ$79 subscription amount.

Define whether tax, refunds, discounts, and payment processing fees are excluded from the commission base.

## 4.3 Referral programme workflow

1. An administrator creates a referral programme.
2. The programme defines its terms and eligibility rules.
3. A customer or affiliate registers.
4. The system generates a unique referral link and code.
5. A prospect visits through that link.
6. The system records attribution according to the configured rules.
7. The prospect registers, purchases, or subscribes.
8. The system verifies the qualifying transaction.
9. The commission enters a Pending state.
10. The qualifying period and refund checks complete.
11. The commission becomes Approved.
12. The commission is paid or credited according to the programme.
13. The transaction and status changes are recorded in an auditable ledger.

Do not mark a referral as payable merely because someone clicked a link or created an account.

## 4.4 Affiliate dashboard

Provide affiliates with:

- Referral link and QR code.
- Referral clicks and registrations.
- Qualified leads.
- Conversion rate.
- Completed purchases.
- Pending, approved, reversed, and paid commissions.
- Available account credit.
- Payment history.
- Programme terms.
- Marketing materials.
- Referral campaign performance.
- Exportable statements.

Protect personal information and show only the referral details an affiliate is permitted to access.

## 4.5 Fraud prevention and referral controls

Implement:

- Duplicate referral detection.
- Self-referral restrictions where appropriate.
- Suspicious signup and transaction detection.
- Rate limiting and abuse prevention.
- Commission reversal after eligible refunds or chargebacks.
- Manual review queues.
- Programme-specific caps and exclusions.
- Payment verification before rewards become payable.
- A complete commission ledger.

Do not rely on IP address alone to establish fraud. Provide appeal and review processes for legitimate referrals flagged by automated controls.

## 4.6 Multi-level referral programmes

Allow optional multi-level referral programmes only when explicitly enabled and legally reviewed.

Configure permitted levels, reward percentages, caps, qualifying transactions, and eligibility requirements.

The system must not pay commissions solely for recruiting participants. Rewards must be tied to legitimate qualifying purchases or services, and the programme must comply with applicable laws.

# 5. Coupons, promotions and loyalty

Create a Promotion Management Centre with:

- Percentage and fixed-value coupons.
- Product-specific and category-specific discounts.
- First-purchase offers.
- Subscription introductory offers.
- Annual billing discounts.
- Referral discounts.
- Bundle pricing.
- Loyalty points and account credit.
- Limited-time campaigns.
- Minimum order requirements.
- Usage limits per code and customer.
- Start and expiry dates.
- Customer-segment restrictions.
- Promotion approval and audit history.

Define whether discounts can be combined. Calculate discounts in a deterministic order and show the calculation in checkout.

Prevent users from applying expired, invalid, exhausted, or ineligible promotions.

# 6. Complete functional requirements catalogue

Assign each requirement a unique ID, priority, implementation status, owner, and acceptance test.

Use these priorities:

- P0: Mandatory for the initial secure production foundation.
- P1: Required for the first commercial release.
- P2: Advanced functionality for later releases.

## 6.1 Platform administration

| ID | Requirement | Priority |
|---|---|---|
| FR-001 | Secure login, logout, password recovery, and session management | P0 |
| FR-002 | Create, update, suspend, and manage tenants | P0 |
| FR-003 | Create and manage licences, plans, and tenant limits | P0 |
| FR-004 | Enforce role-based permissions on backend APIs | P0 |
| FR-005 | Record administrative and security audit events | P0 |
| FR-006 | Create System Admin and IT Admin accounts according to hierarchy | P0 |
| FR-007 | Configure tenant modules and sub-account access | P0 |
| FR-008 | Manage custom dashboards and widget permissions | P1 |
| FR-009 | Configure tenant-specific branding and themes | P1 |
| FR-010 | Monitor platform usage, errors, and service health | P1 |

## 6.2 Billing and subscriptions

| ID | Requirement | Priority |
|---|---|---|
| FR-011 | Create and publish configurable subscription plans | P1 |
| FR-012 | Display plan comparison and pricing pages | P1 |
| FR-013 | Support monthly and annual subscriptions | P1 |
| FR-014 | Create checkout sessions for subscription purchases | P1 |
| FR-015 | Generate invoices and receipts | P1 |
| FR-016 | Process verified payment webhooks safely | P1 |
| FR-017 | Manage renewals, cancellations, and failed payments | P1 |
| FR-018 | Upgrade, downgrade, and migrate plans | P1 |
| FR-019 | Enforce module and usage limits | P0 |
| FR-020 | Support refunds, credits, and subscription history | P1 |
| FR-021 | Support usage-based billing and overages | P2 |
| FR-022 | Support enterprise contracts and negotiated plans | P2 |

## 6.3 E-commerce

| ID | Requirement | Priority |
|---|---|---|
| FR-023 | Manage product and service catalogues | P1 |
| FR-024 | Add, update, and remove cart items | P1 |
| FR-025 | Recalculate prices, discounts, and tax on the server | P1 |
| FR-026 | Complete checkout using a supported payment provider | P1 |
| FR-027 | Manage customer orders and order statuses | P1 |
| FR-028 | Send order confirmations and receipts | P1 |
| FR-029 | Manage fulfilment, cancellations, and eligible refunds | P1 |
| FR-030 | Support digital products and service bookings | P2 |
| FR-031 | Recover abandoned carts with appropriate consent | P2 |
| FR-032 | Manage multiple tenant storefronts | P1 |

## 6.4 Referral and marketing

| ID | Requirement | Priority |
|---|---|---|
| FR-033 | Create referral programmes and eligibility rules | P1 |
| FR-034 | Generate referral links, codes, and QR codes | P1 |
| FR-035 | Attribute qualified purchases to eligible referrals | P1 |
| FR-036 | Calculate commissions and maintain a ledger | P1 |
| FR-037 | Manage approval, reversal, and payout workflows | P1 |
| FR-038 | Provide affiliate dashboards and statements | P1 |
| FR-039 | Manage coupons and promotional campaigns | P1 |
| FR-040 | Detect suspicious referral activity | P1 |
| FR-041 | Support configurable multi-level referral programmes | P2 |
| FR-042 | Track marketing campaigns and conversion rates | P1 |

## 6.5 ERP, CRM and AI

| ID | Requirement | Priority |
|---|---|---|
| FR-043 | Manage CRM contacts, leads, and sales opportunities | P1 |
| FR-044 | Manage products, inventory, and purchasing | P1 |
| FR-045 | Manage employees, shifts, and attendance | P1 |
| FR-046 | Generate business reports and KPI dashboards | P1 |
| FR-047 | Generate AI-assisted reports and business documents | P1 |
| FR-048 | Configure AI agents, tools, limits, and approvals | P1 |
| FR-049 | Manage workflows, triggers, conditions, and actions | P1 |
| FR-050 | Maintain AI execution logs and usage records | P1 |
| FR-051 | Build and manage multiple websites | P1 |
| FR-052 | Embed public chatbots with tenant isolation | P1 |
| FR-053 | Search authorised documents and knowledge sources | P1 |
| FR-054 | Integrate approved email, WhatsApp, and social services | P2 |

## 6.6 Platform operations

| ID | Requirement | Priority |
|---|---|---|
| FR-055 | Manage notification preferences and delivery status | P1 |
| FR-056 | Import and export authorised business data | P1 |
| FR-057 | Manage backups and tested recovery procedures | P0 |
| FR-058 | Provide API documentation and integration status | P1 |
| FR-059 | Manage data retention and authorised deletion requests | P0 |
| FR-060 | Provide automated tests for critical workflows | P0 |

# 7. Non-functional requirements

Non-functional requirements describe the quality, security, reliability, and operational limits of the platform.

Treat the targets below as initial engineering goals. Validate them with load testing and adjust them to the hosting environment and commercial service commitments.

## 7.1 Security

- NFR-001: Enforce tenant isolation in all data access, API endpoints, background jobs, search indexes, file downloads, and AI retrieval.
- NFR-002: Apply least-privilege access and deny access by default.
- NFR-003: Protect privileged accounts with MFA.
- NFR-004: Store passwords using a modern password hashing algorithm and protect secrets using approved secret storage.
- NFR-005: Encrypt network traffic and sensitive stored data where appropriate.
- NFR-006: Validate inputs, control file uploads, and defend against common web vulnerabilities.
- NFR-007: Maintain tamper-resistant audit records and restrict log access.
- NFR-008: Protect payment operations using a compliant provider and avoid storing raw payment card data.
- NFR-009: Scan dependencies, test access controls, and review security changes before production.
- NFR-010: Protect AI agents against prompt injection, unauthorised tools, data leakage, and cross-tenant retrieval.

## 7.2 Performance

- NFR-011: Target a 95th-percentile response time below 2 seconds for common interactive operations under the agreed test load, excluding external provider delays and long-running AI tasks.
- NFR-012: Use pagination, indexed queries, caching where appropriate, and efficient database access.
- NFR-013: Run long-running imports, AI jobs, report generation, and integration tasks asynchronously.
- NFR-014: Display progress, errors, and retry status for asynchronous jobs.
- NFR-015: Establish and test capacity limits for concurrent users, API requests, and background tasks.

## 7.3 Availability and recovery

- NFR-016: Define a production availability target, initially 99.5% monthly, subject to infrastructure and operational design.
- NFR-017: Monitor application health, database health, background workers, and external integrations.
- NFR-018: Back up databases and critical configuration regularly.
- NFR-019: Test restoration rather than assuming backups are usable.
- NFR-020: Define recovery time objective (RTO) and recovery point objective (RPO) before production launch.

## 7.4 Scalability and maintainability

- NFR-021: Use modular services and documented interfaces so new modules can be added without rewriting unrelated functionality.
- NFR-022: Separate tenant data and configuration from global platform settings.
- NFR-023: Use versioned database migrations and controlled deployment procedures.
- NFR-024: Keep secrets, environment-specific settings, and integration credentials out of source code.
- NFR-025: Maintain automated unit, integration, API, permission, and end-to-end tests.
- NFR-026: Use structured logs, metrics, traces where supported, and actionable error reports.

## 7.5 Usability and accessibility

- NFR-027: Support responsive desktop, tablet, and mobile layouts.
- NFR-028: Use consistent navigation, forms, error messages, and interaction patterns.
- NFR-029: Support keyboard navigation and accessible labels.
- NFR-030: Aim for WCAG 2.2 AA accessibility where applicable.
- NFR-031: Provide clear loading, empty, success, and error states.
- NFR-032: Make administrative actions understandable and confirm destructive operations.

## 7.6 Privacy and compliance

- NFR-033: Collect only the personal information needed for defined business purposes.
- NFR-034: Enforce configurable retention, access, correction, export, and deletion workflows.
- NFR-035: Record consent and communication preferences where required.
- NFR-036: Apply relevant New Zealand privacy, tax, consumer, electronic communications, and employment requirements where applicable, along with requirements for other operating jurisdictions.
- NFR-037: Establish appropriate contractual and technical controls for third-party AI and integration providers.
- NFR-038: Provide configurable data residency and retention controls where supported by the selected infrastructure.

## 7.7 AI reliability and governance

- NFR-039: Identify AI-generated content and preserve its source references where relevant.
- NFR-040: Require human approval for configured high-impact actions.
- NFR-041: Track model, prompt version, execution status, usage, cost, and relevant outputs.
- NFR-042: Apply per-tenant AI budgets, quotas, rate limits, and timeout policies.
- NFR-043: Provide graceful handling when an AI provider is unavailable.
- NFR-044: Do not treat AI-generated answers as verified facts without appropriate validation.
- NFR-045: Prevent public chatbots and AI agents from accessing unauthorised records or executing unrestricted tools.

## 7.8 Financial accuracy

- NFR-046: Use decimal-safe monetary calculations and explicit currency handling.
- NFR-047: Store transaction and invoice history with clear status changes.
- NFR-048: Use idempotency controls to prevent duplicate payments, orders, commissions, and webhook processing.
- NFR-049: Reconcile payment provider events against internal transaction records.
- NFR-050: Record commission calculations, reversals, adjustments, refunds, and payouts in an auditable ledger.

# 8. Roles and permission model

Implement role-based access control (RBAC), supplemented by tenant scope, organisational scope, resource ownership, and contextual rules where necessary.

## 8.1 Role hierarchy

| Role | Main responsibility |
|---|---|
| Super Admin | Global platform, tenants, licences, global permissions and policies |
| Platform Billing Admin | Platform subscriptions, invoices, payments and revenue reports |
| Platform Security Admin | Global security configuration and security monitoring |
| System Admin | Organisation configuration, modules, users and tenant settings |
| IT Admin | Technical configuration, integrations and approved security operations |
| Business Owner | Business operations, reports and delegated administration |
| Department Admin | Administration of assigned department |
| Manager | Team, approvals, assignments and reports |
| Sales Manager | Sales pipeline, targets and sales team |
| Sales Representative | Assigned leads, contacts and opportunities |
| Marketing Manager | Campaigns, audiences and marketing workflows |
| Marketing Staff | Permitted content and campaign tasks |
| Finance Manager | Financial records, reporting and approvals |
| Accountant | Invoices, expenses, reconciliation and authorised financial operations |
| HR Manager | Employee records, attendance, leave and rosters |
| HR Staff | Permitted HR tasks and employee data |
| Inventory Manager | Stock, warehouses, purchasing and stock reports |
| Operations Manager | Projects, operations, bookings and workflows |
| Content Manager | Websites, pages, media and publishing workflows |
| AI Manager | AI agents, budgets, knowledge sources and approval rules |
| Support Agent | Assigned customer support tickets |
| Customer | Own profile, orders, invoices and support requests |
| Supplier | Own supplier profile and authorised purchase-order information |
| Affiliate | Own referral links, eligible referrals and commission statements |
| Employee | Own profile, attendance, shifts and authorised tasks |
| Auditor | Read-only access to explicitly assigned audit and business records |
| Student or Learner | Own courses, learning resources, assessments and progress |
| Teacher or Trainer | Assigned courses, students, learning resources and assessments |

Roles must be configurable and may be combined where permitted. The hierarchy defines default authority; it must not grant unrestricted access to every record.

## 8.2 Permission actions

Implement these independent permission actions:

- View.
- Create.
- Edit.
- Delete or archive.
- Approve or reject.
- Publish.
- Export or download.
- Import.
- Assign or delegate.
- Configure.
- Administer.
- Manage permissions.
- Manage billing.
- Execute AI tools.
- Approve AI actions.
- Manage integrations.
- View audit records.

## 8.3 Permission matrix

Legend: A = full administration within authorised scope; E = edit or operate assigned records; V = read-only; O = own records only; P = approval authority; C = configurable or conditional; – = no default access.

| Module | Super Admin | System Admin | IT Admin | Manager | Staff | Customer / Affiliate |
|---|---|---|---|---|---|---|
| Tenant and licence management | A | V/C | – | – | – | – |
| Global roles and policies | A | C | C | – | – | – |
| Tenant users and departments | A | A | C | C | – | – |
| Module and feature settings | A | C | C | – | – | – |
| Dashboard configuration | A | A/C | C | C | O/C | O/C |
| CRM and sales | C | C | – | A/C | E/C | O |
| Marketing and campaigns | C | C | – | A/C | E/C | O/C |
| Finance and billing | Platform scope | Tenant scope | Technical only | P/C | E/C | O |
| Inventory and purchasing | C | C | – | A/C | E/C | O/C |
| HR and attendance | C | C | Technical only | A/C | O/C | O |
| Websites and content | C | C | Technical only | A/C | E/C | O/C |
| AI agents and workflows | C | C | Technical only | C | E/C | O/C |
| Integrations and credentials | C | C | A/C | – | – | – |
| Audit and security | A | C | C | C | – | – |
| Referral programme configuration | A | C | – | C | – | – |
| Own affiliate dashboard | – | – | – | – | – | O |
| Own shopping cart and orders | – | – | – | – | – | O |
| Support tickets | C | C | C | A/C | E/C | O |

The matrix is a starting policy, not a substitute for detailed permissions.

Important restrictions:

1. Platform Billing Admin receives platform billing permissions, not automatic access to every tenant's finance data.
2. IT Admin cannot automatically change business ownership, override global policies, or grant themselves additional privileges.
3. Finance staff cannot approve their own high-risk transactions unless an explicitly approved policy permits it.
4. Affiliates can view their own referral records and commissions, not other affiliates' records or referred customers' private information.
5. Customers can view their own orders and invoices only.
6. Managers can access only their assigned teams, departments, branches, and approved records.
7. Auditors receive read-only access and cannot change records under review.
8. Super Admin access to tenant data must follow an explicit, logged administrative policy.
9. Public website visitors must never receive backend administrative permissions.

## 8.4 Permission evaluation

For every protected action, evaluate:

1. Is the account active and authenticated?
2. Is the tenant and licence valid for the requested operation?
3. Is the requested module enabled?
4. Does the role grant the required action?
5. Does the user have access to the requested tenant, department, branch, or record?
6. Are there explicit restrictions or approval requirements?
7. Is the requested action permitted under the current business state?

Deny access when the policy cannot establish permission. Apply the same checks to direct API calls, background tasks, exports, file access, and AI tool execution.

# 9. Data entities to add

Extend the database schema with the following entities:

### Commercial and subscription data

- PricingPlan.
- PricingPlanVersion.
- Subscription.
- SubscriptionItem.
- LicenceEntitlement.
- UsageMeter.
- UsageEvent.
- Invoice.
- InvoiceLine.
- PaymentTransaction.
- PaymentWebhookEvent.
- CreditNote.
- Refund.
- TaxConfiguration.
- BillingAddress.

### E-commerce data

- Store.
- Product.
- ProductVariant.
- ProductPrice.
- ProductImage.
- ShoppingCart.
- CartItem.
- CheckoutSession.
- Order.
- OrderItem.
- Fulfilment.
- Shipment.
- Coupon.
- Promotion.
- PromotionRedemption.
- ReturnRequest.

### Referral and affiliate data

- ReferralProgramme.
- ReferralParticipant.
- ReferralCode.
- ReferralClick.
- ReferralAttribution.
- ReferralConversion.
- CommissionRule.
- CommissionLedgerEntry.
- PayoutRequest.
- PayoutTransaction.
- FraudReview.

Every tenant-owned entity must include an enforceable tenant scope. Use immutable transaction identifiers, timestamps, status histories, and appropriate relationships.

Do not store raw payment card details or unnecessary sensitive customer information in the referral ledger.

# 10. Critical acceptance tests

The commercial platform must pass the following tests before production release.

1. A visitor can compare plans, select a subscription, complete checkout, and receive a valid subscription only after payment verification.
2. A failed payment does not activate paid entitlements.
3. A renewal does not create duplicate invoices or charges when a webhook is delivered repeatedly.
4. An expired licence correctly applies the configured grace and suspension rules.
5. A customer can add products to a cart, change quantities, apply an eligible coupon, and complete checkout.
6. Tampering with a client-side price does not alter the final server-calculated amount.
7. Stock cannot be oversold beyond the configured reservation and inventory rules.
8. A referral is attributed according to the published programme rules.
9. Duplicate, ineligible, fraudulent, refunded, or reversed transactions do not generate unjustified commission payouts.
10. Affiliates cannot inspect another affiliate's customers or commissions.
11. Commission totals reconcile with their ledger entries and payout transactions.
12. A tenant cannot access another tenant's billing, products, customers, orders, or reports.
13. A user cannot gain additional permissions by editing a browser request.
14. High-impact AI actions follow the required approval workflow.
15. Audit events record subscription changes, permission changes, refunds, commission approvals, and administrative overrides.
16. Backup restoration preserves commercial records and audit relationships.
17. Accessibility and performance tests meet the agreed targets under representative workloads.

# 11. Delivery priorities

## Release 1: Secure commercial foundation

Deliver tenant isolation, account hierarchy, role and permission management, licences, pricing plans, basic subscriptions, audit logging, and automated access-control tests.

## Release 2: Sales and commerce

Deliver public pricing pages, checkout, products, shopping carts, orders, invoices, payment integration, and subscription renewals.

## Release 3: Referral and promotional engine

Deliver referral links, codes, attribution, commission calculations, coupons, affiliate dashboards, approval workflows, and fraud controls.

## Release 4: ERP and AI automation

Integrate commercial data with CRM, BI, AI agents, marketing automation, document generation, and tenant-specific workflows.

## Release 5: Advanced operations

Deliver usage-based billing, marketplace extensions, advanced reporting, enterprise contracts, advanced referral models, and additional integrations.

For every release, provide database migrations, backend APIs, frontend screens, automated tests, security checks, setup instructions, and a list of completed and incomplete features.

Do not mark a requirement complete until its backend behaviour and acceptance tests work. Keep demo data clearly identified, use configurable prices, and never claim that a payment, subscription, integration, or payout is operational until it has been tested against the actual configured provider.