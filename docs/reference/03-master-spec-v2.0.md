# Universal AI ERP/CRM, SaaS, E-commerce and Business Automation Platform
## Master Product Requirements and Technical Specification — Version 2.0

**Status:** Requirements approved for planning; implementation and external integrations remain unverified until tested.

**Primary billing currency:** NZD

**Commercial model:** Hybrid subscriptions, paid modules and usage-based charges

**Trial:** 30 days, subject to configurable eligibility rules

**Referral commission:** Illustrative 15% recurring commission for a configurable, limited period

**Initial payment process:** Manual invoicing and bank-transfer reconciliation

**Commerce scope:** Platform-owner commerce and tenant-specific commerce

---

# 1. Product vision

Build a configurable, multi-tenant, AI-powered business platform that combines SaaS subscription management, ERP, CRM, e-commerce, referral marketing, business intelligence, AI agents, multi-website management, workforce management and industry-specific business applications.

The platform should allow an administrator to create and customise business systems using backend configuration rather than rebuilding the application for every industry.

Examples include:

- Educational consultancy ERP.
- Catering and hospitality ERP.
- E-commerce and inventory management.
- Education and learning management.
- Professional services CRM.
- Marketing and sales automation.
- Event planning and management.
- Retail and distribution.
- Project and service management.

New industries must be introduced through configurable modules, workflows, forms, dashboards, permissions and templates wherever practical.

## 1.1 Two independent business environments

### A. Platform-owner business

The platform owner sells subscriptions, licences, modules, AI usage, templates, implementation services and other approved products to tenant organisations.

The platform owner manages global plans, platform billing, tenant licences, global policies and platform-level referral programmes.

### B. Tenant business

Each tenant can operate its own business, customers, products, storefront, sales pipeline, staff, marketing campaigns, orders, bookings, invoices and referral programme according to its enabled modules.

Tenant commerce and platform commerce must remain logically separated. A platform administrator's ability to manage SaaS subscriptions must not automatically expose all tenant financial records or customer data.

---

# 2. Confirmed commercial configuration

| Setting | Required behaviour |
|---|---|
| Default billing currency | NZD |
| Pricing model | Base subscription + optional paid modules + usage-based charges |
| Trial | 30 days |
| Referral reward | Recurring commission for a limited configured period |
| Illustrative referral rate | 15% of eligible commissionable revenue |
| Initial payment method | Manual invoicing and bank-transfer reconciliation |
| Commerce environments | Platform-owner and tenant-specific commerce |
| Prices | Configurable; no fixed hardcoded production prices |
| Automated payment gateway | Pending until separately configured and tested |
| External integrations | Pending until credentials, permissions and end-to-end tests are completed |

Use NZD as the default currency. Support additional currencies only through an explicit configuration that defines exchange-rate handling, rounding, tax treatment and reporting currency.

All examples in this specification are planning values, not approved commercial offers.

# 3. User types and administration hierarchy

## 3.1 Platform-level roles

### Super Admin

Can manage:

- Tenant creation, suspension and deletion workflows.
- Subscription plans and global pricing rules.
- Licence policies and usage limits.
- Global role definitions and permission policies.
- Module catalogue and industry templates.
- Platform-level referrals and affiliate programmes.
- Platform security settings.
- Platform audit logs and service health.
- Global AI-provider configuration and cost limits.
- Approved platform-wide branding and website settings.

Destructive actions and access to sensitive tenant data must be governed by explicit policies, confirmation steps and audit logging.

### Platform Billing Administrator

Can manage platform subscription invoices, payment records, bank reconciliation, subscription adjustments, refunds or credit notes where authorised, and platform revenue reports.

Cannot automatically access tenant-specific accounting data.

### Platform Security Administrator

Can review security events, manage approved security settings, investigate access issues and respond to incidents.

Cannot silently bypass access controls or alter financial records.

### Platform Support Administrator

Can manage support tickets, authorised tenant support operations and troubleshooting.

Any temporary access to tenant data must be limited, justified, time-bound and logged.

## 3.2 Tenant-level roles

Each tenant may have:

- System Admin.
- IT Admin.
- Business Owner.
- Department Admin.
- Department Manager.
- Sales Manager.
- Sales Representative.
- Marketing Manager.
- Marketing Staff.
- Finance Manager.
- Accountant.
- HR Manager.
- HR Staff.
- Inventory Manager.
- Operations Manager.
- Content Manager.
- AI Manager.
- Support Agent.
- Employee.
- Customer.
- Supplier.
- Affiliate.
- Student or Learner.
- Teacher or Trainer.
- Auditor.

The tenant's System Admin can manage users and assign authorised roles within that tenant. IT Admin can manage technical settings and integrations that have been delegated to them.

Tenant administrators cannot grant themselves global platform privileges.

## 3.3 Custom roles

Allow authorised administrators to create custom roles, for example:

