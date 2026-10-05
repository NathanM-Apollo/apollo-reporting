# Apollo Reports: Troubleshooting

Things go wrong. Here's the playbook.

---

## Symptom: I didn't get the morning email

### Step 1: Confirm the function is running

```bash
# Financial
az functionapp show \
  --name apollo-financial-reports-func \
  --resource-group apollo-reports-rg \
  --query "state" -o tsv

# Supervision + Parent Training (same app)
az functionapp show \
  --name apollo-supervision-func \
  --resource-group apollo-reports-rg \
  --query "state" -o tsv
```

Expected: `Running`. If `Stopped`:
```bash
az functionapp start --name apollo-financial-reports-func --resource-group apollo-reports-rg
```

### Step 2: Confirm all functions are registered

For `apollo-supervision-func` (which houses supervision, parent training, and the client roster):

```bash
az functionapp function list \
  --name apollo-supervision-func \
  --resource-group apollo-reports-rg \
  --query "[].name" --output tsv
```

Expected:
```
apollo-supervision-func/client-roster-weekly
apollo-supervision-func/parent-training-weekly
apollo-supervision-func/supervision-weekly
```

If one is missing, the function host hasn't picked it up. This happens after failed deploys, and also right after a deploy that adds a new function folder (it happened when the client roster was added on 10/5/2026). Fix: restart:
```bash
az functionapp restart \
  --name apollo-supervision-func \
  --resource-group apollo-reports-rg
```

Wait 90 seconds, then re-check the list. If a function is still missing, redeploy the last good zip.

### Step 3: Confirm the schedule is correct

See Operations how-to, section 8.

### Step 4: Check if the function fired

```bash
SUB_ID=$(az account show --query id -o tsv)
az monitor metrics list \
  --resource "/subscriptions/$SUB_ID/resourceGroups/apollo-reports-rg/providers/Microsoft.Web/sites/apollo-supervision-func" \
  --metric "FunctionExecutionCount" \
  --interval PT5M \
  --start-time $(date -u -d '8 hours ago' +%Y-%m-%dT%H:%M:%SZ) \
  --query "value[0].timeseries[0].data[?total > \`0\`]" \
  --output table
```

- **Rows returned** → function fired. Likely email delivery issue (Step 5).
- **No rows** → didn't fire. Schedule/timezone issue or app stopped at fire time.

Note: this metric is app-level, so it counts both supervision AND parent training executions on `apollo-supervision-func`. If both fire at their scheduled times, expect two rows separated by 30 min on Monday morning.

### Step 5: Check for a failure email

If function fired but you got `[FAILED]` email, body includes error. If function fired and no email at all, email pipeline itself failed.

### Step 6: Look at Application Insights

Portal → function app → Application Insights → **Logs** → paste this KQL:

```kusto
traces 
| where timestamp > ago(4h)
| where severityLevel >= 2 or message contains "Error" or message contains "Traceback"
| order by timestamp desc
| take 50
```

Most recent error/traceback tells you what broke.

---

## Symptom: SWA shows values as % or $ when they should be plain numbers

**Cause:** the SWA frontend classifier uses value-based heuristics, if values are all between 0 and 1, it guesses "percent." Parent training's hour values under 1 hit this bug.

**Fix (already in place for parent training):** column headers contain "hrs", the classifier now recognizes this and returns "num" instead.

**If a NEW report hits this:**

Option A, add "hrs" to column headers in the build script:
```python
all_cols = [f'{m} hrs' for m in month_labels]
```

Option B, extend the classifier in `prod/web/index.html`. Around line 55, in `classifyColumn`, add an opt-out for your specific column pattern.

**The rule that fires the bug:**
```javascript
if (allBetween0and1 && someFractional && nums.length > 1) return "pct";
```

Any short-circuit before this line prevents misclassification.

---

## Symptom: SWA shows a stray "COLUMBUS" header/section-break and following row is broken

**Cause:** the SWA renders a clinic row unusually when all its cells are blank, and the next row's formatting gets corrupted.

**Fix (in place for both supervision and parent training):** the build scripts hide clinics with zero activity in the filtered data (strict filter). Columbus and other not-yet-open clinics never appear as rows on the summary tab.

If this recurs with a new clinic:
- Check the build script's clinic filter, should be near where `clinics_alphabetical` is defined
- Both scripts should look like:
  ```python
  _active_clinics = set(df['Clinic'].unique())
  clinics_alphabetical = sorted(
      c for c in set(CLINIC_MAP.values()) if c in _active_clinics
  )
  ```
- If missing, the SWA rendering artifact will recur

---

## Symptom: Deploy hangs at "Running oryx build..."

**Cause:** Oryx build system intermittently freezes on B1. Not caused by your changes.

**Recovery:**

