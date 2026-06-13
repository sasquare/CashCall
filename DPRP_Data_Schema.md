# DPRP Cash Call System — Data Schema
**Dangote Petroleum Refinery & Petrochemicals FZE**
Tech-stack agnostic. Implement in any language/database.

---

## TABLE 1: USERS

| Field | Type | Required | Notes |
|---|---|---|---|
| id | Integer | Yes | Primary key, auto-increment |
| email | String(255) | Yes | Unique. Used as login identifier |
| display_name | String(255) | Yes | Full name shown in UI |
| role | String(50) | Yes | See Roles enum below |
| department | String(255) | No | Required for originator & hod roles only |
| is_active | Boolean | Yes | Default true. False = deactivated account |
| alternate_email | String(255) | No | Backup email for notifications |
| hashed_password | String(255) | No | bcrypt hash. Only needed if not using SSO |
| created_at | Timestamp | Yes | Auto-set on creation |
| updated_at | Timestamp | Yes | Auto-updated on every change |

**Role values:** `originator` · `hod` · `finance_reviewer` · `cfo` · `ceo` · `treasury` · `it_admin`

---

## TABLE 2: SUBMISSIONS

### Core fields
| Field | Type | Required | Notes |
|---|---|---|---|
| id | Integer | Yes | Primary key |
| submission_id | String(20) | Yes | Human-readable unique ID e.g. SC-2026-0001 |
| created_by | FK → users.id | Yes | The originator who submitted |
| department | String(255) | Yes | Originator's department |
| month | Integer (1–12) | Yes | Budget month |
| month_name | String(10) | Yes | e.g. "Jun-26" |
| year | Integer | Yes | Budget year |
| cost_type | String(10) | Yes | `opex` or `capex` |
| supporting_justification | Text | Yes | Business reason for the request |
| request_type | String(20) | Yes | `standard` or `urgent` |
| status | String(50) | Yes | See Status Flow below |
| budget_over_limit_flag | Boolean | Yes | True if total USD exceeds monthly allocation |
| created_at | Timestamp | Yes | Auto-set on creation |

### Urgent request fields (only when request_type = "urgent")
| Field | Type | Required | Notes |
|---|---|---|---|
| urgency_category | String(100) | No | See Urgency Categories enum |
| urgency_reason | Text | No | Why it cannot wait for standard cycle |
| requested_payment_date | Date | No | When payment must be made |
| finance_authoriser | String(255) | No | Name of Finance officer authorising urgency |

### HOD stage fields
| Field | Type | Required | Notes |
|---|---|---|---|
| hod_decision | String(20) | No | `approved` · `returned` · `declined` |
| hod_comment | Text | No | Feedback to originator on return or decline |
| hod_decided_at | Timestamp | No | When HOD acted |
| hod_decided_by | FK → users.id | No | Which HOD acted |

### Finance QC stage fields
| Field | Type | Required | Notes |
|---|---|---|---|
| finance_qc_status | String(20) | No | `approved` · `returned` |
| finance_qc_comment | Text | No | Finance reviewer notes |
| finance_qc_at | Timestamp | No | When Finance QC acted |
| finance_qc_by | FK → users.id | No | Which Finance reviewer acted |

### CFO stage fields
| Field | Type | Required | Notes |
|---|---|---|---|
| cfo_decision | String(30) | No | `approved` · `deferred` · `declined` |
| cfo_reason | Text | No | CFO's notes or reason |
| cfo_approved_amount | String(20) | No | USD amount approved (if partial) |
| cfo_decided_at | Timestamp | No | When CFO acted |
| cfo_decided_by | FK → users.id | No | Which CFO acted |
| cfo_post_deferral | Boolean | No | True if submission had deferred items and remaining items were forwarded |
| cfo_post_deferral_reason | Text | No | Reason for partial deferral |
| cfo_post_defer_to_month | Integer | No | Month deferred items are pushed to |

### CEO stage fields
| Field | Type | Required | Notes |
|---|---|---|---|
| ceo_decision | String(20) | No | `approved` · `declined` |
| ceo_reason | Text | No | CEO notes |
| ceo_decided_at | Timestamp | No | When CEO acted |
| ceo_decided_by | FK → users.id | No | Which CEO acted |

