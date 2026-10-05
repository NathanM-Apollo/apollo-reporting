# Apollo Reports: Information Package

**Purpose:** Automated daily and weekly financial and clinical reports emailed to Apollo leadership and displayed on the Apollo reporting portal (Static Web App).

**Owner (as of handoff):** Nathan Maziar
**Codebase:** Python 3.11 on Azure Functions (Linux)

---

## 1. What This System Does

Four report jobs run on schedules across two function apps.

| Report | Function App | Schedule | Delivery |
|---|---|---|---|
| Daily Financial (Revenue + AR) | `apollo-financial-reports-func` | Weekdays 7:30 AM ET | Email + Portal |
| Weekly Supervision | `apollo-supervision-func` | Mondays 8:00 AM ET | Email + Portal |
| Weekly Parent Training | `apollo-supervision-func` | Mondays 8:30 AM ET | Email + Portal |
| Client & Insurance Roster | `apollo-supervision-func` | Weekdays 9:00 AM ET | Portal only (no email) |

Supervision, Parent Training, and the Client & Insurance Roster run inside the same function app as three separate timer-triggered functions. They share the billing input, the clinic mapping, and the initials code, so keeping them together avoids duplicate setup. Each function has its own schedule in its own `function.json`, so the roster runs every weekday while Supervision and Parent Training run only on Mondays. A bad deploy to this app affects all three.

Source data for all reports: CentralReach CSV exports uploaded to Azure Blob Storage.

---

## 2. Azure Resources

**Subscription:** `a867f16c-a3fa-49f1-947e-a1e364b73ddf`

### Resource groups

- **`apollo-reports-rg`** (East US): function apps, storage, App Insights
- **`labor-util-rg`** (East US): App Service Plan hosting the function apps
- **`apollo-reporting-rg`** (East US): Static Web App

### Storage

- **Account:** `apolloreportsstorage`
- **Container:** `apollo-reports`
- **Layout:**
  ```
  apollo-reports/
    inputs/
      billing/*.csv                       ← all functions read here
      receivables/*Receivables*.csv       ← financial only
    config/
      clinics.csv                         ← clinic → address mapping
    outputs/
      revenue/{YYYY-MM-DD}/*.xlsx
      ar/{YYYY-MM-DD}/*.xlsx
      supervision/{YYYY-MM-DD}/*.xlsx
      parent-training/{YYYY-MM-DD}/*.xlsx
    snapshots/
      ar/{YYYY-MM-DD}.json                ← historical AR portfolio metrics (financial only)
      revenue/{YYYY-MM-DD}.json
  ```

The Static Web App reads from `outputs/{report}/{date}/*.xlsx`, it picks the newest date folder for each report type.

### Function apps

**`apollo-financial-reports-func`**
- Plan: `labor-util-plan` (B1 Basic Linux, in `labor-util-rg`)
- Runtime: Python 3.11
- Function inside: `financial-daily` (cron `0 30 7 * * 1-5`, weekdays 7:30 AM ET)
- Downloads billing + receivables CSVs → builds Revenue + AR XLSX → emails → archives to blob → writes snapshots

**`apollo-supervision-func`**
- Plan: `labor-util-plan` (same B1)
- Runtime: Python 3.11
- Three functions inside:
  - `supervision-weekly` (cron `0 0 8 * * 1`, Monday 8:00 AM ET)
  - `parent-training-weekly` (cron `0 30 8 * * 1`, Monday 8:30 AM ET)
  - `client-roster-weekly` (cron `0 0 9 * * 1-5`, weekdays 9:00 AM ET). The folder name says "weekly" but it runs every weekday. It writes to blob only and sends no report email; a failure notice goes to `CLIENT_ROSTER_ERROR_RECIPIENTS` (defaults to Nathan).
- The three are staggered 30 minutes apart on Mondays so they don't compete for memory. None depends on another.

### Other function apps (not part of this system)

- `BCBA-billing-func`, `labor-util-func`, `labor-util-func-b1` in `labor-util-rg`
- `apollo-tpf-api` in `rg-apollo-tpf`

### Static Web App