- Catering Event Coordinator.
- Educational Consultant.
- Course Assessor.
- Warehouse Supervisor.
- Marketing Analyst.
- Referral Programme Manager.
- AI Workflow Approver.

Custom roles must reuse the platform's permission framework and remain subject to tenant scope, licence limits and global security rules.

---

# 4. Role and permission requirements

## 4.1 Supported permission actions

Every module must support applicable combinations of:

1. View.
2. Create.
3. Edit.
4. Delete or archive.
5. Approve or reject.
6. Publish.
7. Export or download.
8. Import.
9. Assign or delegate.
10. Configure.
11. Administer.
12. Manage permissions.
13. Manage billing.
14. Execute AI tools.
15. Approve AI actions.
16. Manage integrations.
17. View audit logs.

Permission evaluation must occur on the backend for every protected operation.

## 4.2 Default permission matrix

Legend: **A** = administer within authorised scope; **E** = operate or edit assigned records; **V** = read-only; **O** = own records only; **P** = approval authority; **C** = conditional or delegated; **—** = no default access.

| Module | Super Admin | Platform Billing Admin | System Admin | IT Admin | Manager | Staff | Customer/Affiliate |
|---|---|---|---|---|---|---|---|
| Global tenants and licences | A | V/C | — | — | — | — | — |
| Platform subscriptions | A | A | — | — | — | — | O |
| Tenant users and roles | C | — | A/C | C | C | — | — |
| Tenant module configuration | C | — | A/C | C | C | — | — |
| CRM and sales | C | — | C | — | A/C | E/C | O |
| Marketing campaigns | C | — | C | — | A/C | E/C | O/C |
| Tenant finance | C, audited | — | C | — | P/C | E/C | O |
| Inventory and procurement | C | — | C | — | A/C | E/C | O/C |
| HR and attendance | C | — | C | C | A/C | O/C | O |
| Websites and content | C | — | C | C | A/C | E/C | O/C |
| AI agents and workflows | C | — | C | C | C | E/C | O/C |
| Integrations and credentials | C | C for billing systems | C | A/C | — | — | — |
| Security and audit | A | C for billing | C | C | C | — | — |
| Platform referral programmes | A | C | — | — | — | — | O |
| Tenant referral programmes | C | — | C | — | A/C | E/C | O |
| Affiliate commissions | C | C for platform payouts | C for tenant payouts | — | P/C | — | O |
| Shopping cart and orders | C | — | C | — | A/C | E/C | O |
| Own account and documents | C | C for platform invoices | C | — | O | O | O |

This matrix defines default access, not unlimited access. Each permission must also be scoped to the relevant tenant, department, branch, team, resource or record.

## 4.3 Mandatory access rules

- Platform Billing Admin cannot automatically view every tenant's invoices or accounting records.
- Finance users cannot approve their own high-risk financial transactions unless a documented policy explicitly permits it.
- Affiliates can view only their own referral performance and commission statements.
- Customers can view only their own orders, invoices and profile information.
- Managers can access only their assigned organisational scope.
- Auditors have read-only access to explicitly assigned records.
- IT Admin cannot grant themselves additional privileges without an authorised approval process.
- AI agents must operate with explicit tool permissions and cannot inherit unrestricted Super Admin access.
- Public website visitors cannot access backend administrative functions.
- Exports, file downloads, background jobs and AI retrieval must enforce the same permissions as ordinary user interfaces.

## 4.4 Permission precedence

Apply these checks in order:

1. Authentication and account status.
2. Tenant and licence status.
3. Module entitlement.
4. Role permission.
5. Tenant, department, team and record scope.
6. Explicit restrictions and approval requirements.
7. Business-state validation.
8. Audit recording for sensitive operations.

Deny access if permission cannot be established.

---

# 5. SaaS plans, licences and hybrid pricing

## 5.1 Plan configuration

The Super Admin must be able to create, edit, publish, archive and compare pricing plans without modifying application code.

Each plan supports:

- Plan name, description and marketing content.
- Monthly, annual and other supported billing periods.
- Configurable base subscription price.
- One-time onboarding or setup fees.
- Included modules.
- Optional paid modules.
- User and administrator limits.
- Website and custom-domain limits.
- Storage limits.
- AI usage allowance.
- API and workflow limits.
- Support level.
- Trial eligibility.
- Discount rules.
- Usage overage rates.
- Renewal and cancellation policies.
- Grace periods and suspension rules.
- Enterprise-specific contract terms.

## 5.2 Illustrative plan catalogue

The following are examples only. All prices must be editable and unpublished until approved.

| Plan | Illustrative monthly base price | Example use |
|---|---:|---|
| Free | NZ$0 | Restricted evaluation |
| Starter | NZ$29 | Small business |
| Professional | NZ$79 | Growing business |
| Business | NZ$199 | Multi-team operations |
| Enterprise | Custom | Negotiated requirements |

Prices are illustrative NZD amounts and exclude applicable taxes unless explicitly configured otherwise.

The system must not assume these prices are market-validated or commercially approved.