### Treasury stage fields
| Field | Type | Required | Notes |
|---|---|---|---|
| treasury_payment_status | String(30) | No | See Treasury Status enum |
| treasury_comment | Text | No | Treasury payment notes |
| treasury_updated_at | Timestamp | No | When Treasury last updated |
| treasury_updated_by | FK → users.id | No | Which Treasury officer acted |

---

## TABLE 3: LINE ITEMS
*(1 submission can have 1–10 line items)*

| Field | Type | Required | Notes |
|---|---|---|---|
| id | Integer | Yes | Primary key |
| submission_id | FK → submissions.id | Yes | Parent submission |
| vendor_name | String(255) | Yes | Name of vendor/supplier |
| invoice_no | String(100) | Yes | Invoice reference number |
| po_number | String(100) | No | Purchase order number |
| description | Text | Yes | What the payment is for |
| items_products | Text | No | Specific items or products |
| category | String(100) | Yes | See Categories enum |
| account_code | String(50) | Yes | Internal account/GL code |
| billing_period_start | Date | Yes | Start of the billing period |
| billing_period_end | Date | Yes | End of the billing period |
| frequency | String(20) | Yes | `one_off` · `monthly` · `quarterly` · `annual` |
| currency | String(10) | Yes | `USD` · `NGN` · `EUR` · `GBP` · `INR` |
| original_amount | Decimal(18,2) | Yes | Amount in original currency |
| exchange_rate_used | Decimal(18,8) | Yes | Rate at time of submission (immutable) |
| equivalent_usd | Decimal(18,2) | Yes | = original_amount / exchange_rate_used (stamped at submission, immutable) |
| approved_usd | Decimal(18,2) | No | Set at CEO approval stage |
| is_arrear | Boolean | Yes | True if this is a prior-period arrear |
| arrear_type | String(50) | No | See Arrear Types enum (required if is_arrear = true) |
| cfo_deferred | Boolean | Yes | Default false. True if CFO deferred this specific item |
| cfo_defer_to_month | Integer | No | Month this item is deferred to (1–12) |
| payment_tracking_code | String(100) | No | Internal payment tracking reference |
| status_remarks | Text | No | Any remarks on item status |

---

## TABLE 4: EXCHANGE RATES

| Field | Type | Required | Notes |
|---|---|---|---|
| id | Integer | Yes | Primary key |
| currency | String(10) | Yes | `USD` · `NGN` · `EUR` · `GBP` · `INR` |
| rate_to_usd | Decimal(18,8) | Yes | Units of this currency per 1 USD (USD = 1.0) |
| effective_from | Date | Yes | Date this rate becomes active |
| valid_until | Date | No | Null = currently active. Set when replaced by a newer rate |
| source | Text | No | e.g. "CBN", "Manual entry" |
| updated_by | FK → users.id | No | Who entered the rate |
| created_at | Timestamp | Yes | Auto-set |

**Active rate logic:** For a given currency, the active rate is the row where `effective_from <= today` AND `valid_until IS NULL`. When a new rate is added, set `valid_until = new_effective_from - 1 day` on the previous active row.

---

## TABLE 5: DEPARTMENT BUDGETS

*(One row per department per month/year)*

| Field | Type | Required | Notes |
|---|---|---|---|
| id | Integer | Yes | Primary key |
| department | String(255) | Yes | Department name (unique per month/year) |
| month | Integer (1–12) | Yes | Budget month |
| year | Integer | Yes | Budget year |
| monthly_allocation_usd | Decimal(18,2) | Yes | Monthly budget cap in USD |
| monthly_allocation_ngn | Decimal(18,2) | No | Monthly budget cap in NGN |
| annual_allocation_usd | Decimal(18,2) | No | Annual budget in USD |
| approved_mtd | Decimal(18,2) | Yes | Running total: USD approved so far this month |
| paid_mtd | Decimal(18,2) | Yes | Running total: USD paid so far this month |
| approved_ytd | Decimal(18,2) | Yes | Running total: USD approved year-to-date |
| deferred_approved | Decimal(18,2) | Yes | Pre-reserved amount from deferred items incoming this month |
| created_at | Timestamp | Yes | Auto-set |
| updated_at | Timestamp | Yes | Auto-updated |

**Unique constraint:** (department + month + year) must be unique.

---

## TABLE 6: SUBMISSION AUDIT LOG

