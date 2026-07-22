# CashCall — Migration Guide: Render → DPRP Azure Environment

**Audience:** DevOps / cloud infrastructure engineers executing the migration.
**Source environment:** Render (SQLite, ephemeral disk, Render-managed TLS/DNS).
**Target environment:** Dangote Petroleum Refinery & Petrochemicals (DPRP) internal network, Microsoft Azure IaaS, Azure AD (Microsoft 365) tenant, Azure Database for PostgreSQL.

**Assumptions made explicit up front** (confirm/adjust with DPRP IT before Phase 2):
- Target compute is an **Azure VM (IaaS)** running Docker, reusing this repo's existing `docker-compose.prod.yml` + `nginx/nginx.conf` (already written for an Nginx + app + Postgres stack) rather than a PaaS service — this matches "internal network" / "organization server" phrasing. If DPRP's platform team mandates App Service or Container Apps instead, the application container itself is unchanged; only Phases 2 and 4 need re-scoping.
- The production database will be a **managed Azure Database for PostgreSQL Flexible Server**, not a containerized Postgres — more appropriate for an organization system of record than the `db` container in `docker-compose.prod.yml` (no managed backups/patching). This guide shows how to adapt the compose file accordingly.
- Per this session's own investigation, the current Render deployment holds **no real production data** — only demo/seed data, wiped on every redeploy due to `SEED_DB=true` + ephemeral disk. Phase 3 accounts for both cases (empty start vs. real data to migrate) but assume the former unless Phase 1 proves otherwise.

---

## Phase 1 — Pre-Migration Prerequisites and Environment Assessment

**Objective:** Establish exactly what exists today, capture every secret before it's lost, confirm access to the target environment, and create a rollback point — before anything is touched.

### Steps

1. **Confirm access**, in writing, before starting:
   - GitHub: push access to `sasquare/cashcall`.
   - Render: dashboard access to the existing service (to read current environment variables).
   - Azure: a subscription with `Contributor` role on the target resource group, plus an Azure AD role capable of creating App Registrations (`Application Administrator` or `Global Administrator`).
   - DNS: access to DPRP's internal DNS zone (or delegated authority to request records).

2. **Capture every current Render environment variable.** In the Render dashboard → service → Environment tab, record the value of each of the following (all are read by `app/config.py`):
   ```
   APP_ENV, SECRET_KEY, DATABASE_URL, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET,
   AZURE_TENANT_ID, AZURE_REDIRECT_URI, DEV_BYPASS_ENABLED,
   ALLOWED_EMAIL_DOMAINS, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
   EMAIL_FROM, SESSION_MAX_AGE_SECONDS, SEED_DB
   ```
   Store these temporarily in a password manager or secrets vault — **not** in a plaintext file committed anywhere.

3. **Determine whether Render currently holds real data.** Open a Render shell on the running service and run:
   ```bash
   sqlite3 cashcall.db "SELECT COUNT(*) FROM submissions;"
   sqlite3 cashcall.db "SELECT COUNT(*) FROM users WHERE email NOT LIKE '%@dangote.com';"
   ```
   If `submissions` contains anything beyond the test batch(es) created during development/QA, treat this as **real data requiring migration** and follow the data-migration branch in Phase 3, Step 6. Otherwise, plan for a clean start on Postgres.

4. **Confirm target software versions** required by the codebase (do not substitute):
   - Python: **3.11** (`Dockerfile` base image `python:3.11-slim`).
   - PostgreSQL: **16** (`docker-compose.prod.yml` uses `postgres:16-alpine`; Alembic migrations were only validated against this version).
   - Docker Engine ≥ 24 and Docker Compose v2 (`docker compose`, not the legacy `docker-compose` binary).
   - Dependencies are already Postgres-ready: `requirements.txt` includes `psycopg2-binary==2.9.10` — **no code change is needed** to switch database engines.

5. **Get these decisions from DPRP IT/network team before Phase 2:**
   - Target Azure subscription + resource group name.
   - VNet/subnet the VM will join (must have line-of-sight to Azure AD / internal DNS / mail relay).
   - Internal hostname to be issued, e.g. `cashcall.dprp.dangote.com`.
   - Minimum VM size (recommend **Standard_B2ms** — 2 vCPU / 8 GB — as a starting point for a low-QPS internal approval tool; the app has an in-process rate limit of 120 req/min per IP, which is a strong signal this was designed for modest load).
   - Whether TLS will use DPRP's internal PKI/CA or a public CA via a resolvable subdomain.

6. **Tag the current codebase** for a clean rollback reference:
   ```bash
   git fetch origin main
   git checkout main
   git pull
   git tag pre-azure-migration
   git push origin pre-azure-migration
   ```

### Verification Checklist