## 5.3 Hybrid pricing calculation

The billing engine must support:

**Subscription amount = base plan fee + paid module fees + metered usage charges + applicable setup fees − eligible discounts + applicable taxes and adjustments.**

Implement a clear calculation breakdown for every invoice.

For each billing period:

- Determine the applicable plan and price version.
- Calculate the base subscription fee.
- Calculate each active paid module.
- Calculate usage according to the configured metering period.
- Apply usage allowances and overage rates.
- Apply eligible discounts and credits.
- Calculate tax according to the configured rules.
- Apply approved adjustments and credits.
- Generate the invoice and record its calculation details.

Use decimal-safe monetary arithmetic. Do not calculate financial amounts using binary floating-point arithmetic.

## 5.4 Pricing versioning

When an administrator changes a price, existing subscriptions must follow the configured policy:

- Existing price remains unchanged.
- New price applies at the next renewal.
- Customer is notified before the change.
- Customer accepts a revised agreement where required.

Keep historical price versions so past invoices can always be reproduced accurately.

## 5.5 Licence and usage enforcement

Every tenant licence must specify:

- Tenant ID.
- Plan ID and price version.
- Subscription start and expiry dates.
- Trial end date, if applicable.
- Enabled modules.
- User, website and storage limits.
- AI and API usage allowances.
- Current subscription status.
- Invoice and payment status.
- Grace period and suspension rules.

Enforce entitlements on the server. Hiding a menu item is not sufficient.

When a limit is reached, apply the configured behaviour: prevent further usage, request an upgrade, allow an authorised overage, or notify the administrator.

---

# 6. Thirty-day trial workflow

The default trial period is 30 days.

The platform must support the following workflow:

1. Prospect selects an eligible plan.
2. System creates a tenant or trial account.
3. System records the trial start and end timestamps.
4. System grants only the trial plan's enabled modules and limits.
5. System displays remaining trial time to authorised users.
6. System sends configurable trial reminders.
7. Customer can select a paid plan or request assistance.
8. Trial ends at the configured time.
9. If a paid subscription has been confirmed, paid entitlements become active.
10. Otherwise, the system applies the configured grace, restricted-access or suspension policy.

Trial controls must include:

- Eligibility rules.
- Trial duration.
- Trial limits.
- Reminder schedule.
- Extension approval.
- Conversion tracking.
- Data export and retention.
- Abuse prevention.

A 30-day trial must not automatically trigger an unannounced charge. If payment collection or automatic conversion is added later, require clear disclosure, valid payment authorisation and compliance with applicable consumer rules.

---

# 7. Initial invoicing and bank-transfer reconciliation

## 7.1 Initial payment process

The first release will use manual invoicing and bank-transfer reconciliation rather than assuming a payment gateway is already connected.

Workflow:

1. Customer selects a subscription, module or product.
2. System calculates the amount and generates an invoice.
3. Invoice receives a unique identifier and payment reference.
4. Customer receives the invoice and approved bank-transfer instructions.
5. Customer makes the bank transfer outside the platform.
6. Finance staff record or import the relevant bank transaction.
7. System matches the transaction to the invoice using payment reference, amount, date and other permitted evidence.
8. Finance staff review ambiguous matches.
9. An authorised user confirms receipt of payment.
10. The invoice is marked paid.
11. The system records the reconciliation evidence and audit event.
12. Relevant entitlements or order fulfilment are activated according to policy.

## 7.2 Reconciliation controls

Support:

- Manual transaction entry.
- Bank statement CSV import using a validated, documented format.
- Duplicate transaction detection.
- Matching by invoice number or payment reference.
- Exact, partial and overpayment handling.
- Underpayment and unidentified payment queues.
- Refund and reversal records.
- Reconciliation reports.
- Maker-checker approval for sensitive adjustments.
- Audit history for all financial status changes.

Only authorised finance users may confirm payment or modify reconciliation status.

Never mark an invoice paid merely because a customer uploaded a screenshot or claimed to have transferred funds.

## 7.3 Integration status

**Pending / unverified:** Automated bank feeds, open-banking connections, payment gateway checkout, automated direct debit and automated payout services.

Do not display an integration as connected until its credentials, permissions, webhook or import flow, failure handling and end-to-end tests have been verified.

---

# 8. Platform-owner commerce and tenant commerce

## 8.1 Platform-owner commerce

The platform owner can sell:

- SaaS subscriptions.
- Paid modules.
- AI usage.
- Templates and industry packages.
- Implementation and migration services.
- Training and support packages.
- Approved digital products.
- Other configured add-ons.

Platform orders, invoices, subscriptions and revenue reports belong to the platform-owner commercial environment.

## 8.2 Tenant commerce

Each tenant can enable its own storefront and sell:

- Physical products.
- Digital downloads.
- Courses.
- Consulting services.
- Catering packages.
- Event services.
- Appointments and bookings.
- Subscriptions.
- Bundles and configurable products.

