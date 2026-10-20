Your idea is to build a universal, AI-powered ERP, CRM, and multi-website management platform that combines the flexibility of Odoo, the enterprise capabilities of SAP, and the AI automation features of modern business platforms.

The key is to build one modular SaaS platform where a Super Admin can manage multiple customers, licences, roles, permissions, websites, dashboards, AI agents, and industry-specific systems—without developing a completely new application for each business.

The following master prompt is designed for an AI coding platform such as Base44 or another AI app builder. It defines the product vision, hierarchy, modules, dashboard controls, security requirements, and implementation plan.

# Master prompt: Universal AI-powered ERP and CRM platform

Copy the following prompt into your AI coding platform. It is written as a product specification so the platform can build the application in manageable phases.

# Project: Universal AI ERP, CRM and Multi-Website SaaS Platform

## 1. Project vision

Build a complete, modular, AI-powered Enterprise Resource Planning (ERP), Customer Relationship Management (CRM), Business Intelligence (BI), and website management platform.

The platform should combine the flexibility of Odoo, enterprise resource management concepts found in SAP, modern CRM automation, AI agents, and a no-code website builder.

Create one central platform that allows a company to manage its business operations, users, websites, customers, staff, sales, marketing, documents, communications, analytics, and AI agents from a single administrative dashboard.

The system must support multiple companies, multiple accounts, multiple websites, different business industries, configurable modules, subscription licences, custom dashboards, and role-based access control.

Build a working application with functional backend logic, database relationships, authentication, permissions, CRUD operations, integrations, and audit trails. Do not create a dashboard that only looks functional with static sample data.

## 2. Multi-tenant architecture and account hierarchy

Create the following account hierarchy.

### Level 1: Super Admin

The Super Admin controls the entire SaaS platform.

Required features:

- Create, activate, suspend, renew, and revoke customer licences.
- Create multiple customer accounts and assign a unique tenant ID to each account.
- Assign a System Admin to each customer account.
- Configure licence type, expiry date, subscription plan, enabled modules, storage limits, AI usage limits, and user limits.
- Manage every customer's system configuration.
- View and change roles, permissions, and access policies across all tenants.
- Override tenant settings where authorised and maintain an audit trail of overrides.
- View platform-wide usage, revenue, account status, security alerts, AI consumption, and system health.
- Enable or disable modules for individual tenants.
- Manage global settings, subscription plans, integrations, templates, and platform updates.
- Impersonate a tenant administrator only through a secure, time-limited, explicitly audited support process.

The Super Admin must have a separate, highly protected control panel.

### Level 2: System Admin

The System Admin manages the customer organisation assigned by the Super Admin.

Required features:

- Configure the organisation, departments, business units, branches, and websites.
- Create and manage IT Admin accounts.
- Enable or disable available modules for the tenant.
- Configure which modules, pages, widgets, and menu items each sub-account can access.
- Assign modules through a simple checkbox-based permission interface.
- Configure user roles, dashboards, workflows, notifications, and business settings within the limits set by the Super Admin.
- Create sub-accounts for departments, branches, subsidiaries, projects, or business units.
- Allocate licence capacity and monitor account usage.
- Set up the organisation's AI agents and approved integrations.

System Admins must not be able to change global platform policies or exceed the licence and permissions granted by the Super Admin.

### Level 3: IT Admin

IT Admin accounts must be created through the System Admin dashboard.

Required features:

- Manage authorised users, access, security policies, technical settings, and integrations.
- Configure authentication, password policies, session controls, and MFA.
- Manage API credentials and webhook settings where permitted.
- Monitor application errors, system logs, backups, and integration status.
- Manage technical support and approved deployments.

### Level 4: Department Admins and Managers

Support department-specific administration for Sales, Marketing, Finance, HR, Operations, Education, Inventory, Catering, E-commerce, and other enabled modules.

### Level 5: Staff and End Users

Provide a personalised workspace for employees, sales representatives, teachers, students, customers, suppliers, contractors, and other authorised users.