- [ ] All current Render environment variable values captured and stored securely
- [ ] Confirmed whether Render holds real data or only test/demo data
- [ ] Azure subscription/resource group access confirmed for the migration engineer
- [ ] Azure AD tenant ID obtained and app-registration rights confirmed
- [ ] Target internal hostname decided with DPRP network team
- [ ] `pre-azure-migration` git tag created and pushed

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| Render env vars unrecoverable (e.g. access revoked before capture) | Didn't capture before losing access | Rotate all secrets fresh in the new environment instead of trying to recover old values — this is safe since none of them (SECRET_KEY, SMTP password, Azure client secret) should be reused across environments anyway |
| Real data discovered late, after Render is decommissioned | Skipped Step 3 | Render's disk is ephemeral — if the service has been redeployed since data was created, it is almost certainly already gone; check backups if Render's paid tier with persistent disk was ever enabled |

---

## Phase 2 — Infrastructure Provisioning (Server, Domain, TLS, DNS)

**Objective:** Stand up the Azure VM that will run the Dockerized stack, reachable only from DPRP's internal network, with a valid TLS certificate.

### Steps

1. **Create the resource group and VM** (adjust names/region to DPRP conventions):
   ```bash
   az group create --name rg-cashcall-prod --location eastus

   az vm create \
     --resource-group rg-cashcall-prod \
     --name vm-cashcall-prod \
     --image Ubuntu2204 \
     --size Standard_B2ms \
     --vnet-name <dprp-existing-vnet> \
     --subnet <dprp-app-subnet> \
     --public-ip-address "" \
     --admin-username cashcalladmin \
     --generate-ssh-keys
   ```
   `--public-ip-address ""` deliberately gives the VM **no public IP** — it is reachable only inside the VNet, consistent with "internal network only." SSH access is via DPRP's existing bastion/jump host.

