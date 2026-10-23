# Grocery transaction feature schema `grocery_txn_v1`

Source of truth: `backend/app/ml/store_schema.py` (this page is generated from the same facts; the API serves it at `GET /fraud/store-schema`).
Values come from `store_risk.compute`, which saves exactly this dictionary with every order assessment. They describe **what was known when the
order arrived**: no payment outcome, delivery status, refund or analyst verdict is ever an input.

| Feature | Type | Allowed | Missing value | Source | Privacy |
|---|---|---|---|---|---|
| `total_cents` | int | 1 to 100,000,000 | reject | `orders.total_cents` | order value only |
| `max_line_quantity` | int | 0 to 10,000 | reject | largest `order_items.quantity` | basket shape only, no product names |
| `orders_last_hour` | int | 0 to 1,000 | reject | this customer's orders in the hour up to the event | own-account behaviour count |
| `prior_orders` | int | ≥ 0 | reject | this customer's earlier orders | own-account behaviour count |
| `prior_paid_orders` | int | ≥ 0 | reject | this customer's earlier **paid** orders | own-account behaviour count |
| `average_paid_total_cents` | int | ≥ 0 | 0 when no paid orders | mean of earlier paid order totals | aggregate of own history |
| `failed_payments_24h` | int | 0 to 1,000 | reject | failed payment attempts in the 24 h before the event | count only; failure reasons not used |
| `rejected_checkouts_10m` | int | 0 to 1,000 | reject | rejected checkouts in the 10 min before the event | count only |
| `delivery_address_seen_before` | bool | true/false | false for collection or first orders | address matches an earlier order | the address itself is **not** a feature |
| `fulfilment` | category | `delivery`, `collection` | reject | `orders.fulfilment` | none |
| `local_hour` | int | 0 to 23 | reject | creation time in Zambian local time | hour only |
| `payment_method` | category | `card`, `mtn_momo`, `airtel_money`, `cod`, `simulated` | reject | chosen method label | never card data |

Guard (not a model input): `currency` must be `ZMW`. Other currencies are `unsupported_input_schema`, because cent amounts are not comparable.

## What is deliberately excluded

| Excluded | Why |
|---|---|
| Payment outcome, order status, refund status of this order | known only after the event (would leak the future) |
| Analyst outcome, case status | this is the label |
| Name, e-mail, phone, address text | personal data with no need; address reuse is a yes/no |
| Card number, CVV, provider tokens, passwords | never held by the store; must never be a feature |
| IP address, device, country | the store does not collect them (so no geolocation features exist) |
| Customer id | would let a model memorise customers; used only to keep each customer on one side of the split |

## Point-in-time notes
- The training row is the snapshot of the order's **first** assessment (trigger `order_placed`). Later re-assessments (for example after a failed payment) never replace it.
- `prior_paid_orders` and `average_paid_total_cents` count earlier orders that were paid at assessment time.
- Validation: unknown or sensitive field names, wrong types, out-of-range numbers and unknown categories are refused (`unsupported_input_schema` / `invalid_input`). Nothing is coerced, padded or defaulted.

A change to any field, meaning or allowed value needs a new schema version. A model trained on a different version is refused with `schema_incompatible`.