Every user must see only the data, pages, actions, and dashboards permitted by their assigned roles and permissions.

## 3. Dynamic module and permission management

Create a central Module Management Studio.

The Super Admin can register, publish, enable, disable, or restrict modules globally or by tenant.

The System Admin can select which permitted modules appear in each sub-account.

For example:

- Tick Sales CRM to enable sales features.
- Tick HR to enable employee management.
- Tick Inventory to enable stock management.
- Tick Website Builder to enable website creation.
- Tick AI Marketing to enable marketing agents.
- Tick Library to enable digital document and book management.

When a module is disabled, hide it from the user's navigation and block its backend APIs according to the permission policy.

Provide a visual permissions matrix with checkboxes for modules, pages, actions, and data scopes.

Support permissions such as View, Create, Edit, Delete, Approve, Export, Configure, and Administer.

Include permission inheritance, explicit overrides, conflict resolution, and a clear indication when a global policy prevents a tenant-level change.

## 4. Customisable dashboard builder

Create a drag-and-drop Dashboard Builder for authorised administrators.

Users should be able to:

- Add, remove, resize, rearrange, and group widgets.
- Move widgets between dashboard columns and sections.
- Configure chart types, data sources, filters, and display preferences.
- Save dashboards as personal, departmental, tenant-wide, or role-based layouts.
- Lock a dashboard layout to prevent unauthorised changes.
- Unlock it only through the appropriate permission.
- Preview dashboards for different roles before publishing.
- Restore previous layouts and reset to a default dashboard.
- Configure responsive layouts for desktop, tablet, and mobile.

Provide a dashboard widget library containing KPI cards, sales charts, lead pipelines, task lists, attendance summaries, staff schedules, inventory alerts, notifications, AI chat panels, document lists, and business intelligence reports.

## 5. Core ERP and CRM modules

Build each module as an independently configurable component that shares common identity, customer, company, reporting, and permission services.

### Sales and CRM

- Lead capture from websites, forms, email, imports, and approved integrations.
- Lead qualification, scoring, assignment, and follow-up reminders.
- Pipeline stages, opportunities, quotations, proposals, and sales orders.
- Contact, company, customer, supplier, and interaction history.
- Customer segmentation and account management.
- Sales targets, conversion rates, revenue forecasting, and commission rules.
- Automated follow-up workflows.
- AI-assisted lead research, email drafting, prioritisation, and sales recommendations.
- Human approval for sensitive or high-impact automated actions.

### Marketing automation

- Campaign planning and management.
- Email campaigns, audience segmentation, and contact lists.
- Social media content planning and publishing integrations.
- Marketing calendars, campaign budgets, and performance reports.
- Landing pages, lead magnets, and campaign tracking.
- AI-generated marketing content and campaign suggestions.
- Marketing automation workflows and approval queues.
- Conversion tracking, campaign ROI, and attribution reports.

### Finance and accounting

- Customers, suppliers, invoices, bills, payments, expenses, and receipts.
- Accounts payable and receivable.
- Tax configuration, including support for New Zealand GST where appropriate.
- Budgeting, cash-flow reporting, financial summaries, and reconciliation workflows.
- Approval rules and financial audit trails.
- Integration-ready architecture for external accounting and payment services.

Treat this as an operational finance module initially. Implement full accounting, tax, payroll, and statutory reporting only with appropriate jurisdiction-specific rules and validation.

### Inventory and procurement

- Products, SKUs, categories, units, and pricing.
- Warehouses, branches, stock movements, and stock adjustments.
- Purchase orders, suppliers, goods received, and reorder rules.
- Batch, serial number, and expiry tracking where required.
- Inventory valuation and low-stock alerts.
- Barcode and QR code support.
- Demand forecasting and stock recommendations.

### HR and workforce management

- Employee profiles, departments, positions, and reporting lines.
- Recruitment, onboarding, leave, and employee documents.
- Attendance, timesheets, shifts, rosters, and overtime.
- Staff scheduling, shift swaps, and approval workflows.
- Performance reviews, training records, and HR notifications.
- Payroll integration architecture.