2. **Install Docker Engine + Compose plugin** (SSH in via bastion first):
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker cashcalladmin
   sudo apt-get update && sudo apt-get install -y docker-compose-plugin
   # log out/in for group membership to take effect
   docker --version
   docker compose version
   ```

3. **Lock down the Network Security Group** to only what's needed:
   ```bash
   az network nsg rule create --resource-group rg-cashcall-prod --nsg-name <vm-nsg> \
     --name AllowHTTPSInternal --priority 100 --direction Inbound --access Allow \
     --protocol Tcp --destination-port-ranges 443 --source-address-prefixes <dprp-internal-cidr>

   az network nsg rule create --resource-group rg-cashcall-prod --nsg-name <vm-nsg> \
     --name AllowSSHFromBastion --priority 110 --direction Inbound --access Allow \
     --protocol Tcp --destination-port-ranges 22 --source-address-prefixes <bastion-ip>
   ```
   Do **not** open port 80 to anything except the VM's own loopback needs for the HTTP→HTTPS redirect already configured in `nginx/nginx.conf`; if DPRP requires internal HTTP access too, scope it identically to the HTTPS rule.

4. **Register the internal DNS record.** Coordinate with DPRP's network/DNS team to create an A record (Azure Private DNS zone, or on-prem DNS if that's authoritative for `dangote.com` internally):
   ```
   cashcall.dprp.dangote.com  →  <VM private IP>
   ```

5. **Obtain a TLS certificate.** For an internal-only hostname, request one from DPRP's internal Certificate Authority (do not use a self-signed cert — it will show browser warnings for every user, including inside Outlook-embedded links). Once issued, place the files on the VM exactly where `nginx/nginx.conf` expects them:
   ```bash
   sudo mkdir -p /opt/cashcall/nginx/certs
   # copy fullchain.pem and privkey.pem from the CA issuance into:
   #   /opt/cashcall/nginx/certs/fullchain.pem
   #   /opt/cashcall/nginx/certs/privkey.pem
   sudo chmod 600 /opt/cashcall/nginx/certs/privkey.pem
   ```
   These paths match `docker-compose.prod.yml`'s existing volume mount (`./nginx/certs:/etc/nginx/certs:ro`) and `nginx.conf`'s `ssl_certificate`/`ssl_certificate_key` directives — no config changes needed here.

6. **Clone the repository onto the VM:**
   ```bash
   sudo mkdir -p /opt/cashcall && sudo chown cashcalladmin:cashcalladmin /opt/cashcall
   cd /opt/cashcall
   git clone https://github.com/sasquare/cashcall.git .
   git checkout main
   ```

### Verification Checklist

- [ ] VM has no public IP; reachable only via bastion (SSH) and internal VNet (HTTPS)
- [ ] `docker --version` and `docker compose version` succeed on the VM
- [ ] NSG inbound rules allow only 443 from internal CIDR and 22 from bastion — no `0.0.0.0/0` rules
- [ ] `nslookup cashcall.dprp.dangote.com` from another internal host resolves to the VM's private IP
- [ ] `fullchain.pem` and `privkey.pem` present at `/opt/cashcall/nginx/certs/`
- [ ] Repository cloned at `/opt/cashcall`, on `main`

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| VM can't resolve internal DNS or reach Azure AD | VM placed in the wrong VNet/subnet, no peering to DPRP's core network | Recreate the VM in the correct VNet, or set up VNet peering |
| Browser shows "certificate not trusted" for all users | Used a self-signed cert instead of one issued by DPRP's internal CA (or a CA already in the corporate trust store) | Re-issue via the internal CA; don't attempt to `openssl req -x509` a temporary cert for production |
| `docker compose` command not found | Only the legacy standalone `docker-compose` (v1) was installed | Install `docker-compose-plugin`; the compose files in this repo use v2 syntax |

---

## Phase 3 — Database Migration (SQLite → PostgreSQL, Schema, Seed Data)

**Objective:** Provision a managed PostgreSQL instance, apply the application's schema via Alembic, and load only genuine reference data (exchange rates, the real 2026 OPEX budget figures) — never the demo/test data.

### Steps

1. **Provision Azure Database for PostgreSQL Flexible Server**, version 16, inside the same VNet as the app VM (private access, no public endpoint):
   ```bash
   az postgres flexible-server create \
     --resource-group rg-cashcall-prod \
     --name psql-cashcall-prod \
     --location eastus \
     --version 16 \
     --sku-name Standard_B2s \
     --storage-size 32 \
     --vnet <dprp-existing-vnet> --subnet <dprp-db-subnet> \
     --admin-user cashcall_admin \
     --admin-password '<generate-and-store-in-key-vault>'
   ```

2. **Create the application database and a least-privilege application role** (do not use the server admin account for the running app):
   ```sql
   -- connect as cashcall_admin
   CREATE DATABASE cashcall;
   \c cashcall
   CREATE ROLE cashcall_app WITH LOGIN PASSWORD '<generate-and-store-in-key-vault>';
   GRANT ALL PRIVILEGES ON DATABASE cashcall TO cashcall_app;
   GRANT ALL ON SCHEMA public TO cashcall_app;
   ```

3. **Compose the connection string** in the exact format `app/config.py`/SQLAlchemy expects:
   ```
   DATABASE_URL=postgresql+psycopg2://cashcall_app:<password>@psql-cashcall-prod.postgres.database.azure.com:5432/cashcall?sslmode=require
   ```
   `sslmode=require` is mandatory — Flexible Server enforces SSL by default and the connection will be refused without it.

4. **If Phase 1 found real data on Render, migrate it now** (skip to Step 5 if starting clean):
   - Do **not** attempt a raw `sqlite3 .dump` → `psql` import — SQLite's dump syntax (`AUTOINCREMENT`, type affinities) is not directly Postgres-compatible and will fail or silently corrupt types.
   - Instead, write a one-off Python migration script using the app's own SQLAlchemy models to read every row from the old SQLite file and bulk-insert into the new Postgres database, table by table, in FK-safe order: `users` → `exchange_rates` → `category_budgets` → `submissions` → `line_items` → `audit_log` → `system_audit_log`.
   - Run this script locally against a copy of the Render SQLite file and the new `DATABASE_URL`, **before** applying Alembic migrations to Postgres in Step 5 — insert into a schema Alembic has already created (run Step 5 first, then load data).

5. **Apply the schema.** From a machine with network access to the new database (the VM itself is easiest, after Phase 4's `git clone`):
   ```bash
   cd /opt/cashcall
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   export DATABASE_URL="postgresql+psycopg2://cashcall_app:<password>@psql-cashcall-prod.postgres.database.azure.com:5432/cashcall?sslmode=require"
   alembic upgrade head
   ```
   This runs all five migrations in order: `18feaeb4a6c9` (initial schema) → `a1b2c3d4e5f6` (system audit log) → `b2c3d4e5f6a7` (category budgets by category) → `c3d4e5f6a7b8` (per-item approval pipeline) → `d4e5f6a7b8c9` (audit stage columns + the `line_item_approval_report` reporting view). The last migration's `CREATE VIEW` statement is plain ANSI SQL with no SQLite-specific functions, so it applies identically on Postgres.

6. **Load real reference data — deliberately, not via a blanket seed run.** `scripts/seed.py` mixes three things: fictional demo users (weak shared passwords like `HOD@12345`), sample departments, and the **genuine** Finance-supplied 2026 OPEX category budget figures (`seed_budgets()`). Only the last of these belongs in production:
   ```bash
   python3 -c "
   from app.database import SessionLocal
   from scripts.seed import seed_budgets
   db = SessionLocal()
   seed_budgets(db)
   db.close()
   "
   ```
   Exchange rates should be entered via **Admin → Exchange Rates** in the running app once it's up (Phase 4), using live rates — not the placeholder values in `seed.py`.
   Real users are provisioned in Phase 8, not here.

### Verification Checklist

- [ ] `alembic current` (with `DATABASE_URL` pointed at the new Postgres) reports `d4e5f6a7b8c9 (head)`
- [ ] `psql` `\dt` shows: `users, submissions, line_items, audit_log, system_audit_log, category_budgets, exchange_rates, alembic_version`
- [ ] `SELECT * FROM line_item_approval_report LIMIT 1;` runs without error (confirms the reporting view built for Power BI exists and is queryable)
- [ ] `SELECT category, month, monthly_allocation_usd FROM category_budgets ORDER BY category, month;` matches Finance's real 2026 figures
- [ ] Zero rows in `users` at this point (real users are provisioned in Phase 8) — confirms no demo accounts leaked into production
- [ ] If real data was migrated: row counts in `submissions`/`line_items` on Postgres match the Render source exactly

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| `alembic upgrade head` hangs or errors on a `batch_alter_table` block | These were written for SQLite's ALTER TABLE limitations; on Postgres `batch_alter_table` is effectively a no-op passthrough and should apply cleanly — a genuine failure here usually means the target DB/role lacks `ALTER`/`CREATE` privileges | Confirm `cashcall_app` (or whichever role is running the migration) has full DDL rights on the `public` schema |
| `psycopg2.OperationalError: SSL connection is required` | Missing `?sslmode=require` in `DATABASE_URL` | Add it — Flexible Server rejects unencrypted connections by default |
| Data migration script fails on a foreign key violation | Tables loaded out of order | Always load in FK-dependency order: `users` before anything referencing `created_by`/`performed_by`; `submissions` before `line_items`/`audit_log` |

---

## Phase 4 — Application Deployment (Docker, Environment Variables, Secrets)

**Objective:** Run the containerized application on the VM, pointed at the new Postgres instance, with production secrets sourced securely rather than committed anywhere.

### Steps

1. **Provision Azure Key Vault** for production secrets:
   ```bash
   az keyvault create --resource-group rg-cashcall-prod --name kv-cashcall-prod --location eastus
   az keyvault secret set --vault-name kv-cashcall-prod --name SECRET-KEY --value "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
   az keyvault secret set --vault-name kv-cashcall-prod --name DATABASE-URL --value "postgresql+psycopg2://cashcall_app:<password>@psql-cashcall-prod.postgres.database.azure.com:5432/cashcall?sslmode=require"
   az keyvault secret set --vault-name kv-cashcall-prod --name AZURE-CLIENT-SECRET --value "<from Phase 5>"
   az keyvault secret set --vault-name kv-cashcall-prod --name SMTP-PASSWORD --value "<DPRP mail relay credential>"
   ```
   **Never reuse the `SECRET_KEY` value captured from Render** — generate a fresh one; it signs session cookies and reusing it across environments has no benefit and only widens blast radius if either is ever compromised.

2. **Build the production `.env` on the VM** (pull secret values from Key Vault at deploy time via a small fetch script, or paste manually for the initial cutover and rotate to a Key Vault-backed fetch afterward):
   ```bash
   cat > /opt/cashcall/.env <<'EOF'
   APP_ENV=production
   SECRET_KEY=<from Key Vault>
   APP_TITLE=DPRP Cash Call Automation System
   DATABASE_URL=<from Key Vault>
   AZURE_CLIENT_ID=<from Phase 5>
   AZURE_CLIENT_SECRET=<from Key Vault>
   AZURE_TENANT_ID=<DPRP tenant ID>
   AZURE_REDIRECT_URI=https://cashcall.dprp.dangote.com/auth/callback
   DEV_BYPASS_ENABLED=false
   ALLOWED_EMAIL_DOMAINS=dangote.com
   SMTP_HOST=<DPRP mail relay host>
   SMTP_PORT=587
   SMTP_USER=<service account>
   SMTP_PASSWORD=<from Key Vault>
   EMAIL_FROM=cashcall@dangote.com
   SESSION_MAX_AGE_SECONDS=28800
   SEED_DB=false
   EOF
   chmod 600 /opt/cashcall/.env
   ```
   `SEED_DB=false` is critical in production — leaving it `true` re-runs `scripts/seed.py` (demo data) on every container restart, which is the exact bug that wiped this app's audit trail earlier in its life on Render.

3. **Adjust `docker-compose.prod.yml` for a managed database.** As committed, this file also defines a containerized `db` service — since Phase 3 uses managed Azure Postgres instead, remove that service and the `app` service's dependency on it:
   ```yaml
   # docker-compose.prod.yml — edit on the VM (or maintain a DPRP-specific overlay file)
   services:
     app:
       environment:
         APP_ENV: production
         DEV_BYPASS_ENABLED: "false"
         # DATABASE_URL now comes from .env / Key Vault, not this override —
         # delete the DATABASE_URL line under `app.environment` here.
       # delete the `depends_on: db` block

     # delete the entire `db:` service block

     nginx:
       # unchanged — still fronts the app container with TLS as configured
   ```
   Keep this edit in a DPRP-specific branch or a separate `docker-compose.azure.yml` overlay rather than modifying the shared repo file destructively, so the original Render/local-dev compose setup still works for other environments.

4. **Build and start the stack:**
   ```bash
   cd /opt/cashcall
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```
   `entrypoint.sh` runs automatically on container start: `alembic upgrade head` (safe to re-run — idempotent), then (since `SEED_DB=false`) skips seeding, then starts `uvicorn`.

5. **Tail logs to confirm a clean boot:**
   ```bash
   docker compose logs -f app
   ```
   Expect to see `[entrypoint] Running Alembic migrations…` → no pending migrations → `[entrypoint] Starting uvicorn…` with no tracebacks.

### Verification Checklist

- [ ] `docker compose ps` shows `app` and `nginx` containers `healthy`/`running` (no `db` container, since Postgres is managed externally)
- [ ] `curl -sk https://cashcall.dprp.dangote.com/health` (from inside the network) returns `{"status":"ok","env":"production"}`
- [ ] `/opt/cashcall/.env` has permissions `600` and is **not** committed to git (confirm `.env` is in `.gitignore`)
- [ ] `docker compose logs app` shows the Alembic step completing with no errors and no seed step running
- [ ] `curl -sk https://cashcall.dprp.dangote.com/docs` returns `404` (API docs are disabled automatically when `APP_ENV=production`, per `app/main.py`)

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| `/health` times out or connection refused | App container can't reach Postgres (NSG/VNet blocking port 5432 between the app subnet and DB subnet) | Add an NSG rule allowing the app VM's subnet → Postgres Flexible Server on 5432 |
| App container restarts in a crash loop | Missing/malformed `DATABASE_URL` or `SECRET_KEY` in `.env` | `docker compose logs app` will show the exact exception; re-check `.env` values against Phase 3/Step 3's format |
| Login sessions inexplicably invalidated after every deploy | `SECRET_KEY` regenerated on every deploy instead of being fixed in Key Vault | Ensure the deploy process fetches the *same* stored `SECRET_KEY`, not a freshly generated one, on every restart |

