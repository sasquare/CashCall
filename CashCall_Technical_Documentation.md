# CashCall — Technical Documentation
### Dangote Petroleum Refinery (DPRP) Cash Call Approval System

**Version:** 1.0 | **Prepared for:** Business Stakeholders & Development Team

---

## 1. Executive Summary

**What it does.** CashCall is a web application that replaces the paper/email/Excel process of requesting, reviewing, and approving company spending ("cash calls") with a single online system. A department raises a request for funds (e.g. a vendor invoice, maintenance cost, or recurring bill), and the system routes it automatically through a chain of approvers until the money is paid.

**The business problem it solves.** Before this system, cash call requests moved between departments via email and spreadsheets, which caused:
- No single source of truth for what had been requested, approved, or paid.
- No visibility into how much of the monthly budget (by spending category) had been used.
- No audit trail of who approved what, and when.
- Slow, manual bottlenecks — especially for urgent payments.

CashCall solves this by giving every request a unique ID, a visible status, a budget check against the live company budget, and a permanent record of every decision made against it.

**Intended users.**

| Role | Who they are | What they do |
|---|---|---|
| Originator | Department staff | Raise cash call requests |
| HOD | Head of Department | First-line approval for their department's requests |
| Finance Reviewer | Finance team | Quality-checks figures and documentation |
| CFO | Chief Financial Officer | Approves against budget, or defers to a later month |
| CEO | Chief Executive Officer | Final approval authority |
| Treasury | Treasury/Payments team | Executes payment and marks items paid |
| IT Admin | System administrator | Manages users, budgets, and system settings |

---

## 2. Core Features & Capabilities

**Roles & permissions.** Every user has exactly one role, and the system only shows each person the menus, queues, and actions relevant to that role (e.g. an Originator cannot approve their own request).

**Approval workflow — per line item, not per submission.** A single request ("submission") can contain up to 10 individual expense lines. Each line item now moves through the approval chain **independently**:

```
Originator → HOD → Finance QC → CFO → CEO → Treasury → Paid
```

At each stage, the approver can select any combination of items on screen and Approve, Reject, or (at CFO stage only) Defer them to a future month — all in one action. Approved items move on immediately; rejected items stop and return to the requester with a reason; the rest continue waiting. This means one submission can show some items "Paid" while others are still "Pending CFO" or were "Rejected" — the submission's overall status is simply a summary ("Mixed") of where its items currently sit.

**Batch upload & bulk import.** Instead of typing each line item, an Originator can upload an Excel spreadsheet to populate multiple line items in one submission, or upload multiple submissions at once for large volumes of requests.

**Notifications.** Email alerts are sent automatically at key events (e.g. when HOD rejects an item), using a plain SMTP connection — no notification is lost even if email isn't configured, it is simply skipped and logged.

**Reporting & dashboards.** Each role has a dashboard showing what is waiting for their action. A dedicated Reports page (Admin) and a Treasury KPI dashboard show spend by category, by department, amounts paid vs. pending, and budget utilisation, filterable by month and year.

**Budget control.** The company allocates a monthly budget per spending category (e.g. "Maintenance Cost", "Catalyst & Chemicals"). Every approval checks against the live remaining budget for that category and month, and updates it immediately — so nobody can approve spending the company hasn't budgeted for without visibility.

**Security.** Passwords are never stored in plain text (hashed with bcrypt). Login can use Microsoft Azure AD Single Sign-On (SSO), so staff log in with their existing company Microsoft account rather than a separate password. Session cookies are signed and tamper-proof.

**Audit trail.** Every decision — approval, rejection, query, deferral, or payment — is written to a permanent log with who made it, when, on which specific line item, and any comments. This is the record used to answer "who approved this and why."

**Integrations.** Azure AD (login), SMTP email server (notifications), and Power BI (reporting — see Section 7).

---

## 3. Technology Stack