Do not assume attendance records alone are sufficient to calculate lawful wages or payroll.

### Projects and operations

- Projects, milestones, tasks, subtasks, and deadlines.
- Kanban boards, calendars, Gantt-style timelines, and workload views.
- Task assignment, comments, attachments, and approvals.
- Project budgets, costs, resource allocation, and progress reports.
- Workflow automation and overdue-task alerts.

### Customer support and service desk

- Support tickets, categories, priorities, and service-level targets.
- Customer enquiries, internal requests, and escalation rules.
- Knowledge base, FAQs, and AI-assisted support responses.
- Ticket assignment, response tracking, and resolution reports.

## 6. Business intelligence and analytics

Create a Business Intelligence Centre connected to authorised operational data.

Include:

- Executive dashboards.
- Sales, marketing, finance, inventory, HR, and project analytics.
- Revenue, expenses, gross margin, lead conversion, customer retention, and productivity KPIs.
- Custom reports with date ranges, filters, groupings, and drill-down views.
- Charts, pivot-style summaries, and exportable reports.
- Scheduled reports and notification rules.
- AI-assisted report generation from natural-language requests.
- Forecasting with clearly identified assumptions and confidence levels.
- Data import, validation, transformation, and source tracking.

Example: "Show this month's sales by branch, compare them with last month, identify the strongest products, and explain any significant changes."

The AI must query only the data the current user is authorised to access. Show the source, date range, and relevant calculation definitions for generated reports.

## 7. AI agent and automation centre

Create a central AI Agent Studio where authorised administrators can create, configure, test, publish, pause, and monitor AI agents.

Every agent should have a name, purpose, tenant scope, allowed data sources, permitted tools, usage limits, approval rules, and execution logs.

### Sales AI agent

- Review new leads and identify high-priority prospects.
- Suggest lead scores and explain the factors used.
- Draft personalised outreach messages.
- Recommend follow-up tasks and meeting schedules.
- Summarise CRM activity and identify inactive opportunities.
- Prepare sales forecasts and pipeline reports.
- Execute only approved CRM actions within its permissions.

### Marketing AI agent

- Generate marketing campaigns and content calendars.
- Draft social posts, newsletters, and promotional material.
- Suggest customer segments and campaign ideas.
- Analyse campaign performance.
- Recommend improvements and prepare content for approval.
- Publish only through authorised integrations and configured approval policies.

### Business operations AI agent

- Summarise daily business performance.
- Identify overdue tasks, unusual expenses, stock shortages, and operational bottlenecks.
- Draft reports, standard operating procedures, and business documents.
- Recommend workflows and automation opportunities.
- Create tasks or records only when authorised.

### AI document generator

Generate structured business documents from approved templates and authorised data, including:

- Quotations and proposals.
- Invoices and purchase orders.
- Meeting minutes and action lists.
- Project plans and status reports.
- Contracts and policy drafts for professional review.
- Job descriptions and onboarding documents.
- Business plans, marketing plans, and operational manuals.
- Educational reports, course outlines, and training material.
- Catering menus, event proposals, and event checklists.

Provide a document editor, reusable templates, version history, approval workflow, PDF export, and document search.

Generated documents must be drafts until approved when they have legal, financial, contractual, or other significant consequences.

### AI assistant

Provide a conversational AI assistant within the backend dashboard.

Users should be able to ask questions, retrieve permitted information, create draft records, summarise data, generate documents, and request approved actions through natural language.

The assistant must confirm before performing consequential actions such as sending bulk communications, deleting records, publishing content, issuing refunds, or making financial commitments.

## 8. AI chatbot for public websites

Allow administrators to create a chatbot for any website managed by the platform.

Requirements:

- Generate a website-specific chatbot configuration.
- Provide a copyable embed script or installation snippet.
- Provide an approved public chatbot endpoint or widget URL.
- Allow branding, colours, welcome messages, language, position, and appearance to be configured.
- Support FAQs, approved website content, uploaded documents, and authorised knowledge sources.
- Store conversations and enquiries according to configurable privacy and retention policies.
- Capture leads and send enquiries to the appropriate CRM pipeline.
- Support escalation to a human representative.
- Allow administrators to disable the chatbot or restrict its domains.
- Display usage, response quality, lead conversions, and error logs.