---

## Phase 5 — Azure AD / Microsoft 365 SSO Configuration

**Objective:** Register the application in DPRP's Azure AD tenant, restrict sign-in to DPRP accounts only, and understand the app's (deliberate) requirement that every SSO user must also exist as a pre-provisioned local record.

### Steps

1. **Register the app** in Azure Portal → **Azure Active Directory → App registrations → New registration**:
   - Name: `DPRP Cash Call`
   - Supported account types: **"Accounts in this organizational directory only (DPRP only – Single tenant)"** — this is the primary control keeping non-DPRP Microsoft accounts out at the Azure layer, before the request even reaches the app.
   - Redirect URI: platform = **Web**, URI = `https://cashcall.dprp.dangote.com/auth/callback` — must be an **exact** string match to the `AZURE_REDIRECT_URI` env var (protocol, host, path, no trailing slash difference).

2. **Create a client secret**: App registration → Certificates & secrets → New client secret → copy the value immediately (it is never shown again) → store as `AZURE-CLIENT-SECRET` in Key Vault (Phase 4, Step 1).

3. **Grant API permissions**: App registration → API permissions → Add a permission → Microsoft Graph → Delegated permissions → `User.Read` (this matches `_SCOPES = ["User.Read"]` in `app/services/auth_service.py` — the app requests no other Graph scope). Click **Grant admin consent for DPRP**.

