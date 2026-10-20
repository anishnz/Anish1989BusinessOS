# 12. In-app user guide

Last updated: 21 October 2026

## Goal

Every dashboard has a built-in user guide that explains how to use it, step by step, with screenshots. It reads like a book with a table of contents, and each user only sees the parts for the dashboards they can use.

## Where users find it

- A **Help** (?) button on every page opens the guide at the chapter for that page.
- A **User guide** item in the menu opens the full book with its table of contents.
- A search box finds topics across the guide.

## Structure (book style)

```
User guide
├── 1. Getting started
│   ├── 1.1 Logging in and MFA
│   ├── 1.2 First-login setup wizard (IT admin)
│   └── 1.3 Your dashboard at a glance
├── 2. Super Admin dashboard
├── 3. System Admin dashboard
├── 4. IT Admin dashboard
│   ├── 4.1 API keys and integrations
│   ├── 4.2 Google Drive backups
│   └── 4.3 Check system button
├── 5. Orders dashboard (staff)
├── 6. Products and inventory
├── 7. Customers and CRM
├── 8. Business intelligence
├── 9. Website and content editor
├── 10. Tickets and support
├── 11. Competitor intelligence
├── 12. Catering and events
├── 13. Learning and jobs
└── Glossary and FAQ
```

Each chapter page has:
- What this page is for (one or two sentences)
- Who can use it (roles)
- Step-by-step instructions with numbered screenshots
- Common problems and fixes
- Related chapters

## Role-based guides

- Users see only the chapters for dashboards and modules they have permission to use.
- Chapters for modules that a tenant has turned off are hidden.
- A Super Admin can preview the guide as any role.

## Screenshots

- Screenshots are taken **automatically** by a browser test script (Playwright) using demo data, so they stay up to date when the screens change.
- Demo data only: no real customer information appears in screenshots.
- Screenshots are numbered and can have arrows or highlights added.

## Editing and AI

- Platform admins can edit guide text in the backend (Markdown editor with preview).
- Tenants can add their own pages, for example "How we pack catering orders".
- "Generate with AI" drafts a guide page from the screen's fields and actions. A person reviews and publishes it.
- Every edit is versioned.

## Export

- Download the full guide, or one chapter, as a PDF book with a table of contents and page numbers.
- Print-friendly layout.

## Rule for the team

A feature is not "done" until its user guide page exists (added to the definition of done in the [Delivery plan](10-delivery-plan.md)).