| Layer | Technology | Why it was chosen | What it does |
|---|---|---|---|
| Programming language | **Python** | Widely used, readable, huge ecosystem for business web apps | Runs all the application logic |
| Backend framework | **FastAPI** | Modern, fast, has built-in data validation, easy to secure | Receives every request from a user's browser, decides what should happen, and sends back a response |
| Page rendering | **Jinja2 templates** | Ships HTML pages directly from the server — no separate build step or app to maintain | Turns data (e.g. "your submission list") into the actual web pages users see |
| Frontend styling | **Tailwind CSS (CDN)** + vanilla JavaScript | No build tooling required; any developer can edit a page and see the result immediately | Makes pages look professional and adds small interactive behaviours (e.g. "select all" checkboxes) |
| Database (dev/small deployments) | **SQLite** | Zero setup — it's just a file | Stores all data on Render's free tier by default |
| Database (production-recommended) | **PostgreSQL** | Durable, safe for concurrent users, survives server restarts | Recommended once the system is used by real staff day-to-day |
| Database toolkit | **SQLAlchemy** + **Alembic** | Industry standard for Python; Alembic tracks database changes like version control tracks code | Lets the app talk to the database safely, and lets developers evolve the database structure over time without losing data |
| Authentication | **Microsoft Azure AD (via MSAL)**, with a password fallback for local development | Staff already have Microsoft logins — no new password to remember | Confirms who a user is before letting them into the app |
| Data validation | **Pydantic** | Rejects bad or incomplete data before it reaches the database | Checks every submitted form (amounts, dates, currencies) is valid |
| File handling | **openpyxl** | Reads/writes native Excel `.xlsx` files | Powers batch upload and bulk import of line items |
| Hosting platform | **Render** | Simple, affordable, deploys directly from GitHub | Runs the live application on the internet |
| Packaging | **Docker** (multi-stage build) | Makes the app run identically anywhere | Bundles the app and its dependencies into one deployable unit |
| Third-party services | SMTP provider (e.g. Office 365, SendGrid), Power BI | Email delivery, executive reporting | Notifications and analytics on top of the app's data |
| Development tools | Git/GitHub, Alembic migrations, `.env` configuration files | Standard, well-understood tooling | Version control and safe configuration management |

---

## 4. System Architecture

**In plain English:** a user's browser sends a request to the CashCall server. The server checks who the user is, decides what they're allowed to do, reads or writes data in the database, and sends back a finished web page.

```
┌──────────┐      HTTPS       ┌───────────────┐     SQL      ┌──────────────┐
│  Browser │ ───────────────► │   FastAPI     │ ───────────► │   Database   │
│ (user)   │ ◄─────────────── │  (app server) │ ◄─────────── │ (SQLite/PG)  │
└──────────┘   HTML page      └───────┬───────┘   Data rows  └──────────────┘
                                       │
                          ┌────────────┼─────────────┐
                          ▼            ▼              ▼
                    Azure AD SSO   SMTP Email    Excel import/export
```

**Authentication flow**
1. User clicks "Sign in" → redirected to Microsoft Azure AD (or, in development, a simple email/password form).
2. Azure AD confirms identity and sends the user back to CashCall with a secure token.
3. CashCall creates a signed session cookie in the browser. Every later request is checked against this cookie — no password is stored or re-sent.

**File upload flow (batch/bulk Excel import)**
1. User selects an `.xlsx` file and uploads it.
2. The server reads the file in memory (no file is saved to disk), validates every row (amounts, categories, dates).
3. Valid rows become line items on a new submission; invalid rows are reported back to the user with the exact error, before anything is saved.

**Approval workflow (step by step)**
1. Originator submits a request → each line item starts at status `pending_hod`.
2. HOD opens their queue, selects items, approves/rejects → approved items move to `pending_finance_qc`.
3. Finance QC checks documentation → approves, queries (sends back for clarification without losing the item), or rejects.
4. CFO checks against the live category budget → approves, rejects, or defers to a future month (which also moves the budget reservation to that month).
5. CEO gives final sign-off.
6. Treasury pays and marks the item `paid`, which updates the "Paid MTD" (month-to-date) figure for that budget category.
7. Every single step above writes one row to the audit log.

**Notification process:** at key transitions (currently: HOD rejection), the system attempts to send an email via SMTP. If SMTP is not configured, the action still completes and is logged — the email is simply skipped, so the workflow is never blocked by a missing notification setting.

---

## 5. Deployment Guide

### Prerequisites
- A computer with **Python 3.11+** installed (or Docker, as an alternative).
- Git installed, and access to the GitHub repository.
- A Render.com account (or any host that runs Docker/Python).
- (Optional but recommended for production) An Azure AD App Registration and an SMTP mailbox.

### Environment variables

| Variable | Purpose | Required? |
|---|---|---|
| `SECRET_KEY` | Signs session cookies — must be a long random string in production | Yes |
| `DATABASE_URL` | Where data is stored (`sqlite:///./cashcall.db` for dev, or a `postgresql://…` URL for production) | Yes |
| `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_REDIRECT_URI` | Enables Microsoft SSO login | Only if using SSO |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Enables email notifications | Only if using email |
| `SEED_DB` | If `true`, loads demo data on startup — **must be `false` in production** to avoid wiping real data on redeploy | Recommended `false` in production |