Tenant-specific settings include catalogue, pricing, currency, tax, promotions, fulfilment, terms, payment workflow and customer communications.

## 8.3 Commerce separation

Every commercial record must be associated with its correct owner and environment.

Do not mix platform subscription invoices with tenant customer invoices. Use separate identifiers, reporting scopes, permissions and reconciliation rules.

If a tenant later uses an external payment provider, the tenant's account, credentials, transactions and webhook configuration must remain distinct from those of other tenants.

---

# 9. Product catalogue, shopping cart and checkout

## 9.1 Catalogue

Each product or service must support:

- Product ID and SKU.
- Name, description and category.
- Images and attachments.
- Product type.
- Base price and currency.
- Variants and configurable options.
- Tax classification.
- Stock or service availability.
- Discount eligibility.
- Delivery, pickup or digital fulfilment.
- Publication status.
- SEO fields.
- Return, cancellation and fulfilment policies.

## 9.2 Cart

Required functionality:

- Add to cart.
- Remove items.
- Change quantity.
- Select variants and add-ons.
- Save cart for an authenticated customer.
- Guest cart where permitted.
- Recalculate totals.
- Apply valid coupons.
- Apply eligible referral discounts.
- Check stock and service availability.
- Recover abandoned carts with appropriate consent.
- Convert cart to order after checkout.

Revalidate every price, discount, stock quantity and applicable charge on the server during checkout.

## 9.3 Checkout and order management

Implement:

Cart → Customer Details → Fulfilment → Invoice or Payment → Confirmation → Fulfilment → Completion.

Support:

- Guest or registered checkout.
- Billing and delivery details.
- Delivery, pickup, booking or digital fulfilment.
- Order notes.
- Order confirmation.
- Invoice and receipt generation.
- Order history.
- Cancellation and refund workflows.
- Partial fulfilment where relevant.
- Customer notifications.
- Staff order management.

For the initial release, checkout may generate an invoice and bank-transfer instructions. The order must not be treated as paid until authorised reconciliation confirms receipt.

## 9.4 Coupons and promotions

Support:

- Fixed-amount discounts.
- Percentage discounts.
- Subscription discounts.
- Referral discounts.
- First-purchase offers.
- Bundle pricing.
- Limited-time campaigns.
- Product and customer eligibility.
- Minimum order values.
- Maximum redemption limits.
- Start and expiry dates.
- Discount stacking policies.

Every redemption must be validated and recorded. Invalid, expired or exhausted coupons must be rejected.

---

# 10. Referral and affiliate marketing

## 10.1 Programme configuration

Authorised platform administrators and tenant administrators can create independent referral programmes.

Each programme defines:

- Programme owner and tenant scope.
- Name, terms and description.
- Eligible products and subscriptions.
- Referral attribution method.
- Attribution window.
- Qualifying conversion.
- Commission rate.
- Commission duration.
- Commission base.
- Payment schedule.
- Commission caps.
- Refund and chargeback rules.
- Eligibility restrictions.
- Approval workflow.
- Payout or account-credit options.

## 10.2 Default illustrative commission

Set the initial example to **15% recurring commission for a limited, configurable period**.

Suggested initial configuration:

- Commission rate: 15%.
- Commission duration: first six eligible monthly payments.
- Qualifying event: a verified and eligible paid invoice.
- Commission status: Pending until applicable checks complete.
- Approval: authorised finance or referral programme manager.
- Payment: manually reconciled and recorded until a verified payout integration is available.

The six-month duration is a proposed default for configuration, not a final contractual commitment.

## 10.3 Example calculation

If a customer has an eligible NZ$79 monthly subscription and the commission base is the full subscription fee:

- Monthly eligible revenue: NZ$79.
- Illustrative commission rate: 15%.
- Commission for one eligible payment: NZ$11.85.
- Maximum illustrative commission across six eligible payments: NZ$71.10.

This example excludes refunds, taxes, discounts, credits, unpaid invoices and other adjustments. The actual commission must follow the programme's approved commission-base policy.

## 10.4 Commission workflow

1. Affiliate enrols in an approved programme.
2. System issues a unique referral link, code and optional QR code.
3. Prospect visits using the referral link.
4. System records eligible attribution.
5. Prospect registers or purchases.
6. System links the qualifying transaction to the referral according to the programme rules.
7. The invoice is paid and verified.
8. Commission is calculated and marked Pending.
9. The configured refund and fraud review period completes.
10. An authorised user approves the commission.
11. Commission becomes Payable.
12. Finance records payment or account credit.
13. Commission status becomes Paid or Credited.
14. All adjustments and status changes are retained in the ledger.

## 10.5 Referral dashboards

Affiliate dashboard:

- Referral links and QR codes.
- Clicks and registrations.
- Qualified leads.
- Conversions.
- Commission rate and duration.
- Pending, approved, reversed and paid commissions.
- Payment statements.
- Marketing resources.
- Referral campaign performance.

Administrator dashboard:

