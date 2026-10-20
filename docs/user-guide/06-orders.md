# 6. Orders

*User guide, chapter 6 · Last updated 21 October 2026*

**Who this is for:** counter and kitchen staff (role **Shop Staff**), managers and business owners.

Orders are in your business admin under **Orders → Orders**. Later, orders from WhatsApp will arrive here too, and staff will get a simpler order screen. The rules in this chapter stay the same.

## 6.1 Who can do what

| Role (default) | What they can do with orders |
|---|---|
| Shop Staff | See, add and change orders, move them through the steps, enter weights, mark as paid |
| Operations Manager | Everything with orders, including deleting drafts and exporting |
| Business Owner, System Admin | Everything |
| Department Manager | See, add, change, approve |
| Sales Representative | See and add |
| Sales Manager | See and export |
| Finance Manager, Support Agent | See |

To pick products and customers in an order, a person also needs to **see** products and customers.

## 6.2 Add an order

1. Go to **Orders → Add order**.
2. **Customer**: start typing a name or phone number. Leave it empty for a walk-in customer.
3. **Channel**: how the order came in (counter, phone, WhatsApp, website).
4. **Pickup time** and **Notes** (optional), for example *cut into small pieces*.
5. In **Order lines**, choose each product and the **Ordered amount**:
   - Products sold by weight use kg, and the amount must follow the product's steps, for example 0.5, 1, 1.5 kg.
   - Packs and single items use whole numbers.
6. Click **Save**. The order gets a number, for example **#1001**, and its status is **Draft**.

Prices always come from the product and include GST. The order keeps the price of the moment, so a later price change does not change old orders.

## 6.3 The steps of an order

```
Draft → (Awaiting customer confirmation) → Confirmed → Being prepared
      → (Final price sent → Final price accepted) → Ready for pickup → Completed
```

| Status | Meaning |
|---|---|
| Draft | Being written. Products can be changed. |
| Awaiting customer confirmation | Sent to the customer to check (used by WhatsApp ordering). If they do not confirm, it becomes **Expired**. |
| Confirmed | The customer agreed. Products can no longer be changed. |
| Being prepared | Staff are packing it. Enter the real weights now. |
| Final price sent | The real weight changed the price, and the new price was sent to the customer. |
| Final price accepted | The customer agreed to the new price. |
| Ready for pickup | Packed and waiting. |
| Completed | Picked up. |
| Cancelled by customer / by shop | Stopped. A reason is required. |

To move an order on, open it and click **Status and payment**, choose the next step and click **Change status**. To move several orders at once, select them in the list and choose an action, for example **Confirm selected orders**. If an order cannot move, a message tells you why.

## 6.4 Products sold by weight

A customer orders 1.5 kg of goat, but the pack weighs 1.58 kg.

1. Move the order to **Being prepared**.
2. Open the order. In **Real weight**, type *1.58* next to the goat line, and click **Save**. The total changes.
3. Open **Status and payment**:
   - If the price **changed**, choose **Final price sent** and tell the customer the new price. When they agree, choose **Final price accepted**. If the customer is at the counter, you can do both steps at once.
   - If the price is **the same**, go straight to **Ready for pickup**.

The order cannot be marked ready until every weight is entered, and it cannot skip the customer's agreement when the price changed.

## 6.5 Payment

On **Status and payment**, choose how the customer paid (cash, card, bank transfer or other) and click **Mark as paid**. Only confirmed orders can be marked as paid.

If you give the money back, click **Mark as not paid**. A paid order cannot be cancelled until it is marked as not paid, so refunds are never forgotten.

## 6.6 Changing, cancelling and deleting

- **Products** can only change while the order is a **Draft** or **Awaiting customer confirmation**. If you change products while waiting for the customer, the order goes back to **Draft** and the customer must confirm again.
- **Customer, pickup time and notes** can change until the order is completed or cancelled.
- **Cancel** from **Status and payment**: choose *Cancelled by customer* or *Cancelled by shop* and write the reason.
- **Delete** is only possible for drafts. Other orders are cancelled instead, so the history stays complete.

## 6.7 History and export

- **Status and payment** shows the history of the order: every step, when, who, and any note.
- Every change is also recorded in the audit log.
- **Export CSV** in the order list downloads all orders, one row per product line. Managers can use it for reports and the accountant. The file includes customer names, so keep it safe.

## 6.8 Orders waiting too long (for the person who runs the server)

Orders that wait for the customer's confirmation for more than an hour can be closed as **Expired** with:

```
docker compose exec web python manage.py expire_orders --minutes 60
```

This will run automatically when the WhatsApp ordering step is built.