The public chatbot must not expose private CRM data, internal documents, admin endpoints, API keys, or information belonging to other tenants.

Use authenticated server-side retrieval and tenant-specific knowledge indexes.

## 9. Dynamic multi-website and page builder

Build a Website Management Studio supporting multiple websites under a single tenant, subject to licence limits.

Administrators should be able to:

- Create websites and assign domains or subdomains.
- Choose and change themes, templates, layouts, fonts, and branding.
- Use a drag-and-drop page builder.
- Add, edit, reorder, duplicate, and delete pages and subpages.
- Configure menus, navigation, headers, footers, banners, sliders, and forms.
- Add text, images, videos, documents, galleries, tables, product listings, and embedded applications.
- Configure SEO titles, descriptions, URLs, metadata, and redirects.
- Preview desktop and mobile layouts.
- Save drafts, schedule publication, and restore previous versions.
- Assign page-level permissions and content approval workflows.
- Manage media files and reusable content blocks.
- Publish websites to approved hosting and domain configurations.

Include a content management system with reusable page templates, revision history, publishing status, and media management.

## 10. Industry-specific system templates

Provide an Industry Template Marketplace within the administration dashboard.

An administrator should be able to create a new business workspace from a selected template without rebuilding the entire platform.

Initial templates:

### Educational consultancy ERP

- Student and applicant CRM.
- Course and institution catalogue.
- Enquiries, counselling, applications, and follow-ups.
- Document checklists and application status tracking.
- Staff tasks, appointments, and communication history.
- Student portal and public consultancy website.
- Educational content library and reporting.

Visa and immigration information must be verified through appropriate sources. Do not present AI-generated advice as a guaranteed visa outcome.

### Catering and hospitality ERP

- Menu and recipe management.
- Food costing and pricing.
- Ingredient inventory and supplier purchasing.
- Catering enquiries, quotations, bookings, and event calendars.
- Staff scheduling and event assignments.
- Venue, equipment, and logistics checklists.
- Customer database and repeat-order tracking.
- Catering website, menu publishing, and online enquiry forms.
- AI-assisted event planning and proposal generation.
- Food photographs analysed by AI to suggest menu descriptions, presentation ideas, and draft costing estimates for human verification.

### E-commerce ERP

- Product catalogue and variants.
- Stock, pricing, and promotions.
- Online orders, payments, refunds, and fulfilment.
- Customer CRM and support.
- Shipping integrations and order notifications.
- Sales analytics and abandoned-cart workflows.

### Education and learning platform

- Courses, lessons, enrolments, and assessments.
- Student and teacher dashboards.
- Learning materials, assignments, and progress tracking.
- Attendance, results, and certificates.
- AI-assisted lesson preparation and learning resources.
- Role-specific access for students, teachers, parents, and administrators.

### Professional services ERP

- Client CRM, project delivery, timesheets, proposals, invoicing, and document management.

Allow future templates for retail, agriculture, healthcare administration, logistics, manufacturing, and other industries.

Templates should configure existing modules, workflows, data models, permissions, dashboards, and website themes. They must not bypass security or create isolated, unmanaged copies of the core platform.

## 11. Attendance through QR codes

Create an attendance module with QR-based check-in and check-out.

Required features:

- Employee QR identity or time-limited dynamic QR codes.
- QR scanning through supported mobile devices.
- Check-in and check-out timestamps.
- Employee, location, shift, and attendance status.
- Late arrivals, missed check-outs, and exception handling.
- Manager review and correction workflows.
- Daily, weekly, and monthly reports.
- Exportable timesheets.

Implement protection against QR sharing, replay attacks, duplicate scans, and unauthorised attendance changes. Where appropriate, use short-lived signed tokens, authenticated sessions, and server-side validation.