### Running locally
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head                # creates/updates the database
python scripts/seed.py              # optional: loads demo users & data
uvicorn app.main:app --reload       # starts the app at http://localhost:8000
```

### Building for production
The included `Dockerfile` builds a production-ready image in two stages (install dependencies, then copy into a slim runtime image) and runs as a non-root user for security.
```bash
docker build -t cashcall .
docker run -p 8000:8000 --env-file .env cashcall
```

### Deploying to Render
1. Push the code to GitHub (already the case for this project).
2. In Render, create a **New Web Service**, connect the GitHub repository, and choose "Docker" as the environment (Render will detect the `Dockerfile` automatically).
3. Add all environment variables from the table above under **Environment**.
4. **Important:** attach a Render **persistent disk** if using SQLite, or (recommended) provision a **Render PostgreSQL** database and point `DATABASE_URL` at it — otherwise all data is lost on every redeploy, because Render's default filesystem is temporary.
5. Deploy. Render will build the Docker image and start the service automatically on every future push to the connected branch.
6. Run `alembic upgrade head` once (via Render's Shell tab, or as a one-off job) to set up the database tables.

### Connecting a domain
In Render, go to the service's **Settings → Custom Domain**, add the domain, and create the CNAME/A record Render provides at your domain registrar (e.g. GoDaddy, Namecheap). Render issues a free SSL certificate automatically once the DNS record is verified.

### Common deployment issues

| Symptom | Cause | Fix |
|---|---|---|
| Data disappears after a redeploy | Using SQLite on Render's temporary disk | Attach a persistent disk, or switch to PostgreSQL |
| Login fails immediately | Azure AD redirect URI mismatch | Ensure `AZURE_REDIRECT_URI` exactly matches what's registered in Azure AD |
| Emails never arrive | SMTP not configured, or blocked outbound port | Verify SMTP credentials; some hosts block port 25 — use 587 with STARTTLS |
| "relation does not exist" errors | Database migrations not run | Run `alembic upgrade head` after every deploy that changes the database |
| App resets to demo data on every deploy | `SEED_DB=true` in production | Set `SEED_DB=false` once real data exists |

---

## 6. Monthly Alert Configuration

**Current state:** CashCall does not yet include a built-in scheduler. This section describes how to add a reliable "24th of every month" alert (e.g. a budget close-out reminder or unpaid-items summary).

**How a scheduler would work.** A scheduled job is simply code that runs automatically at a set time rather than in response to a user click — e.g. "check for unpaid approved items and email Treasury a summary."

**Recommended options, in order of simplicity:**

1. **Render Cron Job (recommended).** Render can run a script on a schedule independently of the main web app — no code changes to the main app needed. Create a small script (e.g. `scripts/monthly_alert.py`) that queries the database and calls the existing `email_service.send_email()` function, then in Render create a **New Cron Job** pointing at that script with schedule `0 8 24 * *` (8:00 AM on the 24th of every month, in UTC).
2. **In-app scheduler (APScheduler).** Add the `APScheduler` library to `requirements.txt` and register a job inside `app/main.py` at startup. Simpler to keep in one codebase, but only reliable if the web service never sleeps (Render's free tier can spin down when idle, which would skip the job).
3. **External scheduler (e.g. GitHub Actions scheduled workflow, or a third-party cron service like cron-job.org).** Calls a protected API endpoint in CashCall on schedule. Good if you want scheduling decoupled entirely from hosting.

**Where it is configured:** the schedule itself lives in the Render Cron Job dashboard (option 1) or in the `CronTrigger` line of the scheduler code (option 2) — not hardcoded elsewhere.

**Changing the schedule:** edit the cron expression (`minute hour day month weekday`). For example, `0 8 24 * *` → 8 AM on the 24th; `0 8 1,15 * *` → twice a month.

**Best practices for reliability:**
- Always run scheduled jobs in UTC and document the intended local time, to avoid daylight-saving confusion.
- Make the job safe to run twice (e.g. it should not send duplicate alerts if accidentally triggered twice in a day).
- Log every run (success/failure) so a missed alert is noticeable, not silent.
- Avoid the in-app scheduler option on any hosting plan that can "sleep" the app when idle.

---

## 7. Power BI Integration

CashCall does not currently expose a dedicated reporting API — the recommended and simplest integration is a **direct database connection**, since all approval, budget, and audit data already lives in one structured database.

**What data can be consumed:** submissions, individual line items and their statuses, category budgets and monthly utilisation, and the full audit log — everything visible in the app's own Reports and Dashboard pages, plus historical detail not shown on screen.

**Recommended architecture**
```
CashCall (PostgreSQL) ──► Power BI Desktop / Power BI Service ──► Published report
        (read-only DB user)      (Import or DirectQuery mode)
