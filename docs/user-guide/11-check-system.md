# 11. Check system

*User guide, chapter 11 · Last updated 21 October 2026 (backups added)*

**Who this is for:** System Admins, IT Admins and Business Owners of a business, and the platform Super Admin.

The **Check system** button tests whether everything works, in a few seconds, and shows the results in plain words.

## 11.1 Run the checks

1. Click **Check system** at the top right of any admin page (or open `/system-check/` on your address).
2. Click the **Check system** button.
3. After a few seconds you see the results.

You can run the checks once a minute. They also run **every hour by themselves**.

Who can use it:
- on a business site: people with **Settings – View** (System Admin, IT Admin and Business Owner by default). Shop Staff cannot.
- on the platform site: people with **Platform settings – View** (Super Admin and Platform Security Admin).

## 11.2 Read the results

The result at the top is the worst result of all the checks.

| Result | Meaning |
|---|---|
| ✓ **OK** (green) | Works |
| ! **Needs attention** (amber) | Works, but something should be fixed or will stop soon |
| ✕ **Failed** (red) | Broken. Fix it now |
| – **Not set up** (grey) | Not set up yet. This does not change the overall result |

Each check shows a short message that says what to do. Messages never show passwords, keys or technical error details. Those go to the server log only.

## 11.3 What a business check tests

| Area | Check | What it tests |
|---|---|---|
| System | Database | The business's data can be read, and all updates are applied |
| System | Cache (Redis) | Sign-in limits and background jobs can store values |
| System | Background jobs (worker) | A background worker answers |
| System | Scheduled jobs | A scheduled job ran in the last 15 minutes |
| Business | Licence | The licence is valid; amber 7 days before a trial or licence ends, and in the grace period |
| Business | Web address | The business has a main address (chapter 10) |
| Connections | Each saved connection | Each API key on the Integrations page is tested with the provider, like the **Test** button (chapter 4). All are tested at the same time, 10 seconds at most each |
| Connections | Email sending | The business's own email connection, or the platform's |
| Connections | WhatsApp messages | When the last call from Meta arrived, and whether it was accepted |
| Security | Two-step verification | Staff who have not set it up, or have it switched off |
| Security | Audit log | The audit log is complete and unchanged |
| Backups | Backups | The last backup worked and is not older than planned. Grey "Not set up" until backups to your Google Drive are set up (chapter 12) |
| Backups | Copy in Google Drive | The last backup was copied to your Google Drive, and Google still accepts the access |
| Backups | Restore test | The last restore test passed, and it is not older than about two weeks |

The checks only read and test. They never send messages, charge money or change business data. Testing a connection updates its **Connected / Failed** status, like the Test button.

## 11.4 What the platform check tests (Super Admin)

Database, every business's database, cache, background worker, scheduled jobs, disk space, licences that need attention (ending within 7 days, grace period, expired), businesses with failed connections or a failed last check, the platform's own connections, the secret vault master key, security settings, platform admins' two-step verification, the platform audit log, and backups (the backup encryption key, the last backup, the copy in Google Drive and the last restore test; chapter 12).

On a laptop, **Copy in Google Drive** shows **Needs attention** until a Google Drive is connected on the platform's Backups page.

On a laptop, **Security settings** always shows **Needs attention**, because development mode is on there. That is fine on a laptop, but never on a real server.

## 11.5 Earlier runs and alerts

- **Earlier runs** at the bottom of the page lists the last 20 runs: when, the result, and who started it (or "Schedule"). Click a run to see its details. The last 500 runs are kept.
- When an **hourly** check turns red, an email goes to:
  - for a business: its System Admins and IT Admins
  - for the platform: the Super Admins

  The email lists the problems and links to the page. It is not sent again while the check stays red, only when it turns red again later.
- Every run is recorded in the audit log.

Later, a red result will offer **Create ticket** (task 1.15).
