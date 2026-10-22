# 7. WhatsApp and the inbox

*User guide, chapter 7 · Last updated 22 October 2026*

**Who this is for:** staff who answer customers (section 7.1–7.4), the IT Admin who connects WhatsApp (section 7.5), and the person who runs the server (sections 7.6–7.7).

Each business connects **its own** WhatsApp Business number through Meta's official WhatsApp Business Platform (Cloud API). Messages from customers arrive in the business's **Inbox**. Staff answer from there.

WhatsApp's rules and prices change. Check Meta's current documentation before going live: [developers.facebook.com/docs/whatsapp](https://developers.facebook.com/docs/whatsapp).

## 7.1 The inbox

Open **Inbox → Conversations** in your business admin.

- Each customer has one conversation. New messages put it at the top, with the number of **unread** messages.
- A customer who writes for the first time is added to **Customers** automatically, with their WhatsApp name and number. If the number already belongs to a customer, the message is linked to that customer.
- Use the filters on the right for **Open / Closed** and **Assigned to**.

Who can do what (default roles):

| Role | Inbox |
|---|---|
| Shop Staff, Sales Representative | Read and reply, close and reopen |
| Department Manager, Sales Manager, Business Owner, System Admin | Also assign conversations to a staff member |
| Support Agent, Operations Manager, Marketing Manager | Read only |

## 7.2 Reply to a customer

1. Click the customer's name to open the conversation. It is marked as read.
2. Type in **Reply** and click **Send reply**.
3. Under each message you see its progress: **Sent → Delivered → Read**, or **Failed** with the reason.

**The 24-hour rule:** WhatsApp lets a business reply freely for **24 hours after the customer's last message**. After that, the reply box is replaced by a notice, and you can only send an **approved template** (see 7.3).

## 7.3 Templates

Templates are messages you create and get approved in Meta first, for example *order_ready*: "Hi {{1}}, your order {{2}} is ready for pickup."

The order messages (please confirm, final price, ready…) use their own templates and are sent by themselves; see chapter 17. The AI assistant can answer customers too; see chapter 18.

To send one, open **Send an approved template** in the conversation:

- **Template name** and **language** exactly as approved in Meta.
- **Values** for {{1}}, {{2}}… separated by `|`, for example `Sita | #1001`.
- **Category**: *Utility* for order updates, *Marketing* for offers.

**Marketing templates are only sent to customers who agreed to marketing messages** (chapter 5). If a customer writes **STOP**, they are opted out automatically, and this is recorded in their consent history.

## 7.4 Assign and close

- **Assigned to**: choose a staff member and click **Assign**, so everyone knows who is answering.
- **Close conversation** when it is finished. If the customer writes again, it opens again automatically.

When a customer's personal data is removed (chapter 5), their messages are deleted too.

## 7.5 Connect WhatsApp (IT Admin)

You need a Meta Business account and a phone number that is not already used in the WhatsApp app.

**At Meta** ([developers.facebook.com](https://developers.facebook.com)):
1. **My Apps → Create app**, choose the **Business** type, and add the **WhatsApp** product.
2. In **WhatsApp → API Setup**, note the **Phone number ID** and the **WhatsApp Business account ID**. Meta gives you a free test number to start with.
3. Create a **permanent access token**: Meta Business Settings → **System users** → add a system user → **Generate token** for your app with the permissions *whatsapp_business_messaging* and *whatsapp_business_management*. (The token on the API Setup page only works for 24 hours.)
4. In **App settings → Basic**, click **Show** next to **App secret** and copy it.

**In the platform:**
5. Open **Integrations** (chapter 4), click **WhatsApp Business (Cloud API)**, and fill in:
   - **Access token** and **App secret**
   - **Phone number ID** (and the business account ID)
   - Leave **Graph API version** as it is (v25.0) and leave **Webhook verify token** empty. The platform creates one.
6. Click **Save**, then **Test connection**.
7. The Integrations page now shows a **Meta webhook callback URL** and a **Verify token** under the connection.

**Back at Meta:**
8. In **WhatsApp → Configuration → Webhook**, click **Edit**, paste the **callback URL** and the **verify token**, and click **Verify and save**.
9. Under **Webhook fields**, **subscribe** to **messages**.
10. Send a WhatsApp message to your business number. It appears in the Inbox within a few seconds.

The callback URL must be a public **https** address. A laptop address such as `gorkhabutchery.localhost` cannot be reached by Meta. Use section 7.6 or 7.7 instead.

## 7.6 Test on a laptop without Meta

This sends a pretend customer message through the real webhook, including the security checks. It needs a WhatsApp connection on the Integrations page, but test values are fine.

```
docker compose exec web python manage.py whatsapp_simulate --schema gorkhabutchery --from "021 123 4567" --name "Sita" --text "1 kg goat please"
```

Replies sent from the Inbox will show **Failed** with test values, because Meta does not accept them.

## 7.7 Real WhatsApp test from a laptop (optional)

Meta needs a public https address. A free Cloudflare quick tunnel gives your laptop one for as long as it runs.

1. Install **cloudflared**: [developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
2. Run `cloudflared tunnel --url http://localhost:8000` and copy the address it prints, for example `https://blue-sky-1234.trycloudflare.com`.
3. In `.env`, add the address (without https://) to `DJANGO_ALLOWED_HOSTS`, then run `start.cmd` again.
4. As Super Admin, open the business (**Tenants → Gorkha Butchery**) and add a **Domain** row with the same address (not primary). Save.
5. Use `https://<that address>/webhooks/whatsapp/` as the callback URL in step 8 above.

The address changes every time you start the tunnel. Task 1.12 (subdomains and domains) will make this simpler, and a real server will have a fixed address.
