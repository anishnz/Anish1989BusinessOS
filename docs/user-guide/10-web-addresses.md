# 10. Web addresses

*User guide, chapter 10 · Last updated 23 October 2026*

**Who this is for:** the platform Super Admin, and business owners who want to know their address.

Every business has its own web address on the platform, for example `gorkha.<platform address>`. Staff open the admin, the staff app (`/app/`) and, later, the business website on this address.

## 10.1 The main address

A business can have up to **5 addresses**. One of them is the **main address**:

- People use the main address, and emails (for example invitations) link to it.
- If someone opens another address of the business, they are sent to the main address automatically. Old links, posters and QR codes keep working.
- Webhooks (for example WhatsApp), the API and health checks work on **every** address and are not sent anywhere. So the WhatsApp connection keeps working after the main address changes.

Business owners can see their addresses in the licence information (`/api/tenant/licence/`, shown in the app later). In this step, only the Super Admin can change them.

## 10.2 Choose the address when you create a business (Super Admin)

On **Tenants → Add tenant**, fill in **Web address name**, for example `gorkha`. The business opens at `gorkha.<platform address>`.

Leave it empty to use the business id with hyphens, for example the id `joes_catering` gives `joes-catering.<platform address>`.

## 10.3 Add, change or remove an address (Super Admin)

1. Open the platform admin, go to **Tenants** and click the business.
2. Click **Web addresses** at the top right.
3. You see every address of the business. The main address is marked **Main address**.

| To do this | Do this |
|---|---|
| Add an address | Type a name under **Add a web address**, tick **Make it the main address** if you want, and click **Add address** |
| Change the main address | Click **Make main address** next to another address |
| Remove an address | Click **Remove** next to it. The main address cannot be removed: make another address the main one first |

Rules for names:
- 3 to 63 characters: lowercase letters, numbers and hyphens, for example `gorkha-butchery`
- they cannot start or end with a hyphen, or be only numbers
- names used by the platform are not allowed, for example `www`, `admin`, `api`, `app`, `mail`, `support` and `webhooks`
- each address can belong to only one business

**Before you remove an address**, check that nothing still uses it. If the WhatsApp webhook in Meta uses the old address, change it there first (chapter 7). Links and QR codes with a removed address stop working.

**After you change the main address**, people who are signed in must sign in again on the new address. Signing in is kept separate for each address, for security.

Every change is written to the platform audit log and to the business's own audit log, as "platform administrator" with your email.

The **Tenants** list shows each business's main address. Click it to open the business site.

## 10.4 Someone opens an address that does not exist

They see a page that says **No business at this address**. Nothing about other businesses is shown.

## 10.5 On a laptop and on a real server

- **On a laptop**, the platform address is `localhost`. Business addresses look like `http://gorkha.localhost:8000/`. Chrome, Edge and Firefox open them without any setup.
- **On a real server**, the platform address is your domain, for example `example.co.nz`, and businesses open at `https://gorkha.example.co.nz/`. The technical steps (DNS records, HTTPS certificate and moving existing businesses) are in the developer setup guide, section "Web addresses (task 1.12)".

A business can also use its own domain, for example `gorkhabutchery.co.nz`: its System Admin or IT Admin adds it on **Web addresses** (chapter 21). The Super Admin sees each business's own domains at the bottom of the business's Web addresses page and can remove them.