Keep attendance data private and restrict access to authorised HR staff and managers.

## 12. Email, Gmail, WhatsApp and social media management

Create an Integrations Centre for connecting external communication services.

### Email and Gmail

- Connect authorised mailboxes through supported OAuth-based integrations.
- View and manage permitted messages, threads, labels, and contacts.
- Link conversations to CRM contacts, leads, and support tickets.
- Draft AI-assisted replies and templates.
- Support inbox assignment, follow-up reminders, and email activity tracking.

### WhatsApp

- Support authorised WhatsApp Business Platform integrations.
- Link conversations and enquiries to CRM records.
- Configure approved templates, notifications, and customer support workflows.
- Track delivery status and integration errors where supported.
- Respect messaging consent, platform policies, and applicable privacy requirements.

### Social media

- Provide integration adapters for supported Facebook, Instagram, LinkedIn, YouTube, and other approved services.
- Manage content calendars, drafts, campaign assets, and publishing workflows.
- Show engagement and campaign analytics where the provider API permits.
- Store access tokens securely and handle revoked permissions.

Do not simulate integrations with static screens. Show connection status and explain any provider permissions or setup steps still required.

## 13. Library and knowledge management

Create a central Library Management module for books, PDFs, documents, videos, research material, and internal knowledge.

Features:

- Upload and organise PDF, DOCX, XLSX, PPTX, image, and supported media files.
- Categorise, tag, search, filter, and preview files.
- Extract text from supported documents.
- Apply OCR where needed and supported.
- Create access-controlled collections.
- Search document content, not just filenames.
- Generate summaries, question answers, citations, and research notes from accessible sources.
- Track file versions, owners, permissions, and upload history.

### YouTube research

Allow users to submit YouTube URLs for research when access is permitted.

Use available official metadata, captions, or transcripts where legally and technically accessible. Provide source URLs, titles, timestamps where available, and a summary of the retrieved material.

Do not claim to have watched or transcribed inaccessible videos. Respect copyright, platform terms, and access restrictions.

## 14. Security, audit and compliance

Create a dedicated Security and Audit Centre.

Include:

- Role-based access control and tenant isolation.
- Multi-factor authentication for privileged accounts.
- Secure password storage and session management.
- Login history, failed login attempts, and suspicious activity alerts.
- Audit logs for user actions, permission changes, data exports, configuration changes, and administrative overrides.
- Searchable logs with actor, tenant, action, target, timestamp, and outcome.
- API access controls, rate limits, input validation, and secure file uploads.
- Encryption in transit and appropriate encryption at rest.
- Secure secrets management.
- Backup, restore, and disaster recovery procedures.
- Configurable data retention and deletion policies.
- Security testing and vulnerability reporting.
- Protection against common web application vulnerabilities, including broken access control, injection, cross-site scripting, and cross-tenant data exposure.

Audit records must be protected against unauthorised modification. Sensitive data and secrets must not be written to application logs.

Provide configurable notifications for security events and an alert dashboard for administrators.

## 15. Notifications and workflow automation

Build a notification and workflow engine.

Support:

- In-app notifications.
- Email notifications.
- Supported push notifications.
- Approved WhatsApp notifications.
- Per-user, per-role, per-module, and per-event notification settings.
- Enable and disable controls.
- Workflow triggers, conditions, actions, delays, and approval steps.
- Notification history, delivery status, retries, and error handling.

Example workflow: When a new sales lead enters the CRM, assign it to the appropriate representative, calculate an initial AI lead score, create a follow-up task, and notify the responsible manager.

## 16. Super Admin platform settings

Provide central configuration for:

- Licence plans and account quotas.
- Module catalogue and feature flags.
- Global themes and website templates.
- Tenant-specific branding and custom domains.
- AI providers, model settings, and usage limits.
- Approved integrations.
- Security policies and audit retention.
- Notification providers.
- System health and application configuration.
- Database backups, monitoring, and deployment settings.

Keep tenant-level configuration separate from global defaults. Record who changed settings, when the change occurred, and what was changed.

## 17. Technical architecture