- Programme enrolments.
- Attributed sales.
- Conversion rates.
- Commission liability.
- Pending approvals.
- Reversals and refunds.
- Fraud alerts.
- Payout history.
- Campaign performance by programme and tenant.

## 10.6 Referral fraud prevention

Implement:

- Duplicate conversion detection.
- Self-referral rules.
- Suspicious signup and transaction checks.
- Commission caps.
- Refund and chargeback reversals.
- Manual review queues.
- Immutable commission ledger entries.
- Rate limiting and abuse detection.
- Appeals and review of disputed decisions.

Do not calculate payable commissions from clicks alone. Do not reward recruitment without qualifying legitimate commercial transactions.

Any multi-level referral scheme must be optional, legally reviewed and based on qualifying commercial activity.

---

# 11. Functional requirements catalogue

Assign each requirement a unique ID, owner, priority, implementation status and test case.

Priority definitions:

- **P0:** Secure platform foundation.
- **P1:** First commercial release.
- **P2:** Advanced capabilities.

| ID | Functional requirement | Priority |
|---|---|---|
| FR-001 | Secure authentication, password recovery and session management | P0 |
| FR-002 | Tenant creation, configuration and lifecycle management | P0 |
| FR-003 | Role-based access control with server-side enforcement | P0 |
| FR-004 | Tenant isolation across data, APIs, files, jobs and AI retrieval | P0 |
| FR-005 | Licence, entitlement and usage-limit enforcement | P0 |
| FR-006 | Audit logging for sensitive actions | P0 |
| FR-007 | User, department and custom-role administration | P0 |
| FR-008 | Configurable plans and price versions | P1 |
| FR-009 | Thirty-day trial management | P1 |
| FR-010 | Hybrid base, module and usage-based billing | P1 |
| FR-011 | Invoice, credit note and receipt generation | P1 |
| FR-012 | Manual bank-transfer reconciliation | P1 |
| FR-013 | Subscription renewal, upgrade, downgrade and cancellation | P1 |
| FR-014 | Configurable grace, suspension and reactivation | P1 |
| FR-015 | Platform-owner product and service catalogue | P1 |
| FR-016 | Tenant-specific catalogues and storefronts | P1 |
| FR-017 | Add-to-cart, quantity changes and cart removal | P1 |
| FR-018 | Checkout with server-side price validation | P1 |
| FR-019 | Order, fulfilment and refund management | P1 |
| FR-020 | Coupons, discounts and promotion rules | P1 |
| FR-021 | Referral links, codes and QR generation | P1 |
| FR-022 | Referral attribution and conversion tracking | P1 |
| FR-023 | Recurring commission calculation and ledger | P1 |
| FR-024 | Commission approval, reversal and manual payout records | P1 |
| FR-025 | Affiliate dashboards and statements | P1 |
| FR-026 | Referral fraud controls | P1 |
| FR-027 | CRM contacts, leads, opportunities and sales pipeline | P1 |
| FR-028 | Marketing campaigns and lead generation | P1 |
| FR-029 | Inventory, procurement and stock management | P1 |
| FR-030 | Staff records, shifts, attendance and QR check-in | P1 |
| FR-031 | Dashboard builder and configurable widgets | P1 |
| FR-032 | Dynamic pages, forms and module configuration | P1 |
| FR-033 | Multiple websites, themes and content publishing | P1 |
| FR-034 | BI dashboards, KPI reports and exports | P1 |
| FR-035 | AI Agent Studio and controlled tool execution | P1 |
| FR-036 | AI-assisted document generation | P1 |
| FR-037 | Public website chatbot and lead capture | P1 |
| FR-038 | Notifications and workflow automation | P1 |
| FR-039 | Library and document search | P2 |
| FR-040 | Approved YouTube research using available metadata or transcripts | P2 |
| FR-041 | Gmail, WhatsApp and social integrations | P2 |
| FR-042 | Usage-based billing automation and advanced metering | P2 |
| FR-043 | Marketplace for modules, themes and templates | P2 |
| FR-044 | Advanced referral attribution and partner programmes | P2 |
| FR-045 | Enterprise contracts and negotiated pricing | P2 |
| FR-046 | Backup, restoration and data-retention management | P0 |
| FR-047 | Data export, correction and deletion workflows | P0 |
| FR-048 | Automated critical-path and permission tests | P0 |

---

# 12. Non-functional requirements

The following are initial engineering targets. Validate them through performance testing and operational planning.

## 12.1 Security

- NFR-001: Enforce tenant isolation across all data and service boundaries.
- NFR-002: Apply least privilege and deny access by default.
- NFR-003: Require MFA for privileged accounts.
- NFR-004: Protect passwords, tokens, secrets and sensitive data.
- NFR-005: Use encrypted connections and appropriate encryption at rest.
- NFR-006: Validate inputs and defend against common web vulnerabilities.
- NFR-007: Protect audit logs from unauthorised alteration.
- NFR-008: Restrict financial adjustments and commission approvals.
- NFR-009: Secure AI tools against prompt injection and data leakage.
- NFR-010: Test access control for APIs, exports, files, background jobs and integrations.

