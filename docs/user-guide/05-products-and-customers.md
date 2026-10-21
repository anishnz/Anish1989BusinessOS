# 5. Products and customers

*User guide, chapter 5 · Last updated 22 October 2026*

**Who this is for:** business owners and staff who look after the product list and the customer list.

You find both in your business admin, for example `https://gorkhabutchery.<platform-domain>/admin/`, under **Products** and **Customers**.

## 5.1 Who can do what

| Role (default) | Products | Customers |
|---|---|---|
| Business Owner, System Admin | Everything | Everything |
| Inventory Manager | Everything | – |
| Sales Manager | View | Everything |
| Sales Representative | View | View, add, change |
| Shop Staff | View (no cost price) | View, add, change |
| Operations Manager | View (no cost price) | View |
| Department Manager | View | View, add, change |
| Support Agent | – | View |
| Marketing Manager | – | View, export |

The System Admin can change this on the **Roles** page (chapter 2). The **Products** module or the **CRM** module must also be switched on for the business (chapter 3).

## 5.2 Products

### Add a product

1. Go to **Products → Products → Add product**.
2. Fill in:
   - **Name**, for example *Goat curry cut*
   - **SKU / code** (optional): your own code. Two products cannot have the same code.
   - **Category**, for example *Goat*. Add categories under **Products → Categories**.
   - **Unit**: *Per kg* (sold by weight), *Each* or *Per pack*
   - **Price (NZ$, incl. GST)**: the price customers pay. For products sold by weight, the price per kg.
   - **Cost price** (optional): what it costs you. Only people who can edit products see it.
   - **GST applies**: leave ticked for normal products (15% GST is included in the price).
   - **Min quantity** and **Quantity step**: for example 0.5 and 0.5 means customers order 0.5 kg, 1 kg, 1.5 kg and so on.
   - **Search terms**: other names customers use, separated by commas, for example *khasi ko masu, mutton curry*. This helps staff search, and later helps the WhatsApp AI understand orders.
3. Click **Save**.

### Not available today

Untick **Available to order** (or select products in the list and choose **Mark selected products as not available**). The product stays in the list.

### Archive instead of delete

Products are never deleted, because old orders and sales reports need them. Select products and choose **Archive selected products**. Archived products are hidden. To see them, choose **Status: Archived** on the right. To bring them back, choose **Restore selected archived products**.

## 5.3 Customers

### Add a customer

1. Go to **Customers → Customers → Add customer**.
2. Fill in the **Name** and at least a **Phone** or **Email** if you have them.
   - NZ numbers can be typed any way, for example *021 123 4567*. They are saved as *+64211234567*, the format WhatsApp uses.
   - Numbers from other countries must start with **+** and the country code, for example *+977 984 1234567*.
3. **Tags** (optional): words separated by commas, for example *regular, wholesale, halal*.
4. Click **Save**.

Two customers cannot have the same phone number or email. If you try, the page tells you which customer already has it.

**Notes** are for staff only. Never write card numbers, bank details or passwords in notes.

### Marketing consent

Only tick **Agreed to marketing messages** when the customer has said yes to receiving offers and news. New Zealand law requires consent before you send marketing messages.

Every change is recorded in the **Marketing consent history** at the bottom of the customer page, with the date and who recorded it. You cannot edit or delete this history.

### Finding customers

Use the search box. You can search by name, email, tag, or part of the phone number (for example *021 123*).

### When a customer asks you to remove their data

1. Select the customer in the list.
2. Choose **Remove personal data of selected customers (privacy request)** and click **Go**.
3. Check the list and click **Yes, remove personal data**.

This removes the name, phone, email, address, notes and tags. The record stays as *Removed customer #12*, so past orders and sales totals stay correct. **This cannot be undone.**

To just hide a customer, use **Archive selected customers** instead.

## 5.4 Import and export (CSV)

You can add or update many products or customers at once with a spreadsheet saved as **CSV UTF-8**.

**Tip:** click **Export CSV** first. You get a file with the right columns, which you can edit and import again.

### Product columns

`sku, name, category, unit, price, cost_price, gst_applies, min_quantity, quantity_step, available, search_terms, description, count_stock, warn_at, stock`

- Only **name** and **price** are needed.
- **unit**: kg, each or pack. **gst_applies** and **available**: yes or no.
- **count_stock**: yes or no. **warn_at**: the low-stock amount (empty = no warning). **stock**: the amount you counted; it is saved as a *Counted* change in the stock history (5.5). Leave it empty to keep the stock as it is.
- A row with the same **SKU** as an existing product updates it. Without a SKU, a row updates the product with the same name. New categories are created automatically.

### Customer columns

`name, phone, email, address, tags, preferred_language, marketing_consent, notes`

- Only **name** is needed.
- A row with the same **phone** as an existing customer updates it (or the same email, if there is no phone).
- Only put **yes** in **marketing_consent** if the customer really agreed.

### How to import

1. In the product or customer list, click **Import CSV**.
2. Choose the file and click **Check file only**. The page shows how many rows would be added or updated, or which rows have problems.
3. Fix any problems, then click **Import**.

If any row has a problem, **nothing is saved**, so you never get half a file imported.

### Notes on exported files

- Exports include personal data. Keep the files safe and delete them when you no longer need them. Every export is recorded in the audit log.
- Some cells start with an apostrophe, for example `'+64211234567`. This stops spreadsheet programs from treating the cell as a formula. Leave it there; the import removes it.
- The cost price column is empty if you cannot edit products.

## 5.5 Stock

The system can count the stock of a product: in **kg** for products sold by weight, in packs or items for the others.

### Switch on counting

1. Open the product (**Products → Products**) and tick **Count stock**.
2. Optional: fill in **Warn at**, for example *5* (kg). Below or at this amount the product shows **Low**.
3. Save, then enter the first count (below).

Products without **Count stock** are never counted or blocked.

### Change the stock by hand (Products – Edit)

In the staff app, open **Products**, click **Stock** next to the product, choose why, type the amount and click **Save**. In the admin pages, open the product and click **Adjust stock**.

| Why | What you type | Example |
|---|---|---|
| Received | the amount that came in | 20 kg of goat arrived: *20* |
| Counted | the amount now on the shelf | you counted *12.5* kg |
| Waste | the amount thrown away (note needed) | *1.2* kg out of date |
| Correction | a change, with a minus sign to take off (note needed) | *-2* counted wrong yesterday |

Every change is kept in the **stock history** with who, when and why. It cannot be changed or deleted. Shop Staff can see stock but not change it.

### Orders change the stock by themselves

- When an order is **confirmed**, the ordered amount is taken off.
- When the **real weight** is entered, the difference is taken off or put back (ordered 1 kg, weighed 1.08 kg: another 0.08 kg off).
- When a confirmed order is **cancelled**, its amount is put back.
- Drafts and orders waiting for the customer do not hold stock.

### Not enough stock

- **Customers** (WhatsApp and the website, coming next) cannot order more than the stock.
- **Staff** can still confirm the order. The order shows *Only 1.5 kg of … in stock*, the stock goes **below zero**, and the product shows **Below zero: count again**. Count the product and save a **Counted** change.
- A counted product with less than its smallest amount shows **Out of stock**.

### Low stock on the dashboard

The **Low stock** card on the dashboard lists products that are low, out of stock or below zero. In the staff app, **Products → Only low or out of stock** shows the same list.
