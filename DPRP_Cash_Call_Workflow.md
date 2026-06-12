# DPRP Cash Call Automation System
## Business Workflow Document

**Prepared for:** Dangote Petroleum Refinery & Petrochemicals FZE
**Audience:** Business Stakeholders & Management
**Date:** 12 June 2026

---

## 1. System Overview

The DPRP Cash Call Automation System is a centralised digital platform that manages how departments request, review, approve, and pay out funds within Dangote Petroleum Refinery & Petrochemicals FZE. It replaces manual, paper-based and email-driven cash call requests with a single, structured workflow where every request follows a clear, controlled path from the moment it is raised to the moment payment is made. Each request carries full financial detail — vendor, invoice, currency, amount, and billing period — and is automatically converted to a common US Dollar equivalent so that management always sees a consistent view of spend.

The system enforces a layered approval chain, ensuring that no funds leave the organisation without the right people signing off in the right order. It checks every request against the requesting department's budget, flags overspending before it happens, and records every single action taken by every person involved. All of this information feeds directly into Power BI dashboards, giving the CFO, CEO, and the board real-time visibility into spending patterns, approval bottlenecks, budget performance, and currency exposure — without anyone having to chase spreadsheets.

---

## 2. The Actors

| Role | Who They Are | What They Can Do |
|------|-------------|-----------------|
| **Originator** | Department staff who initiate funding requests | Create and submit cash call requests, add line items, respond to return-for-revision feedback, resubmit |
| **HOD (Head of Department)** | Departmental head responsible for their unit's spend | Review their department's requests; approve, return for revision, or decline |
| **Finance Reviewer** | Finance Quality Control officer | Check financial accuracy (amounts, currencies, exchange rates, invoices); approve or return |
| **CFO** | Chief Financial Officer | Approve, partially defer selected line items, or decline a request |
| **CEO** | Chief Executive Officer | Provide final approval authority before payment |
| **Treasury** | Treasury / payments team | Process and release payment once the CEO has approved; mark requests as Paid |
| **IT Admin** | System administrator | Manage users, exchange rates, departmental budgets, and overall system settings |

---

## 3. Step-by-Step Workflow

### Standard Cash Call Flow

1. **Originator logs in** and creates a new cash call request, selecting **Standard Cash Call**.
2. The Originator adds between **1 and 10 line items**. For each line item they capture the vendor name, invoice number, optional PO number, category, description, currency (USD, NGN, EUR, GBP, or INR), original amount, and exchange rate. The system **automatically calculates the USD equivalent**. They also record the billing period (start and end), frequency (one-off, monthly, quarterly, or annual), and whether the item is an arrear (and if so, the arrear type).
3. The Originator submits the request. Its status becomes **Pending HOD**.
4. **The HOD reviews the request.**
   - **If the HOD is satisfied**, they approve it. Status becomes **HOD Approved**, and the system runs the automatic **budget check** (see Section 6). The request moves to **Pending Finance QC**.
   - **If the HOD wants changes**, they return it with feedback. Status becomes **HOD Returned**, an email notification is sent to the Originator, who edits and resubmits (returning to step 3).
   - **If the HOD rejects it outright**, they decline it. Status becomes **HOD Declined**, an email notification is sent to the Originator, and the request ends here.
5. **The Finance Reviewer performs financial quality control**, verifying amounts, currencies, exchange rates, and invoice details.
   - **If the figures are accurate**, they approve. Status becomes **Finance QC Approved** and the request moves to **Pending CFO**.
   - **If corrections are needed**, they return it. Status becomes **Finance QC Returned** and it goes back to the Originator for revision.
6. **The CFO reviews the request.**
   - **If the CFO approves**, status becomes **CFO Approved** and the request moves to **Pending CEO**.
   - **If the CFO wishes to defer**, they tick individual line items to push to a future month (a **partial defer**). The deferred items are held; the remaining approved items proceed to the CEO. The request is marked **CFO Deferred** for the deferred portion.
   - **If the CFO declines**, status becomes **CFO Declined** and the request ends here.
7. **The CEO provides final approval.** When approved, status becomes **CEO Approved** and the request moves to **Pending Treasury**.
8. **Treasury processes the payment.** Once funds are released, Treasury marks the request as **Paid** — the final status.

At any point a request may be **Cancelled**, which stops it from progressing further.

### Urgent Cash Call Sub-Flow

For time-critical needs that cannot wait for the standard monthly timeline, the Originator selects **Urgent Cash Call**. In addition to the standard line item details, the Originator must provide:

- **Urgency category**
- **Requested payment date**
- **Finance authoriser name**
- **Urgency reason**

The urgent request then follows the same approval chain (HOD → Finance QC → CFO → CEO → Treasury) but is flagged and prioritised as urgent throughout, allowing approvers to fast-track it while still applying every control, budget check, and audit record that a standard request receives.

---

## 4. Workflow Diagram