- **Name:** `apollo-reporting`
- **URL:** `https://black-tree-0b4b5461e.7.azurestaticapps.net`
- **GitHub repo:** `https://github.com/NathanM-Apollo/apollo-reporting` (main branch, auto-deploys via GitHub Actions)
- **Access roles:** `apollo_et` (all reports), `apollo_rcm` (AR, Revenue, and Client & Insurance Roster), `apollo_cd_<clinic>` (clinic-scoped views, rows filtered to their clinic)

---

## 3. Secrets & Credentials

Managed via Function App **Application Settings** (Portal → Function App → Environment variables → App settings).

### Financial function (`apollo-financial-reports-func`)

| Setting | Purpose |
|---|---|
| `AzureWebJobsStorage` | Connection string for `apolloreportsstorage` |
| `BLOB_CONTAINER` | `apollo-reports` |
| `GMAIL_USER` | `reports@apollobehavior.com` |
| `GMAIL_APP_PASSWORD` | Gmail app password (NOT account password) |
| `FINANCIAL_RECIPIENTS` | JSON array of emails |
| `FINANCIAL_ERROR_RECIPIENTS` | JSON array for failure notifications |
| `WEBSITE_TIME_ZONE` | `America/New_York` (Linux IANA format required) |
| `FUNCTIONS_EXTENSION_VERSION` | `~4` |
| `FUNCTIONS_WORKER_RUNTIME` | `python` |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` |
| `ENABLE_ORYX_BUILD` | `true` |

### Supervision + Parent Training function (`apollo-supervision-func`)

Same base settings plus:
- `SUPERVISION_RECIPIENTS` / `SUPERVISION_ERROR_RECIPIENTS`
- `PARENT_TRAINING_RECIPIENTS` / `PARENT_TRAINING_ERROR_RECIPIENTS`
- `CLIENT_ROSTER_ERROR_RECIPIENTS` (optional; failure notices only, defaults to Nathan if not set)

The three functions share storage and Gmail credentials and have their own recipient settings.

### Gmail App Password

The `reports@apollobehavior.com` Google Workspace account has an App Password provisioned in Google Account → Security → App Passwords. If revoked, generate a new one and update `GMAIL_APP_PASSWORD` on both function apps.

**Rotation:** Gmail App Password is the primary secret. Storage account keys have been exposed multiple times during development, rotate at Portal → apolloreportsstorage → Access keys.

---

## 4. Code Structure

### `apollo-financial-reports-func` deploy zip

```
host.json
requirements.txt
xlsxwriter/                     ← VENDORED xlsxwriter package
shared/
  __init__.py
  blob_io.py                    ← download_inputs, upload_output, snapshot helpers
  gmail_sender.py               ← send_with_attachment
financial-daily/
  __init__.py                   ← orchestrator
  build_revenue.py              ← ~800 lines, Revenue XLSX
  build_ar.py                   ← ~1200 lines, AR XLSX
  function.json
```

### `apollo-supervision-func` deploy zip

```
host.json
requirements.txt
xlsxwriter/                     ← VENDORED xlsxwriter package
shared/
  __init__.py
  blob_io.py
  gmail_sender.py
supervision-weekly/
  __init__.py
  build_supervision.py          ← ~515 lines
  function.json
parent-training-weekly/
  __init__.py                   ← similar orchestrator, no snapshot logic
  build_parent_training.py      ← ~570 lines
  function.json
client-roster-weekly/
  __init__.py                   ← orchestrator, blob upload only, no report email
  build_client_roster.py        ← ~390 lines
  function.json                 ← weekdays 9:00 AM ET
```

### Static Web App repo

```
prod/
  api/
    report/                     ← serves individual report XLSX
    reports/                    ← lists available reports
    shared/
      access.py                 ← REPORT_CATALOG + role gating
      xlsx_parser.py            ← XLSX → JSON conversion
  web/
    index.html                  ← ~889 lines, React (compiled) + display logic
    staticwebapp.config.json
.github/workflows/
  azure-static-web-apps.yml     ← auto-deploy on push to main
```

### Why xlsxwriter is vendored

`xlsxwriter` used to be in `requirements.txt`, but the Oryx build system on B1 intermittently hangs for 20-30 minutes when resolving that dependency. Vendoring the package bypasses pip resolution entirely.

The build scripts include this snippet to make the vendored folder importable:

```python
_WWWROOT = '/home/site/wwwroot'
if os.path.isdir(_WWWROOT) and _WWWROOT not in sys.path:
    sys.path.insert(0, _WWWROOT)
