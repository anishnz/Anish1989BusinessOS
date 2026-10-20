# 2. Roles, permissions and the audit log

*User guide, chapter 2 · Last updated 21 October 2026*

**Who this is for:** System Admins, IT Admins, Business Owners and Auditors.

## 2.1 How access works

- People can only do what their **roles** allow. A new user has **no access** until someone gives them a role.
- A person can have more than one role. Their permissions add up.
- Each permission is a **module** plus an **action**, for example *Orders – Approve* or *Finance – Export*.
- Roles belong to one business. A role in Gorkha Butchery gives nothing in another business.
- If the business is **suspended**, nobody can use it, including admins, until it is active again.

## 2.2 Default roles

Every business starts with these roles. You can change their permissions, except **System Admin**, which always has everything. Default roles cannot be deleted.

| Role | What it is for |
|---|---|
| System Admin | Full control of the business, users, roles and settings |
| IT Admin | Users, integrations, security settings, technical support |
| Business Owner | All business modules, reports and the audit log |
| Department Manager | A team's records, approvals and reports |
| Sales Manager / Sales Representative | Sales pipeline and orders |
| Marketing Manager / Marketing Staff | Campaigns and content |
| Finance Manager / Accountant | Invoices, payments, reconciliation |
| HR Manager / HR Staff | Employees, shifts, attendance |
| Inventory Manager | Stock, suppliers, purchasing |
| Operations Manager | Orders, events, tickets |
| Shop Staff | Counter and kitchen staff: see products, look up and add customers, take and update orders, report issues |
| Content Manager | Websites, courses, job posts |
| AI Manager | AI agents and approvals |
| Support Agent | Customer tickets |
| Employee | Own tasks and tickets |
| Auditor | Read-only access to records and the audit log |
| Teacher or Trainer | Courses and learners |
| Customer, Supplier, Affiliate, Student | Portal only (their own records), no back-office access |

## 2.3 Give someone a role

*In the admin (superusers):* **Roles and permissions → User roles → Add**, choose the user and the role, then **Save**.

*In the app (coming with the React screens):* open the user, choose **Roles**, tick the role.

Safety rules (enforced everywhere):

- You can only give a role whose permissions **you have yourself**.
- You **cannot change your own roles**. Ask another admin.
- Only a full administrator can give **System Admin**.

## 2.4 Create a custom role

1. **Roles and permissions → Roles → Add role**.
2. Enter an id (for example `catering_coordinator`), a name and a description.
3. Tick the permissions, one row per module.
4. Click **Save**.

You can only tick permissions that you have yourself.

*Screenshot: role editor (added automatically with the user-guide screenshots, task 1.17)*

## 2.5 The audit log

**Audit log → Audit events** lists every important action: logins and failed logins, two-step verification, changes to users and roles, and refused actions ("permission denied").

Each entry shows **when**, **who**, **what**, **on which record**, the **result** and the **IP address**. You can search and filter.

The audit log **cannot be edited or deleted**, not even by the System Admin or directly in the database. Each entry is chained to the one before it, so any change would be detected. Passwords, codes and keys are never written to it.

Platform support can run a check of the whole audit log at any time (`verify_audit_chain`).