4. **Record the two identifiers** needed by the app:
   - Application (client) ID → `AZURE_CLIENT_ID`
   - Directory (tenant) ID → `AZURE_TENANT_ID`

5. **Update the VM's `.env`** with `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_REDIRECT_URI`, and restart:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app
   ```

6. **Understand the app's login model before provisioning anyone** (this affects Phase 8 directly): Azure AD only confirms *identity*. The app does **not** auto-provision a user record from a successful Azure sign-in — `handle_auth_callback()` in `app/services/auth_service.py` looks up a `User` row by the exact email from the Azure AD claims, and returns `None` (login rejected, redirected to `/login?error=auth_failed`) if no matching **active** local record exists. Every real person needs an Admin-created account (Phase 8) with an email that exactly matches their Azure AD UPN **before** their first SSO login will succeed.

7. **Confirm `ALLOWED_EMAIL_DOMAINS=dangote.com`** is set (added earlier in this project) — this is a second, app-level check applied to every Azure AD login, independent of the tenant restriction in Step 1, so a guest account added to the DPRP tenant from an external company still cannot log in even if Azure authenticates it successfully.

### Verification Checklist

- [ ] App registration shows **Single tenant** support type
- [ ] Redirect URI in Azure matches `AZURE_REDIRECT_URI` exactly (test by inspecting the network request during a failed login attempt if unsure)
- [ ] Admin consent granted for `User.Read`
- [ ] A pre-provisioned pilot user (exists in both Azure AD and the app's `users` table) can complete `/login/microsoft` → lands on `/dashboard`
- [ ] A user who exists in Azure AD but has **no** matching local record is correctly bounced to `/login?error=auth_failed`
- [ ] A guest/external-domain account, even if somehow present in the tenant, is rejected

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| `AADSTS50011: The redirect URI ... does not match` | Redirect URI mismatch between Azure app registration and `AZURE_REDIRECT_URI` | Compare character-for-character, including `https://` and no trailing slash |
| User authenticates at Microsoft's login page successfully but bounces back to `/login?error=auth_failed` | No matching local `users` row, row is `is_active=False`, or email fails `ALLOWED_EMAIL_DOMAINS` | Verify the exact email/UPN in Azure AD (Users → search) matches the `email` column in the app's `users` table |
| SSO can seemingly be bypassed with a password | `DEV_BYPASS_ENABLED` left `true` in production `.env` | Set explicitly to `false` and restart; this must never be `true` outside local development |