import xlsxwriter
```

### Orchestrator pattern

Every function follows the same pattern in `__init__.py`:

1. Read `today` from `datetime.now()` (respects `WEBSITE_TIME_ZONE`)
2. Set `APOLLO_REPORT_DATE` env var so build scripts embed date in filenames
3. Download inputs into a `TemporaryDirectory`
4. Run the build script as a **subprocess** (memory isolation)
5. Read stdout/stderr; on non-zero return code, raise RuntimeError with full stderr
6. Email the output XLSX
7. Archive output to blob at `outputs/{report}/{date}/`
8. Write snapshot (financial only)
9. On any exception, send failure email to `_ERROR_RECIPIENTS` with full traceback

Subprocess isolation is important on B1, pandas building 1M+ row DataFrames can exhaust memory in the orchestrator process. Running the build in a child process ensures memory is released between build and email steps.

---

## 5. Data Flow

### Financial (daily)

```
CSV uploads → blob → function reads → pandas processes →
xlsxwriter builds XLSX → Gmail sends → blob archives → snapshot writes → SWA displays
```

Input files matched by pattern:
- Billing: `*.csv`
- Receivables: `*Receivables*.csv` (STRICT, must contain "Receivables")

### Supervision + Parent Training (weekly)

```
CSV uploads → blob → each function reads → filter to 2026+ →
apply clinic mapping (from config/clinics.csv) → compute ratios → 
build XLSX → Gmail sends → blob archives → SWA displays
```

Both filtered to 2026+ only. Supervision uses 97153/97154/97155. Parent training uses 97153/97154/97156.

Monthly columns on both reports show the trailing 12 months, newest month first, never earlier than Jan-2026. Once the calendar passes Jan-2027, the oldest month drops off each month to keep 12.

### Client & Insurance Roster (weekdays)

```
CSV uploads → blob → function reads billing → L30 window → payor and site per client →
build XLSX → blob archives → SWA displays
```

Reads the same billing files as every other report. Does not use receivables. Not filtered to 2026+, since it only looks at the last 30 days.

Clinics with zero activity in the filtered data are automatically hidden from the summary tab of both reports (strict filter). They stay listed in the Clinic Mapping reference tab.

---

## 6. The Clinic Mapping File

`apollo-reports/config/clinics.csv`, controls which addresses map to which clinics.

```csv
StreetNumber,ClinicName,FullAddress
3162,Acworth,3162 Acworth Forest Dr NW
1360,Athens,1360 Caduceus Way
...
```

**Matching rule:** the leading digits of `ServiceLocationAddressLine1` in the billing CSV are matched against `StreetNumber`. Matched → clinic name. Unmatched → "Unmapped".

To add or update a clinic, edit this CSV in Excel and upload back to blob. Both supervision and parent training re-read it on every run.

Multiple StreetNumber rows can share a ClinicName (useful during clinic relocations, sessions at either address roll up).

**Fallback:** if the blob file is unreachable, the build scripts fall back to a hardcoded baseline. Update both places if the canonical list changes structurally.

---

## 7. Static Web App Integration

### How new reports appear on the portal

The SWA has a report catalog in `prod/api/shared/access.py`:

```python
REPORT_CATALOG = {
    "ar":              {"title": "Accounts Receivable", "scope": "all", "folder": "outputs/ar"},
    "rev":             {"title": "Daily Revenue",       "scope": "all", "folder": "outputs/revenue"},
    "supervision":     {"title": "Supervision Ratio",   "scope": "all", "folder": "outputs/supervision"},
    "bcba":            {"title": "BCBA Billing",        "scope": "all", "folder": "outputs/bcba-billing"},
    "direct-labor-margin": {"title": "Direct Labor Margin", "scope": "all", "folder": "outputs/direct-labor-margin"},
    "parent-training": {"title": "Parent Training",     "scope": "all", "folder": "outputs/parent-training"},
    "client-roster":   {"title": "Client & Insurance Roster", "scope": "all", "folder": "outputs/client-roster"},
}
```

Each entry maps a short key → title, scope, and blob folder. Adding a new report is a one-line change here + `git push`. The catalog may also list reports added in other work (for example group-rate, turnover); check the live file before editing.

Group access is set in the same file. `apollo_et` sees every report. `apollo_rcm` sees `ar`, `rev`, and `client-roster`.

### How the SWA displays the report

`prod/api/shared/xlsx_parser.py` reads the XLSX the function produced, converts each tab to JSON (headers, rows, values), and serves it to the frontend. The frontend (`prod/web/index.html`) renders it as HTML tables with tabs.

### Number formatting heuristic: the "hrs" workaround

The frontend uses value-based heuristics to classify columns as percentages, currency, or plain numbers. This works for most reports but broke for parent training: values under 1.0 were misclassified as percentages (`0.46` displayed as `46%`).

**Workaround:** parent training column headers include "hrs" (e.g., "Jan-26 hrs", "L7 × 4 hrs"). The frontend classifier has a one-line rule: if the header contains "hrs" or "hours", treat as plain number and skip the fractional-percent heuristic.

This lives in `prod/web/index.html` around line 55, in the `classifyColumn` function. If you're adding a new report with fractional hour-like values, use "hrs" in the header names too, or add another opt-out rule.

Current rule order in `classifyColumn` (order matters; the first match wins):

```javascript
if (/\bhrs?\b|\bhours?\b/.test(h)) return "num";       // hours columns
if (/units|sessions|count|#/.test(h)) return "int";        // count columns
if (/revenue|\brev\b|\bar\b|amount|collected|receivabl|outstanding|gross|net|balance|charges/.test(h)) return "usd";
if (/^l\d+\b/.test(h)) {                                 // L7/L30/L90 columns default to percent
  if (/\$|\/day/.test(h)) return "usd";
  return "pct";
}
```

The L-column percent rule was added for Direct Labor Margin. Any new report with a column header that starts with L7/L30/L90 will show as a percent unless its header also matches one of the rules above it.

### Charts on the portal

The portal draws its own charts (Recharts) from the chart definitions inside each XLSX. Recharts doesn't do 100%-stacked math, so `buildChartData` in `index.html` converts each row to fractions of the row total when a chart's grouping is `percentStacked`. Without that, the Revenue "Monthly Revenue Mix (100% Stacked)" chart draws as a single color.

**Long-term fix (not implemented):** the parser could pass through the XLSX's actual `number_format` string to the frontend, which could then respect it explicitly instead of guessing. Cleaner but requires touching both parser and frontend.

---

## 8. Deploy Mechanics

### Function app deploys

Use `az webapp deploy --type zip`. Two known issues:

1. **CLI returns 504/502 quickly**: expected. Deploy usually completes server-side. Check via `az webapp log deployment list`.

2. **Oryx build hangs**: deploy status shows `Complete: False, Status: 1` with last log entry stuck at "Running oryx build..." for 20+ min. Recovery: restart the function app to break the hang, then retry. Sometimes takes 2-3 attempts. Extreme cases can leave wwwroot partially wiped, a clean redeploy recovers.

### Static Web App deploys

Automatic via GitHub Actions. Push to `main` on `NathanM-Apollo/apollo-reporting`, SWA rebuilds within 2-3 min.

### Rollback

Every function app deploy zip is in Cloud Shell home directory (`~/apollo-*-deploy-vN.zip`). These zips are the only copy of the function app source. Build every change on the newest known-good zip.

Known-good baselines as of 10/5/2026:
- `apollo-reports-deploy-v11.zip`: financial-daily. This is v6 (the version that ran through 9/15/2026) with one change, the T: prefix fix in both build scripts.
- `apollo-supervision-deploy-v10.zip`: supervision + parent training (months newest first, trailing 12) + client roster

Do not use `apollo-reports-deploy-v7.zip` through `v10.zip`. They were built from stale copies of the build scripts (see Known Issues) and are missing the AR trend history and the xlsxwriter charts.

SWA rollback is `git revert` in the repo.

---

## 9. Design Decisions Worth Preserving

**Two weekly reports in one function app.** Supervision and parent training share ~90% of their code. Co-located = one deploy pipeline, one restart if something goes wrong. Trade-off: a bad deploy affects both.

**One shared blob container across all functions.** Upload once, everyone reads.

**Subprocess isolation for build scripts.** B1 memory is 1.75 GB; pandas can eat that. Subprocess ensures orchestrator memory is released between build and email steps.

**Snapshots for AR trend tabs.** Historical portfolio metrics stored one-JSON-per-day in blob. Losing them resets trends to today only.

**xlsxwriter over openpyxl.** Original scripts used openpyxl but its charts render broken. Full rewrite to xlsxwriter fixed all charts. Do not revert.

**Gmail SMTP with App Password.** Simple, no OAuth refresh, no service account. Trade-off: subject to whatever Google decides about App Passwords.

**Recipients as JSON array in app settings.** Add/remove without a deploy.

**Clinic mapping in a blob CSV.** Edit in Excel, no code deploy. Both weekly scripts re-read on every run.

**Static Web App reads XLSX directly from blob.** No separate JSON schema to maintain. Trade-off: SWA has to parse Excel, and heuristic classification can misfire.

**Parent training headers include "hrs".** Ugly but explicit. Fixes SWA classifier misfire without breaking supervision's percentages.

**Strict clinic filter on summary tabs.** Clinics with zero activity in 2026+ data are dropped from summary rows. Reference tab keeps the canonical list.

**T: prefix stripped like P: and S:.** Tertiary claims in billing carry a `T:` prefix (always `T: Georgia Medicaid: DXC Technology` as of 9/30/2026, 63 billing lines). The payor grouping strips it so those claims land under Georgia Medicaid (DXC) instead of a stray "T" payor.

**Supervision and Parent Training months: newest first, trailing 12.** Requested 9/20/2026. Never back-filled before Jan-2026.

**Client & Insurance Roster lives in the supervision function app on its own weekday schedule.** Same inputs and helpers as the other two; no report email.

---

## 10. Known Issues / Watch Items

**Oryx build hangs.** ~50% of B1 deploys hang for 20+ min. Restart the function app to release. Extreme cases have left wwwroot partially wiped, clean redeploy recovers.

**ARM listKeys timeouts.** Occasional slow-downs of Azure management plane. Blocks manual triggers via curl but doesn't affect scheduled runs.

**Deprecated basic auth on Kudu.** Log streaming via `curl -u user:pass https://*.scm.azurewebsites.net/api/logstream/*` doesn't reliably work. Use Application Insights query in Portal for logs.

**File naming discipline for receivables.** Any receivables CSV must contain "Receivables" in the filename. If missing, AR reports silently exclude that file's data.

**Deploy zip requires xlsxwriter folder at root.** If a deploy zip is built without vendored `xlsxwriter/`, build scripts fail with `ModuleNotFoundError`. Verify with `unzip -l ~/deploy.zip | grep -c xlsxwriter` before deploying (expect 43).

**SWA classifier heuristic.** Fragile value-based percent/currency detection. Adding a new report with unfamiliar column patterns may hit this, either match an existing opt-out (add "hrs" to headers) or extend the classifier in `prod/web/index.html`.

**Never pull code from the function app's file view.** The ARM/Kudu file view (`.../extensions/Vfs/site/wwwroot/...`) has shown stale or missing files on both function apps, while the apps were running newer code. On 9/16/2026 a one-line fix built on files pulled from that view replaced the running AR and revenue scripts with older versions. That removed the AR trend history and the xlsxwriter charts, and brought back an old revenue tab. It took until 9/30 to find and fix. Always start from the newest known-good deploy zip.

**Check any change against the previous report before calling it done.** Compare tabs, chart counts, column counts, and titles between a report from before the change and one from after. Only data-driven differences should show up. The 9/30 comparison script is a good template.

**No Git repository for function apps.** Python code is only in the deploy zips in Cloud Shell home. Losing Cloud Shell home loses the source. **Recommended next step: add function app source to Git.**

**AR trend history has no cutoff.** Aging Trend and DSO Trend load every saved daily snapshot back to 5/8/2026, adding about 250 rows a year. A trailing-12-month limit is planned for later; older snapshots would stay in storage.

**Storage account keys exposed in chat/logs.** Rotate periodically.

---

## 11. Costs

- App Service Plan (B1): ~$54/month for the whole plan (shared across function apps in labor-util-rg)
- Storage account: ~$5-10/month
- Application Insights: free tier
- Static Web App: free tier
- No per-execution costs (B1 is fixed-price)

Total marginal cost: ~$0 (plan already existed).
