# Umre Ops — Accounting Integration

This app keeps **Umre operations** in `Umre Booking` and posts accounting using **standard ERPNext accounting documents**.

## What gets posted (safe defaults)

### Receipts (customer payments)
- **Preferred**: `Payment Entry` (Receive) **when** `Umre Booking.customer` is set and `Umre Ops Settings.receivable_account` is configured.
- **Fallback**: `Journal Entry` receipt (Bank/Cash Dr, Income Cr) when Customer/AR is not configured.

Receipts are posted **per payment row** in the `Umre Booking.payments` child table.

### Operational costs (expense recognition)
- Posted as a **single `Journal Entry`** per booking: Expense Dr (hotel/flight/visa/diyanet/commission), Bank/Cash Cr.
- Trigger is **explicit** (API/button/backfill). Nothing posts on every save.

## Idempotency / duplicate prevention

All posting is gated by `Umre Posting Event` using a deterministic **idempotency key**.

- If the same action is retried, the system returns the previously-created document.
- Downstream documents also get:
  - `Payment Entry.umre_booking`, `Payment Entry.umre_posting_key` (Unique)
  - `Journal Entry.umre_booking`, `Journal Entry.umre_posting_key` (Unique)

## Required configuration (minimal)

Create and configure `Umre Ops Settings`:
- **Company**: required
- **Accounts**:
  - `income_account`
  - `receivable_account` (required only if you want Payment Entry receipts)
  - `hotel_expense_account`, `flight_expense_account`, `visa_expense_account`, `diyanet_expense_account`, `commission_expense_account`
- **Cost Centers**:
  - `umre_operasyon_root_cost_center` (fallback)
  - `genel_gider_cost_center`
  - `pazarlama_cost_center`
- **Mode of Payment mapping** (optional but recommended)
  - map legacy `Umre Booking.odeme_turu` values to `Mode of Payment`

Verify setup via API:
- `umre_ops.umre_ops.api.verify_setup_state`

## Posting APIs

### Record a payment row (no accounting)
- `umre_ops.umre_ops.services.payment_service.api_add_payment(docname, amount, ...)`

### Post a specific payment row receipt (idempotent)
- `umre_ops.umre_ops.services.payment_service.api_post_payment_receipt(docname, payment_row_name, paid_account, dry_run=0)`

### Post booking costs (idempotent)
- `umre_ops.umre_ops.api.post_booking_costs(docname, bank_or_cash_account, dry_run=0)`

## Backfill utilities (safe)

### Recalculate booking derived fields
- `umre_ops.umre_ops.backfill.recalculate_all_bookings(limit=0)`

### Backfill receipts for unposted payment rows
- `umre_ops.umre_ops.backfill.post_all_unposted_payments(paid_account, dry_run=1, limit=0)`

## Notes / constraints
- No raw SQL is used for accounting documents.
- No GL table writes are performed directly.
- Posting is **explicit**; `Umre Booking.validate()` only recalculates operational fields and keeps `odenen` in sync with payment rows.