---

## Phase 6 — Network and Security Hardening

**Objective:** Apply the additional controls appropriate for running on DPRP's own infrastructure rather than a managed sandbox like Render.

### Steps

1. **Re-verify NSG scoping** from Phase 2 now that the full stack is live — inbound 443 only from DPRP internal CIDR ranges, 22 only from the bastion. Explicitly check for and remove any Azure default "AllowVnetInBound" rule that might let *other* VMs/apps in the same VNet reach the app unintentionally if that's broader than intended.

2. **Confirm response security headers are active at both layers** (both already exist in code/config, this step is verification, not new work):
   - `nginx/nginx.conf`: `Strict-Transport-Security`, `X-Frame-Options DENY`, `X-Content-Type-Options nosniff`, `Referrer-Policy`, `Permissions-Policy`.
   - `app/main.py`'s `SecurityHeadersMiddleware`: the same headers applied at the application layer as defense in depth; `Strict-Transport-Security` only appears when `APP_ENV=production`.
   ```bash
   curl -skI https://cashcall.dprp.dangote.com/ | grep -Ei "strict-transport|x-frame|x-content-type|referrer-policy|permissions-policy"
   ```

3. **Understand the rate limiter's scaling limit.** `app/main.py`'s `RateLimitMiddleware` caps each source IP at 120 requests/minute — but this counter lives **in-process**, per container. If DPRP later scales to multiple app replicas behind a load balancer, this limit is not shared across them (each replica independently allows 120/min from the same IP). Acceptable for a single-VM deployment; flag to DPRP's platform team as a future item if horizontal scaling is planned (would need a shared store such as Redis).

4. **Confirm `DEV_BYPASS_ENABLED=false` and API docs are disabled**:
   ```bash
   curl -sk -o /dev/null -w "%{http_code}\n" https://cashcall.dprp.dangote.com/docs        # expect 404
   curl -sk -o /dev/null -w "%{http_code}\n" https://cashcall.dprp.dangote.com/openapi.json # expect 404
   ```

5. **Restrict the Postgres Flexible Server firewall** to only the app VM's subnet (and, later, the Power BI gateway host from Phase 7) — no public network access rule should exist.