Use a modular, maintainable architecture with clear separation between frontend, backend, database, authentication, AI orchestration, integrations, and background jobs.

Select the technology stack based on the capabilities and limitations of the chosen AI coding platform.

Preferred architecture:

- Frontend: React or Next.js with TypeScript and a responsive component system.
- Backend: FastAPI or NestJS, or the platform's supported server-side framework.
- Database: PostgreSQL for production multi-tenant relational data.
- Background processing: a queue and worker system for long-running AI tasks, scheduled reports, and integrations.
- File storage: private object storage with access-controlled downloads.
- Search: PostgreSQL search initially, with a vector database or vector extension when semantic retrieval is required.
- AI: a provider abstraction supporting approved language models and tools.
- Authentication: secure session or token management with MFA for privileged accounts.
- Deployment: containerised environments and managed cloud services where appropriate.
- Observability: structured logs, metrics, error tracking, health checks, and alerts.

If the coding platform uses its own database, authentication, hosting, or framework, adapt the design to the supported services while preserving the required security boundaries and business logic.

Do not expose API keys or privileged credentials in frontend code.

## 18. Core database design

Design and document a relational schema covering at least:

- Tenants and organisations.
- Licences, plans, subscriptions, quotas, and enabled modules.
- Users, roles, permissions, and role assignments.
- Departments, branches, sub-accounts, and teams.
- Modules, pages, navigation items, and feature flags.
- Dashboard layouts, widgets, and saved views.
- Websites, domains, themes, pages, and content revisions.
- CRM contacts, companies, leads, opportunities, and activities.
- Products, suppliers, inventory, and purchase orders.
- Employees, attendance, shifts, and leave.
- Projects, tasks, and approvals.
- Invoices, expenses, payments, and financial records.
- AI agents, tools, executions, usage, and approval records.
- Documents, file metadata, knowledge collections, and search indexes.
- Integration accounts, credential references, and webhook events.
- Notifications, workflow definitions, and execution history.
- Audit events, security alerts, and application settings.

Use appropriate primary keys, foreign keys, indexes, constraints, tenant ownership, and timestamps.

Define how tenant isolation is enforced at the database and application layers. Consider PostgreSQL row-level security where appropriate. Never rely only on hiding frontend menu items to protect data.

## 19. User interface and design

Create a professional, modern business application with:

- A collapsible sidebar.
- Global search.
- Breadcrumb navigation.
- Role-specific dashboards.
- Customisable KPI cards and charts.
- A notification centre.
- A user profile and settings menu.
- Quick-create actions.
- A consistent design system.
- Responsive mobile layouts.
- Light and dark modes.
- Accessible forms, keyboard navigation, and clear validation messages.

The Super Admin interface should prioritise platform operations and tenant management. The System Admin interface should prioritise organisation configuration. Department dashboards should show the tools and information relevant to their work.

Allow authorised administrators to customise the dashboard through drag-and-drop controls and lock layouts when required.

## 20. Functional acceptance criteria

The application is not complete until the following tests pass.

1. A Super Admin can create a tenant, issue a licence, configure limits, and assign its System Admin.
2. A System Admin can create an IT Admin but cannot exceed global permissions or licence limits.
3. A System Admin can enable modules using checkboxes and configure access for sub-accounts.
4. The backend enforces permissions even when users directly call APIs or modify frontend requests.
5. Two tenants cannot access each other's records, files, AI retrieval results, or administrative settings.
6. A user can customise a dashboard, save the layout, and lock it according to their permissions.
7. A lead can enter the CRM, move through a sales pipeline, and trigger a configured workflow.
8. AI-generated recommendations identify their source data and cannot execute unauthorised actions.
9. An administrator can create a website, add pages, change its theme, preview it, and publish it through a supported hosting configuration.
10. A website chatbot can be embedded through a documented installation snippet and capture enquiries in the correct tenant's CRM.
11. QR attendance creates validated check-in records and rejects unauthorised or replayed requests.
12. Audit logs record important administrative, security, and data-changing events.
13. Notification preferences control the relevant notification channels and events.
14. Document uploads, content searches, and AI summaries respect access permissions.
15. External integrations clearly distinguish connected, disconnected, failed, and unconfigured states.
16. Licence expiry, suspension, and quota enforcement work consistently across the frontend and backend.
17. Automated tests cover authentication, permissions, tenant isolation, core workflows, and critical API endpoints.

