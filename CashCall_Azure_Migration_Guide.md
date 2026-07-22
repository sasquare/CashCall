# CashCall — Migration Guide: Render → DPRP Azure Environment

**Audience:** DevOps / cloud infrastructure engineers executing the migration.
**Source environment:** Render (SQLite, ephemeral disk, Render-managed TLS/DNS, **test/demo data only — confirmed no real production data exists**).
**Target environment:** Dangote Petroleum Refinery & Petrochemicals (DPRP) internal network, Microsoft Azure, Microsoft Entra ID (Azure AD), **Azure SQL Database (managed SQL Server)**.

### Confirmed facts driving this revision

- **Database engine is SQL Server**, managed on Azure (Azure SQL Database), not PostgreSQL. This is a genuine application-level change, not just a connection-string swap — see the compatibility findings in Phase 3.
- **Microsoft Entra ID** (the current name for Azure AD — same service, same tenant, Microsoft renamed the product in 2023) will be used for SSO, on the `@dangote.com` domain — this already matches how the app's SSO and `ALLOWED_EMAIL_DOMAINS` setting are built.
- **Power Automate and SharePoint** licenses are available. Neither is required for the core migration; they're noted as optional extension points where relevant (Phase 7 for Power BI/Power Automate refresh triggers) rather than built into any required step.
- **Docker is "probably available"** — treat this as unconfirmed until Phase 1 proves it on the actual target server, not a developer workstation. See Phase 1, Step 4 for a note on a Docker Desktop/WSL2 symptom worth ruling out if testing locally on Windows first.
- **Render currently holds no real data** — only test/demo submissions. This removes an entire category of risk and work from this guide: there is no legacy-data export/import step. Phase 3 is schema-plus-reference-data only.
- Target compute is still assumed to be an **Azure VM running Docker**, reusing this repo's existing `docker-compose.prod.yml` + `nginx/nginx.conf` (already written for this shape). If DPRP's platform team mandates App Service or Container Apps instead, only Phases 2 and 4 need re-scoping — the application container itself is unaffected.

---

## Phase 1 — Pre-Migration Prerequisites and Environment Assessment

**Objective:** Establish exactly what exists today, capture every secret before it's lost, confirm access to the target environment, and create a rollback point — before anything is touched.

### Steps

1. **Confirm access**, in writing, before starting:
   - GitHub: push access to `sasquare/cashcall`.
   - Render: dashboard access to the existing service (to read current environment variables).
   - Azure: a subscription with `Contributor` role on the target resource group, plus a Microsoft Entra ID role capable of creating App Registrations (`Application Administrator` or `Global Administrator`).
   - DNS: access to DPRP's internal DNS zone (or delegated authority to request records).

2. **Capture every current Render environment variable.** In the Render dashboard → service → Environment tab, record the value of each of the following (all are read by `app/config.py`):
   ```
   APP_ENV, SECRET_KEY, DATABASE_URL, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET,
   AZURE_TENANT_ID, AZURE_REDIRECT_URI, DEV_BYPASS_ENABLED,
   ALLOWED_EMAIL_DOMAINS, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
   EMAIL_FROM, SESSION_MAX_AGE_SECONDS, SEED_DB, WORKERS
   ```
   Store these temporarily in a password manager or secrets vault — **not** in a plaintext file committed anywhere. None of these values (especially `SECRET_KEY`) should be reused in the new environment (Phase 4 generates fresh ones) — capture them only for reference/rollback, not for reuse.

3. **Confirm there is no real data to migrate.** This was already checked this session: Render's `SEED_DB=true` combined with its ephemeral disk means every redeploy wipes the database back to demo data. Do one final confirmation before decommissioning Render:
   ```bash
   # in a Render shell on the running service
   sqlite3 cashcall.db "SELECT COUNT(*) FROM submissions;"
   ```
   If this returns only the small number of test submissions created during development/QA (not real departmental cash calls), proceed on the assumption used throughout this guide: **no data migration step is needed**, only schema + genuine reference data (Phase 3).