```
 ORIGINATOR        HOD            FINANCE QC          CFO              CEO           TREASURY
 ==========     ==========       ==========       ==========       ==========     ==========

 Create &
 submit request
 (Standard or
  Urgent)
     |
     v
 [pending_hod] ---> Review
                      |
              <decision diamond>
              /       |        \
        Returned   Declined   Approved
            |          |          |
   (email) |   (email,END)  [budget check]
   edit &  |                     |
  resubmit |                     v
     ^------                [pending_finance_qc] ---> QC Review
                                                        |
                                                <decision diamond>
                                                  /            \
                                             Returned         Approved
                                                 |               |
                                          back to Originator     v
                                                          [pending_cfo] ---> CFO Review
                                                                               |
                                                                       <decision diamond>
                                                                      /        |         \
                                                                 Declined   Deferred   Approved
                                                                    |       (hold items)   |
                                                                  (END)    approved items   |
                                                                              proceed -------+
                                                                                             v
                                                                                      [pending_ceo] ---> CEO Review
                                                                                                           |
                                                                                                      Approved
                                                                                                           |
                                                                                                           v
                                                                                                    [pending_treasury] ---> Process
                                                                                                                              payment
                                                                                                                                |
                                                                                                                                v
                                                                                                                             [PAID]

 Note: A request may be CANCELLED at any stage, halting the flow.
```

---

## 5. Data Captured at Each Stage

| Stage | Information Recorded |
|-------|---------------------|
| **Submission (Originator)** | Submission type (Standard/Urgent); for urgent: urgency category, requested payment date, finance authoriser name, urgency reason |
| **Line Items (1–10 per request)** | Vendor name, invoice number, PO number (optional), category, description, currency, original amount, exchange rate, USD equivalent (auto-calculated), billing period start/end, frequency, arrear flag, arrear type |
| **HOD Approval** | Approval/return/decline decision, feedback notes, timestamp, actor; budget over-limit flag (if triggered) |
| **Finance QC** | Verification decision (approve/return), notes, timestamp, actor |
| **CFO Decision** | Approve / partial defer (which line items, to which future month) / decline, notes, timestamp, actor |
| **CEO Approval** | Final approval decision, notes, timestamp, actor |
| **Treasury Payment** | Payment processed, marked Paid, timestamp, actor |
| **Throughout** | Full audit trail of every action with timestamp, actor, and notes |

---

## 6. Budget Control

Every department has a **monthly budget allocation** maintained by the IT Admin. When a request is approved by the HOD, the system **automatically totals the USD equivalent** of all its line items and compares it against the department's remaining monthly budget allocation.

- **If the total is within budget**, the request proceeds normally.
- **If the total exceeds the allocation**, the system raises a **budget over-limit flag**. This flag is **visible to all subsequent approvers** (Finance Reviewer, CFO, and CEO), so they can make an informed decision — approving with full awareness of the overspend, deferring line items to a future month, or declining.

This ensures overspending is surfaced early and transparently, rather than being discovered after payment.

---

## 7. Audit & Compliance

The system maintains a complete **audit trail** of the entire lifecycle of every request. Every action — submit, approve, return, decline, defer, and pay — is permanently logged with:

- **Timestamp** — exactly when the action occurred
- **Actor** — who performed it
- **Notes** — the reasoning or feedback attached to the action

**Why it matters:** This gives the organisation a tamper-evident record for internal controls, external audit, and regulatory compliance. It answers, at any time, the questions auditors and management care about most: *Who approved this? When? On what basis? Was budget exceeded? Why was it deferred or declined?* It also creates accountability at every level and provides the data needed to measure how efficiently approvals are flowing through the organisation.

---

## 8. Power BI Connection

All information held in the system — every submission, line item, departmental budget allocation, exchange rate, and audit log entry — flows continuously into **Power BI dashboards**. This turns operational data into management intelligence, giving leadership a live, board-ready view of spending and approval performance without manual reporting effort.

### KPI Reports & Visuals Produced

| Report / Visual | Type | What It Shows |
|----------------|------|--------------|
| **Spend by Department** | Bar chart (monthly) | Total spend per department, month by month |
| **OPEX vs CAPEX Split** | Donut chart | Proportion of operating vs capital spend |
| **Submission Pipeline by Status** | Funnel | How many requests sit at each approval stage |
| **Budget vs Actual Spend** | Gauge / bar per department | Each department's actual spend against its allocation |
| **Urgent vs Standard Ratio** | Comparison | Share of urgent versus standard submissions |
| **Average Approval Cycle Time** | Per-stage metric | How long requests take at each stage of approval |
| **Currency Exposure Breakdown** | USD-equivalent totals by original currency | Exposure across USD, NGN, EUR, GBP, INR |
| **Deferred Items Tracker** | Tracker | What was deferred, to which month, and by whom |
| **Top Vendors by Spend** | Ranking | Largest vendors by total spend |
| **Arrears Analysis** | Analysis | Outstanding arrears by type and volume |

These dashboards allow the CFO and CEO to monitor budget discipline, identify approval bottlenecks, manage currency exposure, track deferred commitments, and present a clear, consolidated spending picture to the board.

---

*End of document.*