```bash
# 1. Restart the function app to unstick Oryx
az functionapp restart \
  --name apollo-supervision-func \
  --resource-group apollo-reports-rg

# 2. Wait 90 seconds
sleep 90

# 3. Retry the same deploy
az webapp deploy \
  --resource-group apollo-reports-rg \
  --name apollo-supervision-func \
  --src-path ~/your-deploy.zip \
  --type zip \
  --timeout 600
```

If it hangs again, wait 2-3 min and try once more. Sometimes works on third attempt.

**Extreme case:** hangs have occasionally left `/home/site/wwwroot/` partially wiped (only `host.json` remaining). Function host still remembers functions in memory but they can't actually execute. Recovery is a clean redeploy of the same zip.

**Diagnostic to check disk state:**
```bash
SUB_ID=$(az account show --query id -o tsv)
az rest --method GET \
  --uri "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/apollo-reports-rg/providers/Microsoft.Web/sites/apollo-supervision-func/extensions/Vfs/site/wwwroot/?api-version=2022-03-01" \
  --query "[].name" -o tsv 2>&1
```

Should show `host.json`, `requirements.txt`, `shared`, `supervision-weekly`, `parent-training-weekly`, `xlsxwriter`. If missing folders, redeploy.

---

## Symptom: Deploy returns "504 Gateway Timeout" or "502 Bad Gateway"

**Expected.** CLI has a client-side timeout that fires before Azure's server-side completion signal. Deploy usually completes fine server-side.

**Check:**
```bash
sleep 60

az webapp log deployment list \
  --name apollo-supervision-func \
  --resource-group apollo-reports-rg \
  --query "[0].{complete:complete, status:status, end:end_time}" \
  --output table
```

- `Complete: True, Status: 4` → succeeded despite the 504
- `Complete: False, Status: 1` → still building
- `Complete: True, Status: 3` → failed; get full log:
  ```bash
  SUB_ID=$(az account show --query id -o tsv)
  DEPLOY_ID=$(az webapp log deployment list \
    --name apollo-supervision-func \
    --resource-group apollo-reports-rg \
    --query "[0].id" -o tsv)
  az rest --method GET \
    --uri "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/apollo-reports-rg/providers/Microsoft.Web/sites/apollo-supervision-func/deployments/$DEPLOY_ID/log?api-version=2022-03-01" \
    --query "value[*].properties.{time:log_time, msg:message}" \
    --output table 2>&1 | tail -30
  ```

---

## Symptom: Failed email says "ModuleNotFoundError: No module named 'xlsxwriter'"

Vendored xlsxwriter folder didn't land in the deploy zip, or sys.path fix isn't in the build script.

**Check the deploy zip:**
```bash
unzip -l ~/your-deploy.zip | grep -c "xlsxwriter/"
```
Expected: ~43. If 0, rebuild.

**Check the build script has the sys.path fix:**
```bash
unzip -p ~/your-deploy.zip supervision-weekly/build_supervision.py | head -30 | grep -A 3 "_WWWROOT"
```

Should show:
```python
_WWWROOT = '/home/site/wwwroot'
if os.path.isdir(_WWWROOT) and _WWWROOT not in sys.path:
    sys.path.insert(0, _WWWROOT)
import xlsxwriter
```

Same check for `build_parent_training.py`, `build_revenue.py`, `build_ar.py`.

If missing, add those 3 lines above `import xlsxwriter` and redeploy.

---

## Symptom: AR report has $62K total AR (way too small, mostly in 365+ bucket)

**Cause:** The receivables CSV in blob doesn't match `*Receivables*.csv`. Only old 2021-2024 residual data loads.

**Fix:** Rename the CSV in blob to contain "Receivables". See Operations how-to section 2.

---

## Symptom: Report missing data for a clinic

For supervision or parent training.

**Cause 1:** Address doesn't match street number in `config/clinics.csv`.

Check what addresses are showing up in billing:
- Download `config/clinics.csv` from blob
- Look at `ServiceLocationAddressLine1` in the billing data
- Confirm the leading digits match a StreetNumber row

**Fix:** Add or update the mapping. See Operations how-to section 3.

**Cause 2:** All sessions rolled into "Unmapped" (visible on report).

Same fix.

**Cause 3:** Clinic has zero activity in the filtered data and got auto-hidden by the strict filter (this is intended behavior).

Look at "Clinic Mapping" reference tab, if the clinic is listed there but not on the summary tab, it's been auto-hidden due to zero activity.

---

## Symptom: Failed email says "code 1" with no traceback

**Cause:** Orchestrator's error handler didn't capture build script's stderr. Should not happen on current code, all deploys since v3 (supervision) or v6 (financial) include STDERR capture.

**Diagnostic:**
```bash
unzip -p ~/latest-deploy.zip supervision-weekly/__init__.py | grep -A 2 "STDERR"
```

Should show:
```python
f'\n\nSTDERR:\n{result.stderr or "(empty)"}'
```

