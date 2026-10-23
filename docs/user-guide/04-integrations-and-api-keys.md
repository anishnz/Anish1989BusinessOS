# 4. Integrations and API keys

*User guide, chapter 4 · Last updated 23 October 2026*

**Who this is for:** each business's IT Admin and System Admin (sections 4.1–4.7), the platform Super Admin (section 4.7), and the person who runs the server (section 4.8).

An **integration** connects your business to an outside service, for example an AI model, WhatsApp, email or SMS. Each business adds its own keys. Your keys are only used for your business, and nobody, not even the platform Super Admin, can see them again after you save them.

## 4.1 Open the Integrations page

1. Log in to your business site, for example `https://gorkhabutchery.<platform-domain>/admin/`.
2. In the menu, open **Integrations and API keys → Connections** (or go to `/settings/integrations/`).

You need the **Integrations** permission. The **IT Admin** and **System Admin** roles have it by default. Other roles, such as Business Owner, do not see this page unless a System Admin gives them the permission (chapter 2).

| Permission | What it lets you do |
|---|---|
| View | See the list of connections and their status |
| Configure | Change names and settings, run **Test connection**, and **Disable** or **Enable** |
| Manage integrations | Add or **Remove** connections, and add or change keys |

## 4.2 Add a connection

1. Under **Add a connection**, click the service you want.
2. Fill in the form:
   - **Name**, for example *Main AI* or *Shop WhatsApp*
   - **Settings**, for example the AI model or the WhatsApp phone number ID
   - **Keys**, for example the API key or access token. These fields show dots while you type.
   - **Backup**: tick this for a second connection that is used only when the main one fails (for example a second AI provider).
3. Click **Save**.

After saving, you only see the **last 4 characters** of each key, for example `••••abcd`. This lets you check which key is saved without showing it.

### Services available now

| Group | Services |
|---|---|
| AI | OpenAI, Anthropic (Claude), Google Gemini, Ollama (your own AI server) |
| Messaging | WhatsApp Cloud API, Viber, Telegram |
| Email | Gmail, or your own email server (SMTP) |
| SMS | Twilio |
| Search | Google Places (for competitor reports) |
| Payments | Bank transfer details |
| Website protection | Cloudflare Turnstile (spam check on the enquiry form, chapter 23.4) |

Card payments (Stripe, Windcave, PayPal) are shown as **(coming later)**.

## 4.3 Test a connection

Click **Test connection** next to a connection. The platform makes one small, safe request to the service, for example "list models" for an AI provider. You see one of these:

| Status | Meaning |
|---|---|
| Not tested | Saved, but not tested since the last change |
| Connected | The test worked |
| Failed | The test did not work. The message says why, for example "The provider refused the key" |
| Disabled | Switched off by you. It is not used or tested |

Tip: test again after you change a key at the provider's website.

## 4.4 Change a connection

1. Click **Edit**.
2. Change the name or settings.
3. To change a key, type the new key. **To keep the saved key, leave the key field empty.**
4. Click **Save**. The status goes back to **Not tested**, so run **Test connection** again.

People with **Configure** but not **Manage integrations** can change names and settings, but not keys.

## 4.5 Switch off or remove

- **Disable** keeps the connection but stops it being used. **Enable** switches it back on.
- **Remove** deletes the connection and its keys for good. You will need to enter the keys again to get it back.

## 4.6 Safety notes

- Keys are encrypted (AES-256-GCM) before they are saved. A key saved for one business cannot be opened by another business.
- Keys never appear in the audit log, error messages or emails. The audit log only records *which* fields were changed, and by whom.
- For your own safety, connections to private network addresses (such as `127.0.0.1` or `192.168.x.x`) are refused on the live platform. An Ollama server must have a public web address.
- If you think a key has leaked, create a new key at the provider's website, paste it here with **Edit**, and then delete the old key at the provider.

## 4.7 Send emails with Gmail

The platform sends invitations, password-reset links and notices by email. They go out through a Gmail account.

**Which account is used:**
1. If the business has saved its own Gmail (or SMTP) connection, its emails go out from that account.
2. If not, they go out from the **platform's** Gmail, with a sender name like *Gorkha Butchery via Anish1989 Business OS*.
3. Invitations to a new business's System Admin always use the platform's Gmail.

**Step 1: create an app password at Google** (once per Gmail account)
1. Sign in to the Gmail account at [myaccount.google.com](https://myaccount.google.com).
2. Go to **Security** and turn on **2-Step Verification** if it is not on yet.
3. Open [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
4. Type a name, for example *Business OS*, and click **Create**.
5. Google shows a 16-letter password. Copy it. Google shows it only once.

Use the app password, not your normal Gmail password. If you change your Gmail password later, Google removes your app passwords, so you will need to create a new one and save it here.

**Step 2: save it on the Integrations page**
1. Platform's Gmail: open the platform site (for example `http://localhost:8000/settings/integrations/`). A business's own Gmail: open that business's site.
2. Under **Add a connection**, click **Gmail**.
3. Enter the **Gmail address**, a **Sender name** (optional) and the **App password** (spaces are fine).
4. Click **Save**, then **Test connection**. It should say *Connected to Gmail*.

**Step 3: send yourself a test email** (the person who runs the server)

```
docker compose exec web python manage.py send_test_email --to you@example.com
```

Add `--schema gorkhabutchery` to test a business's own connection.

**Limits:** a personal Gmail account can send about 500 emails a day. That is enough for invitations and password resets. Marketing emails will need a proper email service later.

## 4.8 The master key (for the person who runs the server)

All saved keys are protected by one **master key**. It is the `VAULT_MASTER_KEYS` line in the `.env` file.

- The start scripts (`start.cmd`, `start.ps1`, `start.sh`) create it the first time.
- **Back it up now**, for example in a password manager. If the `.env` file is lost and you have no backup, all saved keys are lost and every business must enter them again. Database backups do not contain the master key, which is on purpose.
- Never put the master key in Git, email or chat.

**To change the master key (rotation):**

1. Create a new key (for example by running the start script on a copy of `.env` with the line removed, or with `openssl rand -base64 32`).
2. Put the new key first and keep the old one after it, separated by a comma:
   `VAULT_MASTER_KEYS=k2:NEWKEY...,k1:OLDKEY...`
3. Restart the platform, then run:
   `docker compose exec web python manage.py rotate_vault_key`
4. When it reports success, you can remove the old key from the line and restart again. Keep a backup of the old key for a while, in case an old database backup needs it.