## 21. Development roadmap

Build the platform incrementally. Do not attempt to implement every module in one generation.

### Phase 1: Platform foundation

Implement authentication, tenant management, licences, account hierarchy, roles, permissions, module registry, and basic audit logging.

### Phase 2: Dynamic administration

Implement module checkboxes, sub-account configuration, navigation management, dashboard widgets, drag-and-drop layouts, and layout locking.

### Phase 3: Core CRM and ERP

Implement CRM, sales pipeline, customers, tasks, inventory, workforce management, and the initial finance module.

### Phase 4: AI and business intelligence

Implement the AI assistant, sales and marketing agents, report generation, document generation, approval queues, and usage monitoring.

### Phase 5: Website and content management

Implement multi-website management, page builder, themes, content publishing, chatbot embedding, and tenant-specific knowledge sources.

### Phase 6: Communications and specialist modules

Add Gmail, WhatsApp Business, social media integrations, library management, YouTube research, and industry templates.

### Phase 7: Production readiness

Complete automated tests, security reviews, performance testing, backups, monitoring, migration procedures, documentation, and deployment.

## 22. Instructions for the AI coding agent

Before implementing the system:

1. Inspect the coding platform's available features, framework, database, authentication, storage, and hosting capabilities.
2. Produce a proposed architecture, database schema, module dependency map, and implementation backlog.
3. Identify features that require external API credentials, paid services, provider approval, or separate infrastructure.
4. Identify technical limitations and propose alternatives before implementing unsupported features.
5. Build Phase 1 as a working end-to-end application.
6. Test each implemented feature against explicit acceptance criteria.
7. Maintain a clear list of completed, partially implemented, blocked, and planned features.
8. Continue to the next phase only after the current phase passes its essential tests.
9. Keep the architecture modular so future modules can be installed and enabled without rewriting the platform.
10. Never label a feature as complete if it is only a mockup, static example, or nonfunctional button.

For every phase, provide the working functionality, database changes, security controls, tests, setup instructions, and known limitations.

Begin by presenting the architecture, database plan, account hierarchy, and Phase 1 implementation plan. Then implement Phase 1 without replacing it with a static prototype.

The final objective is a reusable SaaS platform from which an administrator can create and manage different business systems, including educational consultancy ERP, catering ERP, e-commerce ERP, and education management platforms, using shared modules, configurable permissions, AI agents, and industry-specific templates.

## Recommended implementation strategy

The complete system is a substantial software product. Use the master prompt as the overall specification, then develop and verify it in stages.

## Build order

1\. Super Admin and multi-tenant foundation

Account hierarchy, licences, roles, permissions, tenant isolation and audit logs.

2\. Dynamic dashboard and module builder

Checkbox-based access, drag-and-drop widgets, locked layouts and reusable modules.

3\. CRM, ERP and business intelligence

Sales, inventory, staff, reports, workflows and business records.

4\. AI agents and website builder

AI automation, document generation, public chatbots, themes and industry templates.

## One important architectural decision

Keep three separate layers in the system:

- Platform layer: Super Admin, licensing, global policies and tenant provisioning.
- Business application layer: ERP, CRM, BI, HR, marketing and industry-specific modules.
- Presentation layer: Websites, themes, public chatbots, user dashboards and page layouts.

This separation will make it easier to offer one platform to many businesses while allowing each customer to have a different combination of modules and websites.

My recommendation: Start with the Super Admin, licence management, account hierarchy, and dynamic permission engine. These components determine how every other module will work.

Before building, one decision will help tailor the prompt to your intended platform: Which AI coding platform will you use first? Base44, Lovable, Replit, Bolt, or a custom codebase using VS Code?