Same check for `parent-training-weekly/__init__.py`.

If missing, redeploy from a zip that has it.

---

## Symptom: ARM listKeys times out when I try to manually trigger

**Cause:** Azure ARM control plane slow/degraded.

**Workarounds:**
- Wait 5-10 min and retry
- Use Portal Code+Test instead of curl
- Skip manual trigger; wait for next scheduled run

Not a code issue. Doesn't affect scheduled runs.

---

## Symptom: SWA shows "No report available" even though function ran

**Check:**
1. Did the function actually write output to blob?
   ```bash
   CONN_STR=$(az storage account show-connection-string --name apolloreportsstorage --resource-group apollo-reports-rg --query connectionString -o tsv)
   
   az storage blob list \
     --container-name apollo-reports \
     --connection-string "$CONN_STR" \
     --prefix "outputs/parent-training/" \
     --query "[].{name:name, size:properties.contentLength, modified:properties.lastModified}" \
     --output table
   ```
   Expected: one folder per date the function ran, each containing an XLSX.

2. Is the report registered in `access.py`?
   ```bash
   cd ~/apollo-reporting
   grep parent-training prod/api/shared/access.py
   ```
   Expected: the report key present in `REPORT_CATALOG`.

3. Has the SWA finished deploying since the catalog was last modified?
   - Check GitHub Actions on the repo: latest workflow should be green
   - Or wait 3-4 min after any push to `main`

---

## Symptom: I need to see the actual Python error but can't get logs

**Path 1 (best): Application Insights**: same query as Step 6 above.

**Path 2: Force a re-run and grep the failure email**: the orchestrator captures full stderr and includes it in the failure notification. If your run failed, the failure email body has the traceback.

**Path 3: Read the deployed script directly**

```bash
SUB_ID=$(az account show --query id -o tsv)
az rest --method GET \
  --uri "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/apollo-reports-rg/providers/Microsoft.Web/sites/apollo-supervision-func/extensions/Vfs/site/wwwroot/parent-training-weekly/build_parent_training.py?api-version=2022-03-01" \
  --output tsv 2>&1 | head -50
```

Confirms what's actually on disk vs. what you deployed. Especially useful after suspected partial-wipe.

---

## Symptom: A small fix changed other parts of a report

Seen 9/16/2026: a one-line payor fix also removed the AR trend history, changed the DSO charts, reworded titles, and brought back an old revenue tab.

**Cause:** the change was built on a different copy of the code than the one running, usually a copy pulled from the function app's file view.

**Fix:**
1. Rebuild from the newest known-good deploy zip and reapply only the intended change. Confirm with `diff` that only the intended lines changed.
2. Build the report in Cloud Shell and compare it against a report from before the change: same tabs, same chart counts, same column counts, same titles apart from dates. Only data-driven differences should show.
3. Deploy only after that comparison is clean.

---

## Symptom: DSO Trend charts are blank or drawn sideways

**Cause:** the AR build script isn't the xlsxwriter version (v6/v11 code). The older openpyxl version builds the trend tabs from one day only and sets up the chart axes differently.

**Fix:** redeploy `~/apollo-reports-deploy-v11.zip`. Check with `unzip -p ~/apollo-reports-deploy-v11.zip financial-daily/build_ar.py | grep -c "import xlsxwriter"` (should print 1).

---

## When to Call for Help

- Azure billing/subscription issues
- App Service Plan needs resize/move
- Function app hitting resource limits repeatedly (OOM, disk full)
- Considering re-architecture (different plan, splitting apps, moving to Consumption)

Contact whoever owns the Azure account or engage Azure Support via Portal.

---

## Emergency Rollback

If a deploy broke something:

```bash
# List all deploy zips in Cloud Shell home dir
ls -lh ~/apollo-*.zip

# Deploy the most recent known-good zip
az webapp deploy \
  --resource-group apollo-reports-rg \
  --name apollo-supervision-func \
  --src-path ~/apollo-supervision-deploy-v5.zip \
  --type zip
```

Known-good baselines as of 10/5/2026:
- **Financial:** `~/apollo-reports-deploy-v11.zip` (v6 plus the T: prefix fix). Do not use v7 through v10.
- **Supervision + Parent Training + Client Roster:** `~/apollo-supervision-deploy-v10.zip`
- **Supervision + Parent Training only (before the roster):** `~/apollo-supervision-deploy-v9.zip`

**If Cloud Shell home directory got wiped:** do not rebuild from the function app's file view (ARM Vfs or Kudu). It has shown stale and missing files while the apps ran newer code. A one-line fix built on those copies on 9/16/2026 replaced the running financial scripts with older versions. Get the source into Git so a lost home folder isn't a loss of the code.

**SWA emergency rollback:** `git revert <commit>` on the repo, then push. GitHub Actions auto-deploys the reverted version.
