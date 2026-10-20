# 3. Businesses, licences and modules

*User guide, chapter 3 · Last updated 21 October 2026*

**Who this is for:** the platform Super Admin (sections 3.1–3.4) and each business's System Admin (sections 3.5–3.6).

## 3.1 Create a new business (Super Admin)

1. Open the platform admin (for example `https://<platform-domain>/admin/`) and go to **Tenants → Add tenant**.
2. Enter:
   - **Name**, for example *Gorkha Butchery*
   - **Business id**, for example `gorkhabutchery` (lowercase letters, numbers and underscores; it never changes)
   - **Web address name** (optional), for example `gorkha`, so the business opens at `gorkha.<platform-domain>`. Leave it empty to use the business id. See chapter 10
   - **Industry**, which chooses the starting modules
   - **System Admin email** (optional), which sends them an invitation
3. Click **Save**.

The new business gets:
- its own private database area and web address
- a **30-day free trial** (no automatic charge when it ends)
- the default roles (chapter 2)
- the modules for its industry, for example a butchery gets Products, Inventory, Orders, CRM and Reports

## 3.2 Invite the business's System Admin

On the business's page, click **Invite System Admin** and enter their email. They get an email with a link to set their password on their own business site (the link works for 1 hour). After that, they set up two-step verification.

## 3.3 Licence and limits

On the business's page, in the **Licence** section, you can change:

| Field | Meaning |
|---|---|
| Plan name | Shown to the business (plans and prices come in Phase 2) |
| Trial ends at | End of the free trial |
| Ends at | End of a paid period (leave empty for no end date) |
| Grace days | Days the business can still work after the trial or period ends (default 7), with a "please renew" warning |
| Max users | Active users allowed; adding more is refused |
| Max websites, Storage, AI credits, API calls | Limits for modules that arrive later |

**Modules:** tick **Entitled** for the modules included in the licence. The business can then switch them on or off. Unticking **Entitled** also switches the module off.

## 3.4 Suspend, reactivate, extend a trial, mark as paid

- **Suspend:** on the business's page, click **Suspend business** and enter a reason. Everyone in that business, including its admins, sees "This account is suspended". The reason is recorded in the audit log.
- **Reactivate:** in the **Tenants** list, tick the business, choose **Reactivate selected businesses** and click **Go**. The business returns to its earlier status (trial or active).
- **Extend trial:** choose **Extend trial by 14 days**.
- **Mark as paid:** choose **Mark selected as paid (active licence)**.

Account states:

| State | Can the business work? |
|---|---|
| Trial | Yes |
| Active (paid) | Yes |
| Grace | Yes, with a renewal warning |
| Expired | No (after the grace period) |
| Suspended | No |
| Cancelled | No |

## 3.5 Switch modules on or off (business System Admin)

A System Admin (or anyone with *Business settings – Configure*) can switch the modules included in the licence on or off. A module that is off is blocked for everyone in the business, whatever their role.

Core modules (users, roles, settings, integrations, audit log) are always on. Modules not in the licence can only be added by the platform.

*In the app (coming with the React screens):* **Settings → Modules**. Until then this is available through the API (`/api/tenant/modules/`).

## 3.6 See your licence and usage

**Settings → Licence** (API: `/api/tenant/licence/`) shows the plan, status, trial end date, and usage against each limit, for example *Users: 6 of 10*.


## 3.7 Businesses and users (Super Admin)

Click **Businesses and users** at the top right of the platform admin (or open a business and click **Users and roles**).

- The first page lists every business: its users, how many are active, and how many staff have two-step verification (MFA) **on**, **not set up**, or **switched off**. The platform's own administrators are listed below.
- Click a business to see its users, their roles, MFA status and last login.
- Click a user to:
  - **Change roles:** tick the roles and click **Save roles**.
  - **Reset MFA:** they set it up again at their next login (for a lost phone).
  - **Switch MFA off:** type a reason and click **Switch MFA off**. That person then signs in with a **password only**. Use this only for a short time and switch it on again (**Switch MFA on again**), because a stolen password is then enough to sign in. Accounts with MFA off are shown in red.
  - **Lock / Unlock** the account. Unlocking counts against the business's user limit.
  - See their recent sign-in history.

Every change is recorded in the platform audit log **and** in the business's own audit log, as "Platform administrator (your email)", so the business can see what you changed.

Safety rules: you cannot lock your own account or change your own roles, and the last active Super Admin cannot be locked.

Who can use these pages: platform roles with *Tenants – View* can look; *Tenants – Administer* can change business users. Platform administrators need *Platform admin users – View/Edit* (and *Platform roles – Assign* for roles). The Super Admin role has all of these.
