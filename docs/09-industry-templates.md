# 09. Industry templates

Last updated: 21 October 2026

One core platform serves many kinds of business. An **industry template** is a set of modules, forms, workflows, dashboards and website pages that are switched on for that type of business. A template configures the core; it never creates a separate copy of the platform.

## Businesses the system can serve

| # | Business | What the system does | Main modules | Difficulty |
|---|---|---|---|---|
| 1 | Gorkha Butchery (meat shop) | WhatsApp orders by weight, final price after weighing, pickup slots, stock, wastage, daily sales | WhatsApp ordering, inventory, sales import, BI, QR loyalty | Low |
| 2 | Small fast-food restaurant | WhatsApp orders, order summary, kitchen queue, "ready" message, combo offers | WhatsApp ordering, orders, live order board, coupons, BI | Low |
| 3 | Restaurant | Menu orders, takeaway or delivery, table bookings, preferences, menu performance | Orders, bookings, CRM, feedback, BI | Low–medium |
| 4 | Joe's Catering | Event enquiries, guest numbers, dietary needs, quotes, follow-ups, deposits | CRM, quotations, events, invoices, bank reconciliation, AI documents | Low–medium |
| 5 | Retail shop / online store | Product enquiries and orders, stock, repeat customers | Commerce, inventory, WhatsApp ordering, BI | Low–medium |
| 6 | Service business (cleaning, repairs, salon) | Service requests, bookings, staff assignment, quotes, invoices | Bookings, HR and shifts, quotations, invoices | Low–medium |
| 7 | Marketing and sales tracking | Leads from QR, website and WhatsApp; campaign tracking; channel revenue | CRM, campaigns, referrals, funnel and attribution charts | Medium |
| 8 | Education consultancy | Student enquiries, country, course, budget, English scores, counsellor follow-ups, application status | CRM pipeline, document checklist, appointments, AI assistant | Medium |
| 9 | Education website / e-learning | Courses, lessons with embedded YouTube videos and links, PDFs, enrolment, progress, quizzes | Website builder, learning module, library, notifications | Medium |
| 10 | Cybersecurity education website | Lessons, YouTube tutorials, quizzes, phishing-awareness tips, completion, certificates | Learning module, assessments, certificates | Medium |
| 11 | Event creation and management | Event type, date, venue, guests, budget, suppliers, schedule, RSVPs, reminders | Events, CRM, tasks, quotations, notifications | Medium–high |
| 12 | Job platform (job board, ATS resume builder, Auckland job listings) | Job listings by location, resume builder, applications, job alerts | Jobs and careers module (see below) | Medium |
| 13 | Government website / citizen portal | Service information, enquiries, appointments, status checks, routing | Website builder, chatbot, bookings, workflows | High (later stage) |

## Template groups

Businesses that share a flow are built together:

| Group | Shared flow | Businesses |
|---|---|---|
| A. Ordering | Products → chat order → confirm → prepare → pickup or delivery | Butchery, fast food, restaurant, retail |
| B. Enquiry and booking | Enquiry → details → quote → deposit → event or service → follow-up | Catering, events, service businesses |
| C. Learning and careers | Content → enrol or apply → progress → outcome | Education consultancy, e-learning, cybersecurity education, job platform |
| D. Public services | Information → request → routing → status | Government portal (later) |

## YouTube and video content

- Use YouTube's official embed (iframe) or plain links. No API key is needed for this.
- Use privacy-enhanced mode (`youtube-nocookie.com`).
- Only embed videos that the owner allows to be embedded.
- Store the video URL, title, and the lesson it belongs to. Do not download or re-host YouTube videos.

## Jobs and careers module

This module is part of the same platform (decision D-021).

| Feature | Description |
|---|---|
| Job board | Employers (tenants) post jobs with location, type, pay range and closing date |
| Job listings by location | Show Auckland jobs on a map and in a list, filtered by suburb, type and category |
| ATS-friendly resume builder | Simple single-column templates, standard headings, export to PDF and DOCX, keyword check against a job ad |
| Applications | Job seekers apply; employers see applicants in a simple pipeline |
| Job alerts | Email or WhatsApp alerts for new jobs that match a saved search (with opt-in) |
| AI helper | Suggests resume improvements and cover letter drafts. The user reviews every change. |

### Where job listings come from (legal sources only)

1. Jobs posted directly on the platform by employers.
2. Official partner feeds or APIs, used only under their terms.
3. Public company career pages that allow crawling (robots.txt and terms checked).

Big job sites restrict scraping and reuse. For example, Trade Me's developer business rules say its data must not be combined or presented alongside listings from other sites, or used in data aggregation systems. Check Seek, LinkedIn and others before using any of their data. Every crawled job shows its source link and date, and is removed when the source listing closes.

### Privacy for job seekers

- Resumes contain personal information. Collect only what is needed, let users delete their data, and never share a resume without the user's action.
- Job seekers' data is separate from business tenants' customer data.

## Government portal note

Possible later, but much harder. It needs NZ government web accessibility and usability standards, NZISM security controls, often official identity login (such as RealMe), and formal approvals. Sensitive applications should not be handled through chat alone.