## 12.2 Performance

- NFR-011: Initially target a 95th-percentile response time below two seconds for common interactive operations under an agreed test load, excluding external provider delays and long-running AI tasks.
- NFR-012: Use indexed queries, pagination and efficient database access.
- NFR-013: Run long-running tasks asynchronously.
- NFR-014: Display progress and useful failure messages for background tasks.
- NFR-015: Establish tested limits for concurrent users, API traffic and processing jobs.

## 12.3 Reliability and recovery

- NFR-016: Initially target 99.5% monthly availability, subject to infrastructure and operational capability.
- NFR-017: Monitor application, database and background-worker health.
- NFR-018: Back up critical data and configuration regularly.
- NFR-019: Test restoration from backups.
- NFR-020: Define recovery time objective and recovery point objective before production.

## 12.4 Scalability and maintainability

- NFR-021: Use modular architecture and documented interfaces.
- NFR-022: Separate global platform configuration from tenant configuration.
- NFR-023: Version database migrations.
- NFR-024: Keep credentials and secrets out of source code.
- NFR-025: Maintain automated unit, integration, API and end-to-end tests.
- NFR-026: Provide structured logs, monitoring and actionable errors.

## 12.5 Usability and accessibility

- NFR-027: Support responsive desktop, tablet and mobile interfaces.
- NFR-028: Provide consistent navigation, forms and error messages.
- NFR-029: Support keyboard navigation and accessible labels.
- NFR-030: Aim for WCAG 2.2 AA accessibility where applicable.
- NFR-031: Provide clear loading, empty, success and error states.
- NFR-032: Confirm destructive actions and sensitive financial adjustments.

## 12.6 Privacy and compliance

- NFR-033: Collect only information needed for legitimate business purposes.
- NFR-034: Support authorised access, correction, export and deletion requests.
- NFR-035: Record consent and communication preferences where required.
- NFR-036: Assess applicable New Zealand privacy, consumer, tax, employment and electronic communications requirements.
- NFR-037: Establish appropriate controls for external AI and integration providers.
- NFR-038: Configure retention policies according to legal, operational and contractual needs.

## 12.7 AI governance

- NFR-039: Identify AI-generated content and preserve sources where relevant.
- NFR-040: Require approval for configured high-impact actions.
- NFR-041: Track AI usage, cost, execution status and prompt/model version where available.
- NFR-042: Enforce per-tenant AI budgets and quotas.
- NFR-043: Handle provider outages gracefully.
- NFR-044: Validate AI-generated financial or operational actions before execution.
- NFR-045: Prevent unauthorised cross-tenant retrieval and tool access.

## 12.8 Financial integrity

- NFR-046: Use decimal-safe monetary calculations.
- NFR-047: Preserve invoice and transaction history.
- NFR-048: Prevent duplicate payments, orders, commission entries and webhook processing.
- NFR-049: Reconcile invoices against recorded bank transactions.
- NFR-050: Maintain an auditable commission ledger.
- NFR-051: Preserve historical pricing and invoice calculations.
- NFR-052: Define explicit rules for rounding, discounts, tax, refunds and commission reversals.

---

# 13. Database entities

Use a relational database such as PostgreSQL where supported.

## 13.1 Platform and access

- Tenant.
- TenantSetting.
- User.
- Role.
- Permission.
- RolePermission.
- UserRole.
- Department.
- Team.
- ResourceScope.
- Module.
- ModuleEntitlement.
- Licence.
- AuditEvent.
- SecurityEvent.
- Notification.
- Workflow.
- WorkflowExecution.

## 13.2 Subscription and billing

- PricingPlan.
- PricingPlanVersion.
- Subscription.
- SubscriptionItem.
- SubscriptionHistory.
- Trial.
- LicenceEntitlement.
- UsageMeter.
- UsageEvent.
- Invoice.
- InvoiceLine.
- PaymentRecord.
- BankTransaction.
- ReconciliationMatch.
- CreditNote.
- Refund.
- TaxConfiguration.
- BillingAddress.
- FinancialAdjustment.

## 13.3 Commerce

- Store.
- Product.
- ProductVariant.
- ProductPrice.
- ProductCategory.
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
- Customer.

## 13.4 Referral and affiliate

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

## 13.5 CRM, ERP and AI

- Contact.
- Lead.
- Opportunity.
- Campaign.
- Activity.
- ProductInventory.
- PurchaseOrder.
- Employee.
- Shift.
- AttendanceRecord.
- Website.
- WebsitePage.
- MediaAsset.
- AIConfiguration.
- AIAgent.
- AIToolPermission.
- AIExecution.
- AIApproval.
- KnowledgeDocument.
- IntegrationConfiguration.

Every tenant-owned entity must have an enforceable tenant scope. Platform-level records must be explicitly identified as platform-owned.