6. **Enable automated OS patching** via Azure Update Manager on the VM, and establish a cadence for rebuilding the Docker image (the `python:3.11-slim` base image should be pulled fresh periodically to pick up security patches — this is a manual `docker compose build --no-cache` + redeploy today, since there's no CI/CD pipeline defined in this repo yet).

7. **Configure Postgres automated backups**: Flexible Server has built-in point-in-time restore; confirm the retention window against DPRP's data-retention policy and document the restore procedure.

8. **Forward container logs to Azure Monitor** for centralized audit/troubleshooting (e.g. via the Azure Monitor Agent or a lightweight log-forwarding sidecar), since `docker compose logs` alone won't survive VM loss and isn't centrally searchable.

### Verification Checklist

- [ ] `curl -I https://cashcall.dprp.dangote.com` from **outside** DPRP's network fails/times out
- [ ] Security headers present in the response (Step 2's command)
- [ ] `/docs` and `/openapi.json` return `404`
- [ ] Postgres Flexible Server firewall shows no public-access rule
- [ ] A test point-in-time restore of the database has been performed and validated at least once
- [ ] Container/application logs are visible in Azure Monitor / Log Analytics

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| App reachable from outside the corporate network | VM was given a public IP, or an NSG rule is broader than intended | Remove the public IP (Phase 2 already avoids this); audit all NSG rules for `0.0.0.0/0` or `Internet` source tags |
| Legitimate internal users occasionally get `429 Too Many Requests` | Many users sharing one egress/NAT IP on the corporate network hit the 120 req/min-per-IP limit collectively | Raise `_RATE_LIMIT` in `app/main.py` (currently `120`) for an internal-only deployment where the threat model is different from a public internet-facing app, and redeploy |

---

## Phase 7 — Power BI Database Connection Setup

**Objective:** Give Power BI safe, read-only, least-privilege access to reporting data via the `line_item_approval_report` view (added specifically for this purpose) — never via the application's own database credentials.

### Steps

1. **Create a dedicated read-only Postgres role:**
   ```sql
   CREATE ROLE powerbi_reader WITH LOGIN PASSWORD '<generate-and-store-in-key-vault>';
   GRANT CONNECT ON DATABASE cashcall TO powerbi_reader;
   GRANT USAGE ON SCHEMA public TO powerbi_reader;
   GRANT SELECT ON line_item_approval_report, category_budgets TO powerbi_reader;
   -- Deliberately NOT granted: users, audit_log, submissions, line_items directly —
   -- the reporting view already exposes everything needed without touching
   -- raw tables (which include hashed passwords and internal FK plumbing).
   ```

2. **Provide connectivity for Power BI.** Since the Postgres server has no public endpoint (Phase 6), install the **On-premises Data Gateway** on a machine inside DPRP's network with connectivity to the Postgres Flexible Server's private endpoint, and register it against the organization's Power BI tenant (Power BI admin portal → Manage gateways).

3. **Connect from Power BI Desktop**: Get Data → **PostgreSQL database** → Server = the Flexible Server's private FQDN → Database = `cashcall` → enable **Encrypt connection** → credentials = `powerbi_reader`. Choose **Import** mode for scheduled refresh, or **DirectQuery** if near-real-time is required (at a query-performance cost).

4. **Build reports against these two objects:**
   - `line_item_approval_report` — one flattened row per line item: vendor, category, currency/amounts, current status, and every stage's decision + timestamp (`hod_decided_at`, `finance_qc_decided_at`, `cfo_decided_at`, `cfo_deferred`/`cfo_defer_to_month`, `ceo_decided_at`, `treasury_updated_at`). Use this for: approval turnaround (delta between consecutive stage timestamps), rejected-vendor analysis, deferred-invoice tracking, monthly submission trends, and bottleneck identification (which stage holds items longest).
   - `category_budgets` — monthly allocation vs. `approved_mtd`/`paid_mtd`/`deferred_approved` per category, for budget-utilization dashboards.

5. **Publish and schedule refresh** in the Power BI Service, via the gateway registered in Step 2 (e.g. daily at 06:00).

### Verification Checklist

- [ ] `powerbi_reader` can `SELECT` from `line_item_approval_report` and `category_budgets`
- [ ] `powerbi_reader` **cannot** read `users`, `audit_log`, `submissions`, or `line_items` directly, and cannot `INSERT`/`UPDATE`/`DELETE` anywhere (test explicitly)
- [ ] On-premises Data Gateway shows "Online" status in the Power BI admin portal
- [ ] A test report built against both objects renders correctly
- [ ] A scheduled refresh has completed successfully at least once

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| Power BI Service refresh fails: "cannot reach data source" | Gateway not installed, not registered, or lost network path to the DB | Confirm gateway status in the admin portal; confirm gateway host can reach Postgres on 5432 |
| `SSL negotiation failed` in Power BI's connector | "Encrypt connection" not enabled in the PostgreSQL connector settings | Enable it — Flexible Server requires SSL |
| Reports show stale or duplicate turnaround numbers | Report built against raw `audit_log` joins instead of the purpose-built `line_item_approval_report` view | Rebuild against the view — it was specifically added to avoid analysts having to hand-write these joins |

---

## Phase 8 — User Provisioning and Role Assignment

**Objective:** Get every real DPRP staff member into the application with the correct role, department, and an email that exactly matches their Azure AD account — required before they can SSO in (see Phase 5, Step 6).

### Steps

1. **Compile the real roster** with DPRP HR/department heads: for every department, at minimum **1 HOD + 2 Originators** (the two-originator requirement established for this system so a backup can raise requests when the primary is on leave), plus at least one each of Finance Reviewer, CFO, CEO, Treasury, and IT Admin.

2. **Bootstrap the first IT Admin account** directly against the database (there is no public self-signup in this app by design — every account is created by an IT Admin, so the very first one has no admin yet to create them):
   ```bash
   docker compose exec app python3 -c "
   from app.database import SessionLocal
   from app.models.user import User
   from app.services.auth_service import verify_password
   import bcrypt
   db = SessionLocal()
   db.add(User(
       email='firstname.lastname@dangote.com',   # must match this person's real Azure AD UPN
       display_name='Firstname Lastname',
       role='it_admin',
       is_active=True,
       hashed_password=bcrypt.hashpw(b'temporary-unused-value', bcrypt.gensalt()).decode(),
   ))
   db.commit()
   "
   ```
   The `hashed_password` value is never actually usable for login once `DEV_BYPASS_ENABLED=false` (SSO-only) — it exists only because the column is currently required by the admin form for new users; any throwaway value satisfies it.

3. **Provision everyone else through Admin → Users** (`https://cashcall.dprp.dangote.com/admin/users/new`) once the first IT Admin can log in via SSO:
   - Email: the person's **exact** Azure AD UPN (do not guess the format from their name — confirm with DPRP IT; a mismatch here is the single most common go-live support ticket).
   - Display name, Role, Department (department is required for `originator`/`hod` roles at the *application* level — the admin form does not currently hard-block a blank department for these roles, so double-check it manually when provisioning).
   - Password field: any throwaway value — never used for SSO accounts.

4. **For bulk onboarding of many users at once**, script it the same way as Step 2 in a loop over the real roster (a real-data equivalent of `_make_dept_users()` in `scripts/seed.py`, which shows the intended pattern — role + department pairing) rather than clicking through the UI dozens of times. Do **not** run `scripts/seed.py` itself in production — it creates fictional department accounts with shared demo passwords.

5. **Deactivate or delete any leftover demo/test accounts** that might have been created during Phase 3/4 verification (`Admin → Users → Deactivate`), before go-live.

### Verification Checklist

- [ ] Every real department has exactly ≥1 active HOD and ≥2 active Originators
- [ ] At least one active account exists for each of: Finance Reviewer, CFO, CEO, Treasury, IT Admin
- [ ] 3–5 spot-check users can each complete SSO login and land on the dashboard matching their role
- [ ] No demo/seed accounts (e.g. anything matching the `hod.<slug>@dangote.com` / `originator.<slug>@dangote.com` pattern from `scripts/seed.py`) remain active
- [ ] Every provisioned email was confirmed against DPRP's Azure AD user list, not guessed

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| A specific user can never log in, others work fine | Their `email` in the app doesn't exactly match their Azure AD UPN (common with maiden names, nicknames, or subdomain differences like `@dprp.dangote.com` vs `@dangote.com`) | Look the person up directly in Azure AD → Users, copy their UPN verbatim, update the app record to match |
| Originator can't select their department when raising a submission | Department left blank at provisioning time | Edit the user record in Admin → Users and set the correct department from the dropdown |
| A whole department has no Originator | Missed in roster compilation | Cross-check the final `users` table against DPRP's org chart before go-live, not after |

---

## Phase 9 — UAT and Go-Live Validation

**Objective:** Prove the complete approval pipeline, notifications, budgets, audit trail, and reporting all work correctly on the new environment with real people, before cutting over fully and decommissioning Render.

### Steps

1. **Run a full pilot submission** through the entire pipeline with 3–5 real pilot users: Originator creates → HOD (exercise Approve, Reject, Defer, and Request Clarification across different line items) → Finance QC → CFO (exercise the month-deferral action specifically) → CEO → Treasury marks paid.

2. **Verify budget figures** in `Admin → Budgets` update correctly at each stage of the pilot (approved_mtd increments on HOD approval, releases on rejection, moves to the deferred month on CFO defer, paid_mtd increments on Treasury payment) — this logic was extensively verified during development; the pilot confirms it behaves identically against the new Postgres instance.

3. **Verify email notifications actually arrive** in real inboxes, not just that the app attempted to send them — confirm with DPRP's messaging/M365 administrators that the app's SMTP service account is permitted to relay mail (a common corporate-network failure mode is silently blocking unauthenticated or unrecognized relay attempts, distinct from an application-level SMTP misconfiguration).

4. **Verify the audit trail** (`Admin → Audit`) shows accurate approver, stage, timestamp, previous status, and new status entries for every action taken during the pilot.

5. **Verify Power BI reflects the pilot data** after a manual "Refresh now" in the Power BI Service.

6. **Sanity-check the rate limiter under realistic traffic patterns** — if DPRP's internal network routes many users through a shared NAT/proxy egress IP, watch for `429` responses during the pilot; if it happens, apply the fix from Phase 6's failure-mode table before go-live, not after.

7. **Plan the DNS/URL cutover communication**: if users have the old Render URL bookmarked or embedded in saved emails, send a company-wide notice with the new `https://cashcall.dprp.dangote.com` URL and a clear cutover date.

8. **Hold a go/no-go review** with the business stakeholders (Finance, the pilot HOD/CFO/CEO/Treasury users) confirming the pilot results are acceptable.

9. **Decommission Render only after a safety window.** Pause (don't immediately delete) the Render service for at least 2 weeks after go-live, in case a rollback is ever needed — only fully delete it once DPRP is confident in the new environment.

### Verification Checklist

- [ ] Full pilot submission completes the entire five-stage pipeline with correct final per-item statuses
- [ ] Budget totals match expected arithmetic after the pilot run
- [ ] Pilot users confirm receipt of expected email notifications
- [ ] Audit trail for the pilot submission is complete and accurate
- [ ] Power BI report reflects pilot data after a manual refresh
- [ ] No unexpected `429` rate-limit responses during pilot usage
- [ ] Stakeholder go/no-go sign-off obtained and documented
- [ ] Render service paused (not deleted) as a rollback safety net

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| Emails never arrive despite the app logging "Email sent" | Corporate mail flow rules blocking the service account as an unrecognized/unauthenticated relay | Escalate to DPRP messaging admins to explicitly allowlist the service account for SMTP AUTH relay — this is a mail-server-side fix, not an app bug |
| Some pilot users report random logouts mid-pilot | `SESSION_MAX_AGE_SECONDS` (8 hours by default) expired during a long testing session, or `SECRET_KEY` changed between deploys (invalidating all existing session cookies) | Confirm `SECRET_KEY` is fixed (Phase 4 failure-mode table); extend `SESSION_MAX_AGE_SECONDS` temporarily during UAT if needed |
| Go-live delayed because a department has no provisioned Originator | Roster gap missed in Phase 8 | Treat Phase 8's department cross-check as a hard gate before scheduling the go/no-go review |
