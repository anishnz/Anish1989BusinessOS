# 01. Mind map

Last updated: 21 October 2026

This mind map shows the whole platform. Each branch is explained in more detail in the other documents.

```mermaid
mindmap
  root((Anish1989 Business OS))
    0 Brainstorm and docs
      Vision and scope
      Roles and permissions
      FR and NFR requirements
      Data model ERD
      Architecture decisions
      Roadmap
    1 Tech stack
      Django and DRF
      React or Next.js
      PostgreSQL schema per tenant
      Celery and Redis
      Django Channels
      Docker
    2 Multi-tenant core
      Tenants and licences
      Roles and permission matrix
      Module registry
      Audit log
      Onboarding wizard
      Sandbox mode
      Data export and offboarding
    3 Settings and secret vault
      Own AI keys
      Own messaging keys
      Own payment settings
      Encrypted and masked
      Key health checks
      Usage and cost meter
      AI fallback provider
    4 Adapters and inbox
      WhatsApp Viber Telegram
      Email and SMS
      Bank transfer now
      Stripe Windcave PayPal later
      Unified inbox
      Tenant API and webhooks
    5 WhatsApp AI ordering
      QR scan and OTP
      Chat order
      Confirm before recording
      Weight based final price
      Stock aware and quick reorder
      Status updates and pickup slots
      Human handover
    6 Business modules
      CRM and sales
      Inventory and wastage
      Invoices and reconciliation
      Cart orders coupons
      Referrals and QR loyalty
      HR and QR attendance
      Websites
      Staff mobile app PWA
    7 AI layer
      Agent studio
      OpenAI Claude Gemini local
      Tool permissions
      Approval queue
      Cost limits
    8 Business intelligence
      Many chart types
      Customer response
      Post order feedback
      Segments and basket analysis
      Demand forecast
      Anomaly alerts
      Daily owner summary
    9 Competitor intelligence
      Choose location and radius
      Find similar businesses
      Crawl public websites
      Ask AI to check competitors
      Weekly report
      Full log and history
    10 Security and compliance
      MFA and encryption
      Tenant isolation
      Consent log and STOP
      Backups and tests
      Monitoring
    11 Learning and jobs
      Courses and YouTube lessons
      Quizzes and certificates
      Job board
      Auckland job listings
      ATS resume builder
      Job alerts
    12 Platform operations
      Subdomains and custom domains
      DNS check and SSL
      Website content editor with AI
      Ticket system
      Check system button
      Backups every 6 hours to Google Drive
```

## Branch summary

| # | Branch | Purpose | Details |
|---|---|---|---|
| 0 | Brainstorm and docs | Plan before building | This folder |
| 1 | Tech stack | Tools and frameworks | [Decisions](02-decisions.md) |
| 2 | Multi-tenant core | Tenants, licences, roles, modules, audit | [Feature catalogue](03-feature-catalogue.md) |
| 3 | Settings and secret vault | Each tenant manages its own keys | [Settings and secrets](04-tenant-settings-and-secrets.md) |
| 4 | Adapters and inbox | One interface per provider type | [Settings and secrets](04-tenant-settings-and-secrets.md) |
| 5 | WhatsApp AI ordering | Order by chat, no website visit needed | [WhatsApp AI ordering](05-whatsapp-ai-ordering.md) |
| 6 | Business modules | CRM, inventory, finance, commerce, HR | [Feature catalogue](03-feature-catalogue.md) |
| 7 | AI layer | Agents with limits and approvals | [Feature catalogue](03-feature-catalogue.md) |
| 8 | Business intelligence | Charts and customer response | [Business intelligence](06-business-intelligence.md) |
| 9 | Competitor intelligence | Weekly competitor reports | [Competitor intelligence](07-competitor-intelligence.md) |
| 10 | Security and compliance | Protect data and follow NZ rules | [Feature catalogue](03-feature-catalogue.md) |
| 11 | Learning and jobs | Courses, job board, resume builder | [Industry templates](09-industry-templates.md) |
| 12 | Platform operations | Domains, content editor, tickets, health checks, backups | [Platform operations](11-platform-operations.md) |