Keep payment records, commission records and audit events traceable through immutable identifiers and status histories.

---

# 14. Technical architecture

Preferred architecture, subject to the selected development platform:

- Frontend: React or Next.js with TypeScript.
- Backend: FastAPI or NestJS.
- Database: PostgreSQL.
- Background jobs: a supported queue and worker system.
- File storage: private object storage with authorised download links.
- Authentication: secure session or token-based authentication with MFA for privileged roles.
- AI: provider-agnostic service layer with quotas and controlled tools.
- Search: database search and optional search/vector infrastructure.
- Deployment: managed cloud or container-based hosting.
- Observability: centralised logs, metrics and error monitoring.

If using a visual AI coding platform, adapt the implementation to its actual capabilities. Do not assume it supports every integration, permission model, backend job, database constraint or payment workflow until verified.

## 14.1 Required architectural boundaries

Separate:

1. Platform administration and licensing.
2. Tenant business applications.
3. Subscription and finance services.
4. Commerce and order processing.
5. Referral and commission processing.
6. AI execution and approval.
7. Website and presentation layers.
8. Integration and notification services.

Avoid implementing financial calculations independently in multiple modules. Use shared, tested services for pricing, tax configuration, entitlements, reconciliation and commissions.

---

# 15. Dynamic dashboard and module builder

Provide a backend interface that allows authorised administrators to:

- Create and configure modules.
- Enable or disable modules per tenant.
- Configure subpages and navigation.
- Add dynamic forms, fields and validation rules.
- Create dashboards and widgets.
- Drag and drop widgets.
- Save personal, team and role-specific layouts.
- Lock layouts when required.
- Configure visibility based on permissions.
- Preview changes before publishing.
- Maintain configuration history and rollback options.

Use a defined module manifest to describe a module's routes, data requirements, permissions, settings and dashboard widgets.

Configuration must not bypass backend authorisation. A page hidden in navigation must still be protected at the API and data-access layers.

---

# 16. AI Agent Studio

Create a backend AI Agent Studio that allows authorised users to configure:

- Sales lead generation agent.
- Sales follow-up agent.
- Marketing campaign agent.
- Customer support agent.
- Business intelligence agent.
- Document generation agent.
- Operations assistant.
- Event planning agent.
- Catering management assistant.
- Educational consultancy assistant.
- E-commerce operations assistant.
- Custom tenant-specific agents.

Each agent must define:

- Purpose and permitted tasks.
- Knowledge sources.
- Available tools.
- Tenant and record scope.
- Usage and cost limits.
- Approval requirements.
- Execution schedule or triggers.
- Error handling and retry policy.
- Audit and reporting configuration.

Require approval for configured high-impact actions, including financial adjustments, refunds, commission payouts, permission changes and external communications that require human review.

Do not grant an AI agent unrestricted access to tenant data or global administration.

---

# 17. Website builder and public chatbot

Allow authorised users to create multiple websites, configure themes, create pages, manage content, publish updates and connect supported domains.

Support:

- Dynamic page and subpage management.
- SEO settings.
- Forms and lead capture.
- Product and service pages.
- Public pricing pages.
- Landing pages.
- Booking and inquiry pages.
- Content previews.
- Version history.
- Publishing approvals.
- Tenant-specific branding.

Provide an embeddable public AI chatbot using a generated script or supported embed URL.

The chatbot must:

- Use only authorised tenant knowledge sources.
- Respect tenant isolation.
- Capture leads only with appropriate disclosure.
- Provide escalation to a human.
- Respect consent and retention settings.
- Avoid exposing internal documents or private CRM records.
- Clearly identify unavailable information instead of inventing answers.

---

# 18. Other ERP and CRM modules

## Sales and CRM

Manage contacts, leads, opportunities, pipelines, quotations, activities, reminders, sales targets and customer communication history.

## Marketing

Manage campaigns, audiences, referral promotions, content calendars, approved email integrations, campaign analytics and conversion attribution.

## Finance

Manage invoices, expenses, payments, reconciliation, credit notes, refunds, reports and approvals according to tenant permissions.

## Inventory and procurement

Manage products, stock, suppliers, purchase orders, stock movements, reorder rules and fulfilment.

## Workforce

Manage employees, teams, shifts, leave, attendance, QR check-in and operational task assignment. QR attendance should include replay prevention, expiry and appropriate verification.

## Documents and knowledge

Manage PDFs, documents, library records, search, OCR where supported, summarisation and controlled AI retrieval.

## Integrations

Provide configuration screens for supported Gmail, WhatsApp Business, social media, bank import and other integrations. Use authorised APIs and OAuth where applicable.

**Integration status:** Pending until the specific provider, credentials, scopes, permissions and end-to-end behaviour are verified.

---

# 19. Acceptance criteria and mandatory test scenarios

## 19.1 Subscription and billing

