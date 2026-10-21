# 08. Open questions

Last updated: 22 October 2026

Answer these before writing code. When a question is answered, move the answer to [02. Decisions](02-decisions.md).

## Competitor intelligence

| # | Question | Options |
|---|---|---|
| Q-04 | What should be compared? | Prices, products or menu, offers, opening hours, Google reviews and ratings, social media activity |
| Q-05 | Where should it look? | Competitor websites only / Also Google Maps listings / Also Facebook and Instagram pages |
| Q-06 | How is the weekly report delivered, and when? | Dashboard only / Also email / Also WhatsApp, plus day and time |
| Q-07 | Should limits depend on the plan? | For example 5 competitors on Starter and 20 on Business |

## Platform

| # | Question | Notes |
|---|---|---|
| Q-08 | Hosting provider? | For example AWS Sydney, Azure Australia East, DigitalOcean or a local NZ host |
| Q-09 | Which places or search API for finding competitors? | Check terms, cost and data storage rules |
| Q-10 | First industry template? | The blueprint suggests a butchery or small food retailer |
| Q-11 | Domain name for the platform? | anish1989.com.np is the personal brand site |

## Pilots and jobs module

| # | Question | Notes |
|---|---|---|
| Q-12 | Monthly price for each pilot business after the pilot? | Write it in the pilot agreement |
| Q-13 | Pilot length? | For example 4 or 8 weeks |
| Q-14 | Which job sources can we use legally? | Employer-posted jobs first; check each site's terms before using its data |
| Q-15 | Who are the resume builder's main users? | For example students, new migrants, career changers in Auckland |

## Platform operations

| # | Question | Notes |
|---|---|---|
| Q-16 | Whose Google Drive receives backups? | **Answered:** both. Platform owner's Drive for the whole database, and each tenant's own Drive for its own data (D-031) |
| Q-17 | Backup retention? | **Answered:** every backup for 7 days, daily to 30 days, monthly for 12 months (D-099) |
| Q-18 | Platform domain name for tenant subdomains? | For example `<tenant>.<platform-domain>` |
| Q-19 | Which registrar for domain search and purchase (later)? | Needs an account and API access |

## Answered

| # | Question | Answer | Decision |
|---|---|---|---|
| — | Pilot order | Core, then butchery + restaurant, then catering + events, then education + jobs | D-020 |
| — | Job tools: separate or same platform? | Module in the same platform | D-021 |
| — | What did businesses agree to? | Pay after the pilot | D-022 |
| — | Working time | Full-time | D-023 |
| Q-01 | Can customers pay inside the chat? | No: pay at pickup or on delivery (22 Oct 2026) | D-117 |
| Q-02 | Fulfilment type? | Pickup and delivery (22 Oct 2026) | D-118 |
| Q-03 | Which languages should the AI understand? | English and Nepali, including Nepali in English letters (22 Oct 2026) | D-119 |