*(One row per action taken on a submission)*

| Field | Type | Required | Notes |
|---|---|---|---|
| id | Integer | Yes | Primary key |
| submission_id | FK → submissions.id | Yes | Which submission |
| action | String(100) | Yes | e.g. "hod_review", "cfo_review", "payment_update" |
| outcome | String(100) | Yes | e.g. "approved", "returned", "declined", "paid" |
| performed_by | FK → users.id | Yes | Who performed the action |
| performed_at | Timestamp | Yes | When it happened |
| amount_usd | Decimal(18,2) | No | USD amount at time of action |
| notes | Text | No | Free-text notes added by the actor |

---

## TABLE 7: SYSTEM AUDIT LOG

*(System-level changes: rate updates, budget changes, user management)*

| Field | Type | Required | Notes |
|---|---|---|---|
| id | Integer | Yes | Primary key |
| event_type | String(100) | Yes | e.g. "exchange_rate_updated", "budget_updated", "user_created" |
| performed_by | FK → users.id | Yes | Who made the change |
| performed_at | Timestamp | Yes | When it happened |
| old_value | Text | No | Previous value before change |
| new_value | Text | No | New value after change |
| notes | Text | No | Description of what changed |

---

## ENUMS & ALLOWED VALUES

### Submission Status Flow
```
pending_hod
  ├─ hod_returned          (HOD sends back to originator for revision)
  ├─ hod_declined          (HOD permanently rejects)
  └─ hod_approved ──► pending_finance_qc
                           ├─ finance_qc_returned   (Finance sends back)
                           └─ finance_qc_approved ──► pending_cfo
                                                       ├─ cfo_declined
                                                       ├─ cfo_deferred   (some/all line items deferred)
                                                       └─ cfo_approved ──► pending_ceo
                                                                           ├─ ceo_declined
                                                                           └─ ceo_approved ──► pending_treasury
                                                                                               └─ paid
```
Also valid: `cancelled`

### Treasury Payment Status values
`paid` · `not_yet_paid` · `doc_not_in_treasury` · `returned_to_payable` · `duplicated` · `audit_hold` · `invoice_not_received` · `account_payable` · `other`

### Cash Call Categories
- Catalyst & Chemicals
- Crude Shipping / Marine
- Maintenance Cost
- Admin & Insurance
- Communication / Internet

### Urgency Categories (urgent requests only)
- Plant Shutdown Risk
- Safety & Regulatory Compliance
- Contractual Obligation / Penalty Avoidance
- Supplier Credit Risk
- Critical Spare Parts
- Utility / Feedstock Continuity
- Other

### Arrear Types
`prior_period` · `bluestar_shipping` · `ge_international` · `rfcc_shutdown` · `expansion_project`

### Payment Frequencies
`one_off` · `monthly` · `quarterly` · `annual`

### Currencies
`USD` · `NGN` · `EUR` · `GBP` · `INR`

### Cost Types
`opex` · `capex`

---

## KEY BUSINESS RULES

1. **USD Conversion:** `equivalent_usd = original_amount / exchange_rate_used`. Rate is stamped at submission time and never changes for that line item.
2. **Budget Check:** Triggered after HOD approves. Compare sum of all `equivalent_usd` on the submission against `monthly_allocation_usd` for that department/month/year. If exceeded, set `budget_over_limit_flag = true` on the submission (warn only — does not block flow).
3. **Originator Department Lock:** Standard submissions lock the department to the originator's own department. Finance Reviewer role can submit urgent requests on behalf of any department.
4. **CFO Partial Defer:** CFO can mark individual line items (`cfo_deferred = true`) and send remaining items forward to CEO. Deferred items are held until their target month.
5. **HOD Return:** HOD can return a submission to the originator with comments. Originator edits and resubmits (status resets to `pending_hod`).
6. **Submission ID format:** `SC-YYYY-NNNN` e.g. `SC-2026-0042` — sequential per year.
7. **Exchange Rate Upsert:** When a new rate is added for a currency, the previous active rate's `valid_until` is set to `new_effective_from - 1 day`. Only one rate per currency should have `valid_until = null` at any time.
8. **Max Line Items:** 10 per submission.
9. **Audit Trail:** Every approval, return, decline, defer, and payment action must write a row to the Submission Audit Log.