- A customer can select an eligible plan and start a 30-day trial.
- Trial entitlements match the configured plan.
- A trial expiry does not trigger an undisclosed automatic charge.
- Base subscription, module fees and usage charges are calculated correctly.
- Price changes preserve historical invoice calculations.
- Invoices use NZD by default.
- Tax and rounding rules are configurable and tested.
- A bank-transfer invoice remains unpaid until authorised reconciliation confirms receipt.
- Duplicate bank transactions are detected.
- Partial payments and overpayments enter a controlled reconciliation workflow.
- Subscription status changes produce audit records.

## 19.2 Commerce

- A customer can add a product to a cart and change its quantity.
- The server rejects tampered prices and invalid discounts.
- Checkout creates a valid order and invoice.
- Order payment status matches verified financial records.
- Stock and service availability are checked before confirmation.
- Customers cannot view another customer's orders.
- Tenant orders and platform subscription orders remain separate.

## 19.3 Referral marketing

- The system generates a unique referral link and code.
- A qualifying transaction is attributed according to the configured rules.
- The illustrative 15% commission is calculated only on the configured commission base.
- The commission period ends after the configured number of eligible payments.
- Unpaid, refunded or ineligible transactions do not generate payable commission.
- Repeated webhook or transaction processing does not create duplicate commissions.
- Approved commission payouts reconcile with the commission ledger.
- Affiliates cannot access other affiliates' private information.

## 19.4 Permissions and security

- A user without permission cannot access a protected page or API.
- A tenant cannot read or modify another tenant's data.
- Direct API requests cannot bypass role restrictions.
- AI agents cannot access records outside their authorised scope.
- Sensitive financial adjustments require the configured approval.
- Permission changes and privileged access are recorded.
- Backup restoration preserves key financial and audit relationships.

## 19.5 AI and integrations

- AI agents respect their configured usage and cost limits.
- High-impact actions follow approval requirements.
- Public chatbots cannot access private tenant records.
- Failed external integrations show an accurate failure state.
- No integration is labelled Connected before a successful verification test.
- AI-generated reports identify source material where relevant.
- Provider outages do not silently corrupt orders, invoices or commissions.

---

# 20. Implementation roadmap

## Phase 1 — Secure foundation

Deliver tenant isolation, authentication, roles, permissions, audit logging, module entitlements, database structure, backups and automated security tests.

## Phase 2 — Commercial foundation

Deliver configurable plans, the 30-day trial, hybrid pricing, invoices, manual bank-transfer reconciliation, licence enforcement and subscription lifecycle management.

## Phase 3 — E-commerce

Deliver product catalogue, cart, checkout, invoices, orders, fulfilment, coupons and separate platform-owner and tenant storefronts.

## Phase 4 — Referral marketing

Deliver referral programmes, attribution, recurring commission calculations, the 15% illustrative configuration, approval workflows, manual payout records and fraud controls.

## Phase 5 — Core ERP and CRM

Deliver CRM, sales pipeline, marketing, finance, inventory, workforce, dashboards and business reports.

## Phase 6 — AI and websites

Deliver the AI Agent Studio, controlled AI tools, document generation, multi-website management, public chatbot and knowledge retrieval.

## Phase 7 — Advanced capabilities

Deliver usage-billing automation, marketplace extensions, advanced analytics, additional payment providers, approved social integrations and advanced partner programmes.

## Phase 8 — Production readiness

Complete load testing, security testing, reconciliation tests, backup restoration, operational monitoring, deployment documentation and end-to-end acceptance testing.

---

# 21. Delivery and implementation rules

The coding agent or development team must:

1. Inspect the selected development platform and confirm its capabilities before implementation.
2. Produce the architecture, data model, requirements traceability matrix and phased implementation plan.
3. Identify required external accounts, credentials, permissions, provider fees and operational dependencies.
4. Implement the P0 foundation before enabling commercial transactions.
5. Build one complete workflow at a time, including frontend, backend, data model, validation and tests.
6. Use realistic but clearly identified demo data during development.
7. Keep pricing, permissions, limits, referral rules and trial policies configurable.
8. Avoid hardcoding commercial prices or granting unrestricted administrator privileges.
9. Record each requirement as Not Started, In Progress, Blocked, Implemented or Verified.
10. Never mark a feature Verified without passing its acceptance tests.
11. Mark unsupported or unconfigured external integrations as Pending.
12. Document setup, deployment, migration, recovery and administrator procedures.
13. Protect tenant data during testing and migration.
14. Avoid enabling automatic payments or payouts until the relevant provider integration has been authorised and tested.

## Definition of done

A feature is complete only when its user interface, backend behaviour, database rules, permission checks, error handling, audit requirements and acceptance tests work together.

A polished dashboard or working prototype alone does not establish production readiness.

**Final product objective:** A secure, configurable, multi-tenant business platform with NZD-first hybrid SaaS pricing, a 30-day trial, manual invoicing and bank-transfer reconciliation, recurring referral commissions, platform and tenant commerce, modular ERP/CRM, controlled AI automation and a testable path to additional integrations.