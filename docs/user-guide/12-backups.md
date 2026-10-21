# 12. Backups

*User guide, chapter 12 · Last updated 21 October 2026*

**Who this is for:** System Admins and IT Admins of a business, and the platform Super Admin. Business Owners can see the Backups page but cannot change it.

There are two kinds of backup:

| | Platform backups | Your business's backups |
|---|---|---|
| What | The whole platform: every business's data | Only your business's data |
| Where | On the platform's server, plus a copy in the platform owner's Google Drive | In **your own** Google Drive |
| Locked with | The platform's backup key | **Your backup passphrase** |
| Set up by | The Super Admin | Your IT Admin or System Admin |

Every backup is encrypted **before** it leaves the server. Google cannot read it, and nobody can open it without the key or the passphrase.

## 12.1 Open the Backups page

Click **Backups** at the top right of any admin page (or open `/backups/` on your address).

- People with **Settings – Configure** (System Admin and IT Admin) can use the buttons and change settings.
- People with **Settings – View** (also the Business Owner) can only look.
- On the platform site: **Platform settings – View** to look, **Platform settings – Configure** to change.

## 12.2 Set up backups for your business

The page shows three steps until backups are set up.

1. **Set a backup passphrase.** Under **Backup passphrase**, enter your own password and click **Make a passphrase for me**. The passphrase is shown **once**. Save it in a password manager or another safe place. You can also type your own (at least 16 characters, several words work well).
2. **Connect Google Drive.** Under **Google Drive**, enter your password and click **Connect Google Drive**. Google asks you to sign in and to allow access. The platform asks only for access to **the files it creates itself** (Google's "drive.file" permission). It cannot see anything else in your Drive.
3. Click **Back up now**, then **Test restore**.

After that, backups run by themselves.

> **Important:** without the passphrase, nobody can open your backups, not even the platform. If you change it, new backups use the new one, and older backups still need the old one. Keep both.

## 12.3 What happens automatically

- **Every 6 hours** (you can choose every 12 hours or once a day under **Settings**), a new backup is made and copied to Google Drive, into the folder `Anish1989 Backups - <your business>`. You can rename the folder under **Settings**.
- **Every 7 days**, a **restore test** runs: the newest backup is downloaded from Google Drive, opened with the passphrase, checked, and loaded into a temporary test database. Every table's number of rows must match the numbers saved when the backup was made. The test database is deleted afterwards. A backup only counts once a restore from it has worked.
- **Old copies are removed**, in Google Drive and on the server:
  - every backup from the last 7 days is kept,
  - then one backup a day up to 30 days,
  - then one backup a month for 12 months.

  Only backup files the platform made are removed. Your other Drive files are never touched.
- The server keeps only the newest copy of your business's backup. The platform's own backups also contain your data.

## 12.4 Read the page

| Item | Meaning |
|---|---|
| **Last backup** | Result and time of the newest backup |
| **Last good backup** | Time, size, and whether it is in Google Drive |
| **Next backup** | When the next one starts (the schedule looks every 15 minutes) |
| **Last restore test** | Result of the newest restore test |
| **History** | The last 20 backups and restore tests, who started them ("Schedule" when automatic), and a short message |

Results: ✓ **OK**, ! **Needs attention**, ✕ **Failed**, … **Waiting** or **Running**. While a run is going, the page updates itself every 5 seconds.

Messages never show passwords, passphrases, keys or technical errors. Those stay in the server log.

## 12.5 When something goes wrong

- **A scheduled backup or restore test fails:** your System Admins and IT Admins get **one email**. They do not get another one until it works again and fails again later. The problem also shows in **Check system** (chapter 11).
- **"Copies to Google Drive have stopped"**: Google no longer accepts the access, for example because someone removed it in the Google account, or the password of the Google account changed. Click **Connect Google Drive** again (enter your password). Until then, no backups of your business are made.
- **"The Google Drive is full"**: free up space in the Google account, or buy more storage.
- A failed backup is tried again after 1 hour.

To stop backups to Google Drive, click **Disconnect** (with your password). Copies already in the Drive stay there.

## 12.6 Google sign-in app (Super Admin, once)

Before anyone can click **Connect Google Drive**, the platform needs a Google sign-in app. You make it yourself in Google Cloud. Nobody else can do this for you, because it is your Google account.

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project, for example `Anish1989 Business OS`.
2. **APIs & Services → Library**: turn on the **Google Drive API**.
3. **APIs & Services → OAuth consent screen** (Google Auth Platform): app name, support email, and the scope `.../auth/drive.file`. While testing, add your own Google accounts as **test users**.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**, type **Web application**.
5. Under **Authorised redirect URIs**, add the address shown on the platform's Backups page, for example `https://<platform address>/oauth/google/callback/` (on a laptop: `http://localhost:8000/oauth/google/callback/`).
6. Copy the **Client ID** and **Client secret**. On the platform site, open **Integrations**, add **Google sign-in app (for Google Drive backups)**, paste both, save, and click **Test connection**.

Businesses use the platform's sign-in app. A business can also add its own on its Integrations page.

> Before real businesses use it, Google must **verify** the app (branding and privacy review). While the app is in "Testing", only the test users can connect, and Google may ask them to connect again after 7 days.

## 12.7 Platform backups (Super Admin)

- Platform backups run every 6 hours and are kept on the server in the `backups` folder (a Docker volume). Connect a Google Drive on the platform's Backups page for an off-site copy.
- They are locked with **BACKUP_ENCRYPTION_KEYS** from the `.env` file. The start script creates it. **Save a copy outside the server**, together with `VAULT_MASTER_KEYS`. A backup without its key cannot be opened, and a restored database without the vault key has unreadable API keys.
- On a laptop without the key, a development key is used. The page and Check system show "Development key". Never use that on a real server.

## 12.8 Open a backup yourself

You only need this for a real restore, for example after downloading a backup from Google Drive.

1. On the Backups page, click **backup tool** at the bottom. It downloads `anish1989-backup-tool.py`.
2. On a computer with Python 3.12 or newer, run `pip install cryptography`.
3. Run `python anish1989-backup-tool.py decrypt <backup file> <empty folder>`. Business backups ask for the passphrase. Platform backups use the `BACKUP_ENCRYPTION_KEYS` value (set it as an environment variable first).
4. The folder now has `manifest.json` (what is inside, with row counts), `database.dump` and `media/` (uploaded files).
5. A technical person loads `database.dump` into an **empty** PostgreSQL 16 database with `pg_restore --no-owner --no-privileges -d <database> database.dump`.

On the server, `python manage.py open_backup <file> <folder>` does step 3.

Putting a business's backup back into the live platform (replacing its current data) is done by the platform team, not from this page.