```
1. Migrate production to **PostgreSQL** (Power BI's SQLite support is limited/unofficial; PostgreSQL has a first-class Power BI connector).
2. Create a **read-only database user** dedicated to Power BI (never connect reporting tools with the app's own credentials).
3. In Power BI Desktop: **Get Data → PostgreSQL database**, enter the host/port and read-only credentials.
4. Choose **Import** mode for scheduled refreshes (e.g. daily) or **DirectQuery** for near-real-time dashboards, at the cost of query performance.

**Refresh options:** Power BI Service supports scheduled refresh (e.g. every morning) via the on-premises data gateway if the database isn't publicly reachable, or directly if Render's PostgreSQL allows external connections with SSL.

**Security considerations**
- Use a read-only, least-privilege database role — Power BI should never be able to modify data.
- Restrict database network access to known IP ranges (Render PostgreSQL supports connection restrictions).
- Always connect over SSL (`sslmode=require`).
- Do not expose raw salary, personal, or credential data in any table Power BI can read.

**Example reporting scenarios**
- Monthly budget utilisation by category vs. allocation, refreshed daily for CFO review.
- Approval cycle-time dashboard (average days spent at each stage) to identify bottlenecks.
- Department-level spend trends over the year for the Executive team.
- Rejected/deferred items tracker for Finance follow-up.

---

## 8. Future Enhancements

| Enhancement | Business value |
|---|---|
| Mobile application | Approvers can act on requests from anywhere, reducing delays |
| AI-powered approval suggestions | Flags unusual amounts or vendors for extra scrutiny automatically |
| Predictive analytics | Forecasts category overspend before month-end |
| SMS / WhatsApp notifications | Faster response from approvers than email alone |
| OCR & document scanning | Auto-extract invoice data instead of manual entry |
| ERP integration (SAP, Oracle, MS Dynamics) | Removes duplicate data entry between CashCall and finance systems |
| Workflow automation rules | E.g. auto-approve below a threshold amount |
| Advanced dashboards | Trend lines, anomaly detection, exportable executive packs |
| Multi-company support | One deployment serving multiple business units/subsidiaries |
| Public API ecosystem | Lets other internal tools read/write cash call data securely |
| Cloud scalability (auto-scaling, managed Postgres) | Supports significant growth in users/volume without redesign |
| Role-based analytics | Each role sees KPIs tailored to their responsibilities |
| Machine-learning insights | Learns typical approval patterns to highlight outliers |

---

## 9. Developer Handover

**How the application is structured**
- `app/main.py` — application entry point; wires together all routers and middleware.
- `app/routers/` — one file per role/area (`hod.py`, `finance_qc.py`, `cfo.py`, `ceo.py`, `treasury.py`, `submissions.py`, `admin.py`, `auth.py`). Each file defines the URL endpoints for that role.
- `app/models/` — the database tables, defined as Python classes (SQLAlchemy ORM): `submission.py`, `line_item.py`, `audit_log.py`, `category_budget.py`, `user.py`.
- `app/services/` — the business logic shared across routers (e.g. `submission_service.py` handles budget reservation and status rollup; `email_service.py` handles notifications; `batch_import_service.py` handles Excel parsing).
- `app/templates/` — one folder per role, containing the HTML pages users see.
- `alembic/versions/` — the history of every database structure change, in order. Never edit an old migration file; always add a new one.
- `scripts/seed.py` — creates demo users and sample data for local testing.

**How to understand the project quickly**
1. Read `app/models/` first — the data structures explain what the business actually tracks.
2. Then read one router end-to-end (e.g. `app/routers/hod.py`) alongside its matching template folder — this shows the full pattern used everywhere: fetch data → check permission → render page or process an action.
3. `app/services/submission_service.py` is the most important file — it contains the budget and status-rollup logic used by every approval stage.

**How to add a new feature (general pattern)**
1. If it needs new data, add a column/table in `app/models/`, then generate a migration: `alembic revision --autogenerate -m "describe change"`, review it, then `alembic upgrade head`.
2. Add or extend a function in `app/services/` if it involves business logic (not just displaying data).
3. Add or edit a route in the relevant `app/routers/` file.
4. Add or edit the matching template in `app/templates/`.
5. Test the full flow manually (create → approve → reject → view) before pushing.

**Best practices for maintaining the project**
- Never edit a database table by writing raw SQL by hand — always go through an Alembic migration, so every environment (dev, staging, production) stays in sync.
- Keep business logic (budget math, status transitions) in `app/services/`, not scattered inside route handlers — this is what made the per-item approval rebuild possible without breaking other pages.
- Treat `LineItem.status` as the single source of truth for where an item is in the workflow; `Submission.status` is only a computed summary — never write logic that trusts `Submission.status` for permissions or budget decisions.
- Always write an `AuditLog` entry for anything that changes money or approval state — this is a compliance requirement, not optional logging.
- Set `SEED_DB=false` and use PostgreSQL with a persistent database before this system holds real financial data.
- Keep secrets (`SECRET_KEY`, SMTP/Azure credentials) only in environment variables — never commit them to the repository.