4. **Confirm target software versions and Docker readiness.** Required versions (do not substitute):
   - Python: **3.11** (`Dockerfile` base image `python:3.11-slim`).
   - SQL Server driver: **pymssql 2.3.13** (already updated in `requirements.txt` — see Phase 3's compatibility notes for why this driver was chosen over `pyodbc`).
   - Docker Engine ≥ 24 and Docker Compose v2 (`docker compose`, not the legacy `docker-compose` v1 binary).

   If Docker is being checked on a Windows workstation first (before the real Azure VM is provisioned) and `docker version` reports a client version but then fails with:
   ```
   failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine ...
   open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
   ```
   this means **Docker Desktop's client CLI is installed but its backend engine is not running** — the CLI found `docker.exe` on disk but couldn't reach the daemon. This is a local workstation issue, not a sign Docker is unavailable for the migration. Resolve it by opening the Docker Desktop application (not just the CLI) and waiting for it to report "Engine running," ensuring WSL2 is installed and set as the backend (`Settings → General → Use the WSL 2 based engine`), and confirming the `docker-desktop` WSL distro is running (`wsl -l -v` should show it as `Running`). This is only relevant if testing locally before the real Azure VM exists — the actual target VM (Phase 2) will run Docker natively on Linux with no such issue.

5. **Get these decisions from DPRP IT/network team before Phase 2:**
   - Target Azure subscription + resource group name.
   - VNet/subnet the VM (and Azure SQL Database's private endpoint, if used) will join.
   - Internal hostname to be issued, e.g. `cashcall.dprp.dangote.com`.
   - Minimum VM size (recommend **Standard_B2ms** — 2 vCPU / 8 GB — as a starting point for a low-QPS internal approval tool; the app has an in-process rate limit of 120 req/min per IP, a strong signal this was designed for modest load).
   - Whether TLS will use DPRP's internal PKI/CA or a public CA via a resolvable subdomain.
   - Whether Azure SQL Database will be reached via a **private endpoint** (fully internal, no public exposure — recommended) or a public endpoint locked down by firewall rules (simpler, slightly larger attack surface).

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
- [ ] Confirmed (again, immediately before cutover) that Render holds only test/demo data
- [ ] Azure subscription/resource group access confirmed for the migration engineer
- [ ] Microsoft Entra ID tenant ID obtained and app-registration rights confirmed
- [ ] Target internal hostname decided with DPRP network team
- [ ] Decision made: private endpoint vs. firewalled public endpoint for Azure SQL Database
- [ ] `pre-azure-migration` git tag created and pushed
- [ ] Docker confirmed working on the actual target VM (not just a workstation) — deferred to Phase 2 if the VM doesn't exist yet

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| Render env vars unrecoverable (e.g. access revoked before capture) | Didn't capture before losing access | Rotate all secrets fresh in the new environment instead of trying to recover old values — none should be reused across environments regardless |
| Docker Desktop CLI works but every command fails to reach the daemon | Docker Desktop engine not started, or WSL2 backend not initialized (see Step 4) | Start Docker Desktop fully and confirm "Engine running" before treating Docker as verified — this is a workstation issue, not evidence the target server lacks Docker |

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
   Unlike the Windows Docker Desktop symptom noted in Phase 1, this native Linux install runs the daemon directly on the VM — no WSL2/engine-connection layer to troubleshoot.

3. **Lock down the Network Security Group** to only what's needed:
   ```bash
   az network nsg rule create --resource-group rg-cashcall-prod --nsg-name <vm-nsg> \
     --name AllowHTTPSInternal --priority 100 --direction Inbound --access Allow \
     --protocol Tcp --destination-port-ranges 443 --source-address-prefixes <dprp-internal-cidr>

   az network nsg rule create --resource-group rg-cashcall-prod --nsg-name <vm-nsg> \
     --name AllowSSHFromBastion --priority 110 --direction Inbound --access Allow \
     --protocol Tcp --destination-port-ranges 22 --source-address-prefixes <bastion-ip>
   ```

4. **Register the internal DNS record.** Coordinate with DPRP's network/DNS team to create an A record (Azure Private DNS zone, or on-prem DNS if that's authoritative for `dangote.com` internally):
   ```
   cashcall.dprp.dangote.com  →  <VM private IP>
   ```

5. **Obtain a TLS certificate.** For an internal-only hostname, request one from DPRP's internal Certificate Authority (do not use a self-signed cert). Once issued, place the files exactly where `nginx/nginx.conf` expects them:
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
- [ ] `docker --version` and `docker compose version` succeed on the VM itself (not just a workstation)
- [ ] NSG inbound rules allow only 443 from internal CIDR and 22 from bastion — no `0.0.0.0/0` rules
- [ ] `nslookup cashcall.dprp.dangote.com` from another internal host resolves to the VM's private IP
- [ ] `fullchain.pem` and `privkey.pem` present at `/opt/cashcall/nginx/certs/`
- [ ] Repository cloned at `/opt/cashcall`, on `main`

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| VM can't resolve internal DNS or reach Entra ID | VM placed in the wrong VNet/subnet, no peering to DPRP's core network | Recreate the VM in the correct VNet, or set up VNet peering |
| Browser shows "certificate not trusted" for all users | Used a self-signed cert instead of one issued by DPRP's internal CA | Re-issue via the internal CA |
| `docker compose` command not found | Only the legacy standalone `docker-compose` (v1) was installed | Install `docker-compose-plugin`; the compose files in this repo use v2 syntax |

---

## Phase 3 — Database Migration (SQLite → Azure SQL Database, Schema, Reference Data)

**Objective:** Provision Azure SQL Database, confirm the application is genuinely compatible with SQL Server (verified below, not assumed), apply the schema via Alembic, and load only real reference data.

### Compatibility verification already performed

Before writing this phase, the actual Alembic migration chain was compiled against SQLAlchemy's real `mssql` dialect (offline SQL generation — `alembic upgrade head --sql` with `DATABASE_URL=mssql+pymssql://...`) to catch any PostgreSQL/SQLite-specific assumptions before they became a production surprise. Findings:

- **Every table and column compiles correctly** to native T-SQL types: `INTEGER ... IDENTITY` for primary keys, `DATETIMEOFFSET` for timezone-aware timestamps, `BIT` for booleans, `NUMERIC(18,2)` for money fields, `DEFAULT (CURRENT_TIMESTAMP)` for server-side timestamp defaults (this last one already uses ANSI-standard `CURRENT_TIMESTAMP` rather than a Postgres-only `now()`, a fix already made in this codebase's history — it happens to also be exactly what SQL Server needs).
- **The one non-portable query construct in the app** — `.ilike()`, used in the HOD/Finance/CFO tracker search boxes (`app/routers/hod.py`, `finance_qc.py`, `cfo.py`) — was confirmed to compile correctly to `lower(x) LIKE lower(y)` on the mssql dialect (SQLAlchemy's built-in fallback for dialects without native `ILIKE`). No code change needed.
- **The Power BI reporting view** (`CREATE VIEW line_item_approval_report`, added in migration `d4e5f6a7b8c9`) is plain ANSI `SELECT`/`JOIN` SQL and compiles unchanged; it correctly renders as the first statement in its own batch, which T-SQL requires for `CREATE VIEW`.
- **Minor, non-blocking note:** columns declared with SQLAlchemy's generic `Text` type (e.g. `hod_comment`, `cfo_reason`) compile to SQL Server's legacy `TEXT` type rather than the modern `VARCHAR(MAX)`/`NVARCHAR(MAX)`. `TEXT` still works correctly in SQL Server (deprecated but functional, no removal announced), so this does not block migration — flagging it as an optional follow-up if DPRP's DBAs prefer to modernize it later.
- **Driver choice:** `pyodbc` (the more commonly documented SQL Server driver) requires installing Microsoft's ODBC Driver 17/18 and `unixODBC` at the OS level inside the Docker image — a real Dockerfile change. `pymssql` (bundles FreeTDS, pure-Python-wheel install) was tested instead: `pip install pymssql` succeeds with **zero additional system packages**, and the app's `Dockerfile` (`python:3.11-slim`, glibc-based) needs **no changes at all** to support it. `requirements.txt` has already been updated: `psycopg2-binary` → `pymssql==2.3.13`.
- **What was not tested:** an actual live connection to a real Azure SQL Database instance (none was available in the environment this verification ran in). The offline dialect-compilation check is a genuine, meaningful test of SQL correctness, but Phase 3, Step 6's verification checklist below requires a real `alembic upgrade head` run against a live dev/test Azure SQL Database before trusting this for production.

### Steps

1. **Provision Azure SQL Database:**
   ```bash
   az sql server create \
     --resource-group rg-cashcall-prod \
     --name sql-cashcall-prod \
     --location eastus \
     --admin-user cashcall_admin \
     --admin-password '<generate-and-store-in-key-vault>'

   az sql db create \
     --resource-group rg-cashcall-prod \
     --server sql-cashcall-prod \
     --name cashcall \
     --service-objective S1
   ```
   `S1` (Standard tier) is a reasonable starting point for a low-QPS internal tool; DPRP's DBA team can right-size based on observed usage after go-live.

2. **Network-isolate it.** For a private-endpoint deployment (recommended, matches "internal network"):
   ```bash
   az network private-endpoint create \
     --resource-group rg-cashcall-prod \
     --name pe-cashcall-sql \
     --vnet-name <dprp-existing-vnet> --subnet <dprp-db-subnet> \
     --private-connection-resource-id $(az sql server show -g rg-cashcall-prod -n sql-cashcall-prod --query id -o tsv) \
     --group-id sqlServer \
     --connection-name cashcall-sql-connection
   ```
   Then disable the server's public network access entirely: `az sql server update -g rg-cashcall-prod -n sql-cashcall-prod --set publicNetworkAccess=Disabled`. If DPRP instead opts for a firewalled public endpoint, use `az sql server firewall-rule create` scoped only to the app VM's outbound IP and, later, the Power BI gateway host (Phase 7) — never `0.0.0.0`–`255.255.255.255`.

3. **Create a least-privilege application login and user** (do not use the `cashcall_admin` server-level account for the running app):
   ```sql
   -- connect to the 'master' database as cashcall_admin
   CREATE LOGIN cashcall_app WITH PASSWORD = '<generate-and-store-in-key-vault>';

   -- then connect to the 'cashcall' database
   CREATE USER cashcall_app FOR LOGIN cashcall_app;
   ALTER ROLE db_datareader ADD MEMBER cashcall_app;
   ALTER ROLE db_datawriter ADD MEMBER cashcall_app;
   GRANT CREATE TABLE, ALTER, CREATE VIEW TO cashcall_app;  -- needed once, for Alembic to apply the schema
   ```

4. **Compose the connection string** in the format the app's SQLAlchemy setup expects:
   ```
   DATABASE_URL=mssql+pymssql://cashcall_app:<password>@sql-cashcall-prod.database.windows.net:1433/cashcall
   ```
   Azure SQL Database enforces encrypted connections by default; FreeTDS (which `pymssql` wraps) negotiates TLS automatically on modern builds. If a connection is refused specifically over encryption negotiation, append `?tds_version=7.4` and confirm the `pymssql` wheel installed was built against a FreeTDS version that supports TLS 1.2 (the `pymssql==2.3.13` pin already verified in this guide's compatibility check bundles a current FreeTDS).

5. **Apply the schema**, from the VM after Phase 2's `git clone`:
   ```bash
   cd /opt/cashcall
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   export DATABASE_URL="mssql+pymssql://cashcall_app:<password>@sql-cashcall-prod.database.windows.net:1433/cashcall"
   alembic upgrade head
   ```
   This runs all five migrations in order: `18feaeb4a6c9` (initial schema) → `a1b2c3d4e5f6` (system audit log) → `b2c3d4e5f6a7` (category budgets by category) → `c3d4e5f6a7b8` (per-item approval pipeline) → `d4e5f6a7b8c9` (audit stage columns + the `line_item_approval_report` reporting view).

   **If DPRP's change-control process requires DBA review of DDL before it runs against production**, generate the script instead of running it live, and hand the reviewed `.sql` file to a DBA to execute via `sqlcmd` or Azure Data Studio (both understand the `GO` batch separators Alembic emits in this mode — a raw DBAPI connection or `psql`-style tool does not, so this generated file must go through a `GO`-aware client):
   ```bash
   alembic upgrade head --sql > cashcall_schema.sql
   ```

6. **Load real reference data — deliberately, not via a blanket seed script run.** `scripts/seed.py` mixes fictional demo users (weak shared passwords) with the **genuine** Finance-supplied 2026 OPEX category budget figures (`seed_budgets()`). Only the latter belongs in production:
   ```bash
   python3 -c "
   from app.database import SessionLocal
   from scripts.seed import seed_budgets
   db = SessionLocal()
   seed_budgets(db)
   db.close()
   "
   ```
   Exchange rates should be entered via **Admin → Exchange Rates** in the running app once it's up (Phase 4), using live rates. Real users are provisioned in Phase 8.

### Verification Checklist

- [ ] `alembic current` (with `DATABASE_URL` pointed at the live Azure SQL Database) reports `d4e5f6a7b8c9 (head)` — this is the **live-connection confirmation** the offline compatibility check above could not itself provide
- [ ] In Azure Data Studio or `sqlcmd`, `SELECT name FROM sys.tables;` shows: `users, submissions, line_items, audit_log, system_audit_log, category_budgets, exchange_rates, alembic_version`
- [ ] `SELECT TOP 1 * FROM line_item_approval_report;` runs without error
- [ ] `SELECT category, month, monthly_allocation_usd FROM category_budgets ORDER BY category, month;` matches Finance's real 2026 figures
- [ ] `SELECT COUNT(*) FROM users;` returns `0` at this point — confirms no demo accounts leaked into production (real users come in Phase 8)
- [ ] `cashcall_app`'s effective permissions confirmed as least-privilege (data read/write + schema DDL for migrations only — not `db_owner`)

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| `alembic upgrade head` fails with a permissions error on `CREATE TABLE`/`CREATE VIEW` | `cashcall_app` only has `db_datareader`/`db_datawriter`, missing DDL rights | Grant the additional `CREATE TABLE, ALTER, CREATE VIEW` permissions shown in Step 3 (can be revoked after the initial migration if DPRP prefers the app's runtime login to be read/write-only going forward, re-granting temporarily for future migrations) |
| Connection refused / TLS handshake failure from the app or `alembic` | FreeTDS/`pymssql` encryption negotiation issue with Azure SQL Database's enforced TLS | Try appending `?tds_version=7.4` to `DATABASE_URL`; confirm outbound 1433 isn't blocked by an NSG between the VM and the database's private endpoint |
| `CREATE VIEW` fails when a DBA runs the generated `.sql` file manually | The file was executed as one block by a tool that doesn't understand `GO` batch separators (e.g. piped into a raw DBAPI connection) | Run it through `sqlcmd -i cashcall_schema.sql` or open it in Azure Data Studio/SSMS, both of which split on `GO` correctly |

---

## Phase 4 — Application Deployment (Docker, Environment Variables, Secrets)

**Objective:** Run the containerized application on the VM, pointed at Azure SQL Database, with production secrets sourced securely.

### Steps

1. **Provision Azure Key Vault** for production secrets:
   ```bash
   az keyvault create --resource-group rg-cashcall-prod --name kv-cashcall-prod --location eastus
   az keyvault secret set --vault-name kv-cashcall-prod --name SECRET-KEY --value "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
   az keyvault secret set --vault-name kv-cashcall-prod --name DATABASE-URL --value "mssql+pymssql://cashcall_app:<password>@sql-cashcall-prod.database.windows.net:1433/cashcall"
   az keyvault secret set --vault-name kv-cashcall-prod --name AZURE-CLIENT-SECRET --value "<from Phase 5>"
   az keyvault secret set --vault-name kv-cashcall-prod --name SMTP-PASSWORD --value "<DPRP mail relay credential>"
   ```
   **Never reuse the `SECRET_KEY` value captured from Render** — generate a fresh one; it signs session cookies.

2. **Build the production `.env` on the VM** (pull secret values from Key Vault at deploy time, or paste manually for the initial cutover and rotate to a Key Vault-backed fetch afterward):
   ```bash
   cat > /opt/cashcall/.env <<'EOF'
   APP_ENV=production
   SECRET_KEY=<from Key Vault>
   APP_TITLE=DPRP Cash Call Automation System
   DATABASE_URL=<from Key Vault>
   AZURE_CLIENT_ID=<from Phase 5>
   AZURE_CLIENT_SECRET=<from Key Vault>
   AZURE_TENANT_ID=<DPRP Entra ID tenant ID>
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
   `SEED_DB=false` is critical — leaving it `true` re-runs `scripts/seed.py` (demo data) on every container restart, the exact bug that wiped this app's audit trail earlier in its life on Render.

3. **Remove the containerized database from `docker-compose.prod.yml`.** As committed, this file also defines a `db` service — Azure SQL Database replaces it entirely, so remove that service block and the `app` service's dependency on it. Maintain this as a DPRP-specific overlay (e.g. `docker-compose.azure.yml`) rather than destructively editing the shared repo file, so local/Postgres-based dev setups elsewhere still work unchanged:
   ```yaml
   # docker-compose.azure.yml — overlay used only on the DPRP VM
   services:
     app:
       environment:
         APP_ENV: production
         DEV_BYPASS_ENABLED: "false"
         # DATABASE_URL comes from .env / Key Vault — do not override it here
       # no depends_on: db — there is no local db container in this deployment

     nginx:
       # unchanged — still fronts the app container with TLS as configured
   ```
   Delete the entire `db:` service block and its `postgres_data` volume from the copy of `docker-compose.prod.yml` used on this VM (or write the overlay above without them; either approach works, the overlay pattern keeps intent clearer for future maintainers).

4. **Build and start the stack:**
   ```bash
   cd /opt/cashcall
   docker compose -f docker-compose.yml -f docker-compose.azure.yml up -d --build
   ```
   `entrypoint.sh` runs automatically on container start: `alembic upgrade head` (idempotent, safe to re-run), then — since `SEED_DB=false` — skips seeding, then starts `uvicorn`.

5. **Tail logs to confirm a clean boot:**
   ```bash
   docker compose logs -f app
   ```
   Expect `[entrypoint] Running Alembic migrations…` → no pending migrations → `[entrypoint] Starting uvicorn…` with no tracebacks.

### Verification Checklist

- [ ] `docker compose ps` shows `app` and `nginx` containers `healthy`/`running` (no `db` container — Azure SQL Database is external)
- [ ] `curl -sk https://cashcall.dprp.dangote.com/health` (from inside the network) returns `{"status":"ok","env":"production"}`
- [ ] `/opt/cashcall/.env` has permissions `600` and is **not** committed to git (confirm `.env` is in `.gitignore`)
- [ ] `docker compose logs app` shows the Alembic step completing with no errors and no seed step running
- [ ] `curl -sk https://cashcall.dprp.dangote.com/docs` returns `404` (API docs are disabled automatically when `APP_ENV=production`)

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| `/health` times out or connection refused | App container can't reach Azure SQL Database's private endpoint (NSG blocking port 1433 between the app subnet and DB subnet) | Add an NSG rule allowing the app VM's subnet → Azure SQL Database on 1433 |
| App container restarts in a crash loop | Missing/malformed `DATABASE_URL` or `SECRET_KEY` in `.env` | `docker compose logs app` shows the exact exception; re-check `.env` values against Phase 3, Step 4's format |
| Build fails trying to compile a SQL Server driver from source | Someone reverted the `requirements.txt` change and reintroduced `pyodbc` without also adding the ODBC driver install steps to the `Dockerfile` | Confirm `requirements.txt` still specifies `pymssql==2.3.13` (already changed in this repo) — it needs no OS-level driver install, unlike `pyodbc` |

---

## Phase 5 — Microsoft Entra ID (Azure AD) SSO Configuration

**Objective:** Register the application in DPRP's Entra ID tenant, restrict sign-in to DPRP accounts only, and understand the app's (deliberate) requirement that every SSO user must also exist as a pre-provisioned local record.

### Steps

1. **Register the app** in Azure Portal → **Microsoft Entra ID → App registrations → New registration**:
   - Name: `DPRP Cash Call`
   - Supported account types: **"Accounts in this organizational directory only (DPRP only – Single tenant)"** — the primary control keeping non-DPRP Microsoft accounts out at the Entra ID layer, before the request even reaches the app.
   - Redirect URI: platform = **Web**, URI = `https://cashcall.dprp.dangote.com/auth/callback` — must be an **exact** string match to `AZURE_REDIRECT_URI`.

2. **Create a client secret**: App registration → Certificates & secrets → New client secret → copy the value immediately → store as `AZURE-CLIENT-SECRET` in Key Vault (Phase 4, Step 1).

3. **Grant API permissions**: App registration → API permissions → Add a permission → Microsoft Graph → Delegated permissions → `User.Read` (matches `_SCOPES = ["User.Read"]` in `app/services/auth_service.py` — the app requests no other Graph scope). Click **Grant admin consent for DPRP**.

4. **Record the two identifiers**: Application (client) ID → `AZURE_CLIENT_ID`; Directory (tenant) ID → `AZURE_TENANT_ID`.

5. **Update the VM's `.env`** and restart:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.azure.yml restart app
   ```

6. **Understand the app's login model before provisioning anyone** (this affects Phase 8 directly): Entra ID only confirms *identity*. The app does **not** auto-provision a user record from a successful sign-in — `handle_auth_callback()` in `app/services/auth_service.py` looks up a `User` row by the exact email from the identity claims, and rejects the login (`/login?error=auth_failed`) if no matching **active** local record exists. Every real person needs an Admin-created account (Phase 8) with an email that exactly matches their Entra ID UPN **before** their first SSO login will succeed.

7. **Confirm `ALLOWED_EMAIL_DOMAINS=dangote.com`** is set — a second, app-level check applied to every sign-in, independent of Step 1's tenant restriction, so a guest account added to the DPRP tenant from an external company still cannot log in even if Entra ID authenticates it successfully.

### Verification Checklist

- [ ] App registration shows **Single tenant** support type
- [ ] Redirect URI in Azure matches `AZURE_REDIRECT_URI` exactly
- [ ] Admin consent granted for `User.Read`
- [ ] A pre-provisioned pilot user (exists in both Entra ID and the app's `users` table) can complete `/login/microsoft` → lands on `/dashboard`
- [ ] A user who exists in Entra ID but has **no** matching local record is correctly bounced to `/login?error=auth_failed`

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| `AADSTS50011: The redirect URI ... does not match` | Redirect URI mismatch | Compare character-for-character, including `https://` and no trailing slash |
| User authenticates at Microsoft's login page successfully but bounces back to `/login?error=auth_failed` | No matching local `users` row, row is `is_active=False`, or email fails `ALLOWED_EMAIL_DOMAINS` | Verify the exact UPN in Entra ID (Users → search) matches the `email` column in the app's `users` table |
| SSO can seemingly be bypassed with a password | `DEV_BYPASS_ENABLED` left `true` in production `.env` | Set explicitly to `false` and restart |

---

## Phase 6 — Network and Security Hardening

**Objective:** Apply the additional controls appropriate for running on DPRP's own infrastructure rather than a managed sandbox like Render.

### Steps

1. **Re-verify NSG scoping** now that the full stack is live — inbound 443 only from DPRP internal CIDR ranges, 22 only from the bastion.

2. **Confirm response security headers are active at both layers** (already present in code/config — verification only):
   ```bash
   curl -skI https://cashcall.dprp.dangote.com/ | grep -Ei "strict-transport|x-frame|x-content-type|referrer-policy|permissions-policy"
   ```

3. **Understand the rate limiter's scaling limit.** `app/main.py`'s `RateLimitMiddleware` caps each source IP at 120 requests/minute, in-process/per-container — not shared across replicas. Fine for a single-VM deployment; flag to DPRP's platform team as a future item if horizontal scaling is planned.

4. **Confirm `DEV_BYPASS_ENABLED=false` and API docs are disabled:**
   ```bash
   curl -sk -o /dev/null -w "%{http_code}\n" https://cashcall.dprp.dangote.com/docs        # expect 404
   curl -sk -o /dev/null -w "%{http_code}\n" https://cashcall.dprp.dangote.com/openapi.json # expect 404
   ```

5. **Confirm Azure SQL Database has no public network access** (if the private-endpoint path from Phase 3 was chosen) or a firewall scoped only to the app VM and, later, the Power BI gateway host.

6. **Enable automated OS patching** via Azure Update Manager on the VM, and establish a cadence for rebuilding the Docker image (`docker compose build --no-cache` + redeploy periodically to pick up base-image security patches — there's no CI/CD pipeline defined in this repo yet).

7. **Confirm Azure SQL Database's automated backup settings** (point-in-time restore is on by default for Azure SQL Database) match DPRP's data-retention policy, and document the restore procedure.

8. **Forward container logs to Azure Monitor** for centralized audit/troubleshooting.

### Verification Checklist

- [ ] `curl -I https://cashcall.dprp.dangote.com` from **outside** DPRP's network fails/times out
- [ ] Security headers present in the response
- [ ] `/docs` and `/openapi.json` return `404`
- [ ] Azure SQL Database firewall/private-endpoint configuration shows no public-access path
- [ ] A test point-in-time restore has been performed and validated at least once
- [ ] Container/application logs visible in Azure Monitor / Log Analytics

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| App reachable from outside the corporate network | VM was given a public IP, or an NSG rule is broader than intended | Remove the public IP (Phase 2 already avoids this); audit all NSG rules for `0.0.0.0/0` or `Internet` source tags |
| Legitimate internal users occasionally get `429 Too Many Requests` | Many users sharing one egress/NAT IP hit the 120 req/min-per-IP limit collectively | Raise `_RATE_LIMIT` in `app/main.py` for an internal-only deployment and redeploy |

---

## Phase 7 — Power BI Database Connection Setup

**Objective:** Give Power BI safe, read-only, least-privilege access to reporting data via the `line_item_approval_report` view, never via the application's own database credentials.

### Steps

1. **Create a dedicated read-only SQL Server login:**
   ```sql
   CREATE LOGIN powerbi_reader WITH PASSWORD = '<generate-and-store-in-key-vault>';
   -- in the cashcall database:
   CREATE USER powerbi_reader FOR LOGIN powerbi_reader;
   GRANT SELECT ON line_item_approval_report TO powerbi_reader;
   GRANT SELECT ON category_budgets TO powerbi_reader;
   -- Deliberately NOT granted: users, audit_log, submissions, line_items directly.
   ```

2. **Provide connectivity for Power BI.** Power BI's **native SQL Server connector** is mature and works directly against Azure SQL Database. If a private endpoint was used (Phase 3), Power BI Service needs a path in: either an **on-premises data gateway** installed on a DPRP-network machine with connectivity to the private endpoint, or Power BI's **VNet data gateway** (a newer, Microsoft-managed alternative that avoids running your own gateway VM, if DPRP's Power BI licensing tier supports it). If instead a firewalled public endpoint was chosen, Power BI Service can connect directly once its documented service IP ranges (or "Allow Azure services" toggle) are permitted through the SQL Database firewall — no gateway needed, at the cost of a (locked-down) public exposure.

3. **Connect from Power BI Desktop**: Get Data → **SQL Server database** → Server = `sql-cashcall-prod.database.windows.net` → Database = `cashcall` → credentials = `powerbi_reader` (Database authentication). Choose **Import** mode for scheduled refresh, or **DirectQuery** for near-real-time at a query-performance cost.

4. **Build reports against:**
   - `line_item_approval_report` — one flattened row per line item, with per-stage decision timestamps, for approval turnaround, rejected-vendor analysis, deferred-invoice tracking, monthly trends, and bottleneck identification.
   - `category_budgets` — allocation vs. `approved_mtd`/`paid_mtd`/`deferred_approved` per category, for budget-utilization dashboards.

5. **Publish and schedule refresh** in the Power BI Service via the gateway (if used) — e.g. daily at 06:00. Since DPRP has **Power Automate** licenses available, an optional enhancement here (not required for baseline reporting) is a Power Automate flow that posts a Teams/email alert when a scheduled refresh fails, rather than relying on someone noticing a stale report.

### Verification Checklist

- [ ] `powerbi_reader` can `SELECT` from `line_item_approval_report` and `category_budgets`, and **cannot** read `users`, `audit_log`, `submissions`, or `line_items` directly, or write anywhere
- [ ] Power BI successfully connects (directly, or via gateway if a private endpoint is used)
- [ ] A test report built against both objects renders correctly
- [ ] A scheduled refresh has completed successfully at least once

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| Power BI Service refresh fails: "cannot reach data source" | Gateway not installed/registered (private endpoint path), or firewall doesn't allow Power BI (public endpoint path) | Confirm gateway status in the admin portal, or confirm the firewall rule/"Allow Azure services" toggle |
| Login fails with an authentication error in Power BI | Connector defaulted to Windows/Entra ID auth instead of SQL login | Explicitly select **Database** authentication and supply the `powerbi_reader` SQL login credentials |
| Reports show stale or duplicate turnaround numbers | Report built against raw `audit_log` joins instead of `line_item_approval_report` | Rebuild against the view — it exists specifically to avoid hand-written joins |

---

## Phase 8 — User Provisioning and Role Assignment

**Objective:** Get every real DPRP staff member into the application with the correct role, department, and an email that exactly matches their Entra ID account.

### Steps

1. **Compile the real roster** with DPRP HR/department heads: for every department, at minimum **1 HOD + 2 Originators** (so a backup can raise requests when the primary is on leave), plus at least one each of Finance Reviewer, CFO, CEO, Treasury, and IT Admin.

2. **Bootstrap the first IT Admin account** directly (no public self-signup exists by design):
   ```bash
   docker compose exec app python3 -c "
   from app.database import SessionLocal
   from app.models.user import User
   import bcrypt
   db = SessionLocal()
   db.add(User(
       email='firstname.lastname@dangote.com',   # must match this person's real Entra ID UPN
       display_name='Firstname Lastname',
       role='it_admin',
       is_active=True,
       hashed_password=bcrypt.hashpw(b'temporary-unused-value', bcrypt.gensalt()).decode(),
   ))
   db.commit()
   "
   ```
   The `hashed_password` value is never actually usable for login once `DEV_BYPASS_ENABLED=false` — it exists only because the column is currently required by the admin form for new users.

3. **Provision everyone else through Admin → Users** (`https://cashcall.dprp.dangote.com/admin/users/new`) once the first IT Admin can log in via SSO — email must be the exact Entra ID UPN, department is required for `originator`/`hod` (the admin form does not currently hard-block a blank department for these roles, so verify manually).

4. **For bulk onboarding**, script it the same way as Step 2 in a loop over the real roster, rather than clicking through the UI dozens of times. Do **not** run `scripts/seed.py` in production.

5. **Deactivate or delete any leftover demo/test accounts** before go-live.

### Verification Checklist

- [ ] Every real department has ≥1 active HOD and ≥2 active Originators
- [ ] At least one active account exists for each of: Finance Reviewer, CFO, CEO, Treasury, IT Admin
- [ ] 3–5 spot-check users can each complete SSO login and land on the dashboard matching their role
- [ ] No demo/seed accounts remain active
- [ ] Every provisioned email was confirmed against DPRP's Entra ID user list, not guessed

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| A specific user can never log in, others work fine | Their `email` in the app doesn't exactly match their Entra ID UPN | Look the person up directly in Entra ID → Users, copy their UPN verbatim, update the app record |
| Originator can't select their department when raising a submission | Department left blank at provisioning time | Edit the user record in Admin → Users and set the correct department |

---

## Phase 9 — UAT and Go-Live Validation

**Objective:** Prove the complete approval pipeline, notifications, budgets, audit trail, and reporting all work correctly with real people, before cutting over fully.

### Steps

1. **Run a full pilot submission** through the entire pipeline with 3–5 real pilot users: Originator creates → HOD (exercise Approve, Reject, Defer, and Request Clarification across different line items) → Finance QC → CFO (exercise the month-deferral action specifically) → CEO → Treasury marks paid.

2. **Verify budget figures** in `Admin → Budgets` update correctly at each stage.

3. **Verify email notifications actually arrive** in real inboxes — confirm with DPRP's messaging/M365 administrators that the app's SMTP service account is permitted to relay mail. (Since DPRP has Power Automate available, note this as a future alternative channel if the SMTP relay path proves troublesome operationally — not required for this go-live.)

4. **Verify the audit trail** (`Admin → Audit`) shows accurate approver, stage, timestamp, previous status, and new status entries.

5. **Verify Power BI reflects the pilot data** after a manual refresh.

6. **Sanity-check the rate limiter** under realistic traffic — watch for `429` responses if many users share a corporate NAT egress IP.

7. **Monitor Azure SQL Database DTU/vCore utilization** during the pilot to confirm the chosen service tier (`S1`, Phase 3) is adequate before scaling the pilot to full rollout.

8. **Plan the DNS/URL cutover communication** to users still bookmarking the old Render URL.

9. **Hold a go/no-go review** with business stakeholders.

10. **Decommission Render only after a safety window** — pause (don't delete) for at least 2 weeks post-go-live.

### Verification Checklist

- [ ] Full pilot submission completes the entire five-stage pipeline with correct final per-item statuses
- [ ] Budget totals match expected arithmetic after the pilot
- [ ] Pilot users confirm receipt of expected email notifications
- [ ] Audit trail for the pilot submission is complete and accurate
- [ ] Power BI report reflects pilot data after a manual refresh
- [ ] No unexpected `429` rate-limit responses during pilot usage
- [ ] Azure SQL Database utilization stayed comfortably within the provisioned tier during pilot load
- [ ] Stakeholder go/no-go sign-off obtained and documented
- [ ] Render service paused (not deleted) as a rollback safety net

### Known Failure Modes

| Symptom | Cause | Resolution |
|---|---|---|
| Emails never arrive despite the app logging "Email sent" | Corporate mail flow rules blocking the service account as an unrecognized relay | Escalate to DPRP messaging admins to allowlist the service account for SMTP AUTH relay |
| Some pilot users report random logouts mid-pilot | `SECRET_KEY` changed between deploys (invalidating session cookies), or `SESSION_MAX_AGE_SECONDS` expired | Confirm `SECRET_KEY` is fixed in Key Vault, not regenerated on each deploy |
| Go-live delayed because a department has no provisioned Originator | Roster gap missed in Phase 8 | Treat Phase 8's department cross-check as a hard gate before scheduling the go/no-go review |
