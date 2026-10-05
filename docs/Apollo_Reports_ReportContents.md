# Apollo Reports: Report Contents Reference

Business documentation of what each report contains, how metrics are calculated, and what to look for. Read this to understand the substance of the reports. See the IP doc for how the code runs, the How-To docs for how to operate the system.

---

## Overview

Apollo automates five reports:

| Report | Frequency | Recipients | File name pattern |
|---|---|---|---|
| Daily Revenue | Weekdays 7:30 AM ET | Financial leadership | `Apollo_Daily_Revenue_Report.xlsx` |
| Daily AR | Weekdays 7:30 AM ET | Financial leadership | `Apollo_AR_Report.xlsx` |
| Weekly Supervision Ratio | Monday 8:00 AM ET | Nathan, Kim, Devin, Clinical Excellence | `Apollo_Supervision_Ratio_YYYY-MM-DD.xlsx` |
| Weekly Parent Training | Monday 8:30 AM ET | Nathan, Kim, Devin, Clinical Excellence | `Apollo_Parent_Training_YYYY-MM-DD.xlsx` |
| Client & Insurance Roster | Weekdays 9:00 AM ET | Portal only, no email | `Apollo_Client_Roster_YYYY-MM-DD.xlsx` |

The two daily financial reports come as attachments in a single email. The two weekly reports come as separate emails. The roster is not emailed.

All five are viewable on the reporting portal (Static Web App).

Source data for all reports: CentralReach exports uploaded to Azure Blob Storage as CSV files.

---

## Revenue Report: Daily

**Purpose:** track revenue performance across payors, procedure codes, and time windows.

**Data source:** all billing CSVs in `apollo-reports/inputs/billing/` (spans 2021-present, ~660 MB).

**Revenue definition:** `ClientChargesAgreedTotal` field from CentralReach billing exports. Void and deleted lines excluded.

### Tab-by-tab

1. **Summary**: L7/L30/L90/L365 revenue, WTD/MTD, top-line snapshot
2. **Payor Revenue**: every payor across time windows, % of total, revenue per unit
3. **Procedure Codes**: same structure but by CPT code (97153 dominates; 97155/97154 smaller; 97156 emerging)
4. **Daily Trend**: chart of daily revenue + 30-day rolling average
5. **Daily History**: raw daily revenue table (backing data)
6. **Weekly Trend**: weekly revenue + revenue per unit chart
7. **Payor Trend (Monthly)**: 100% stacked chart of monthly revenue mix by payor, plus a line view from 2022 on
8. **Payor Mapping**: reference: raw `PayorName` → `ConsolidatedPayor` grouping

There is no Collection Performance tab on the revenue report. Collection rates by aging band are on the AR report's Collection Cohort and Aging Trend tabs.

**Payor grouping:** the `P:`, `S:`, and `T:` (primary, secondary, tertiary) prefixes are stripped before grouping, so each claim lands under its insurer.

### What to look for

- **Payor concentration**: Payor Trend tab, one payor > 40% is a concentration risk
- **Collection degradation**: AR report's Aging Trend tab, compare recent rates by band to earlier dates
- **Sudden drops in Daily Trend**: may indicate billing pause or export gap
- **Rev/unit falling**: mix shift or rate cuts

---

## AR Report: Daily

**Purpose:** track outstanding accounts receivable, aging patterns, and DSO by payor.

**Data source:** all receivables CSVs in `apollo-reports/inputs/receivables/` (must have "Receivables" in filename), plus billing CSVs for cohort context.

**Net AR definition:** sum of the age bucket columns (0-30 through 365+) from CentralReach receivables exports. Includes credit balances (negatives).

### Tab-by-tab

1. **Summary**: Net AR total, Gross AR, credit balances, L60/L365 revenue, portfolio DSO
2. **Aging by Payor**: payor × aging bucket matrix + stacked bar chart
3. **Collection Cohort**: same as Revenue's Collection Performance tab
4. **DSO by Payor**: Days Sales Outstanding for each payor at 60- and 365-day windows
5. **Patient AR**: patient-owed portion of AR (co-pays, deductibles, self-pay)
6. **Credits & Negatives**: lines with negative balances
7. **Aging Trend**: collection rate by aging band, one row per saved day, newest first
8. **DSO Trend**: two line charts of 60-day DSO (top 6 payors by Net AR, then the rest), with the daily tables that feed them below
9. **Payor Mapping**: same reference as Revenue

Trend tabs (7, 8) are built from the daily snapshots saved in `snapshots/ar/`, back to 5/8/2026. Each run saves that day's snapshot after the report is built. There is no cutoff yet; a trailing-12-month limit is planned. Saved days from before 9/16/2026 recorded tertiary claims under a payor named "T". DSO Trend takes its payor columns from the current day's payor list, so "T" doesn't show. For those earlier dates, Georgia Medicaid (DXC) excludes the tertiary claims, which were near zero Net AR.

### What to look for

- **Net AR movement**: Summary tab, is AR growing faster than revenue?
- **365+ bucket growth**: Aging by Payor, specific payors' 365+ column trending up
- **DSO spikes**: DSO Trend, doubling suggests adjudication logic change
- **Aging drift**: Aging Trend, % of AR in 90+ bucket climbing week over week

---

## Supervision Ratio Report: Weekly

**Purpose:** track BCBA supervision ratio across clinics and individual clients.

**Data source:** billing CSVs, filtered to 2026+ data only.

### The Metric

**Formula:** `97155 units ÷ (97153 units + 97154 units)`, as a percentage.

- **97153**: Adaptive behavior treatment by RBT/BT (direct 1:1)
- **97154**: Group adaptive behavior treatment
- **97155**: Protocol modification by BCBA (supervision)

**Interpretation:** ratio of BCBA supervision units to direct treatment units. Healthy portfolio typically 5-10% depending on payor and clinical model.

**Portfolio baseline:** ~6.3% across Apollo.

### Tab-by-tab

**1. Supervision Ratio (main matrix)**
- Rows: active clinics alphabetically + "Unmapped" + "Portfolio Total"
- Columns: L7 | L30 | L90 | then months, newest first (current month, prior month, ...), trailing 12 months, never earlier than Jan-26
- Cells: supervision ratio for that clinic × window (blank if no activity)
- L90 color-scaled
- "Portfolio Total" is weighted average, not simple mean

**2. Supervision by Client**
- Rows: every (client × center) with ≥1 unit of 97153 in L7
- Columns: Client ID | Initials | Center | L7 Direct Units | L7 | L30 | L90 | months (newest first, trailing 12)
- Autofilter and frozen panes on

**3. Methodology**: formulas, windows, exclusions, mapping logic

**4. Clinic Mapping**: reference table of clinic → street number → address

### Windows

**L7, L30, L90** are anchored to the **latest DateOfService** in the billing data, not the calendar date.

Example: if newest DOS is 2026-06-15:
- L7 = 2026-06-09 through 2026-06-15
- L30 = 2026-05-17 through 2026-06-15
- L90 = 2026-03-18 through 2026-06-15

### Inclusion criterion (client tab)

A (client × center) pair appears only if that client billed ≥1 unit of 97153 at that center in L7 (low bar, so many clients appear).

### Clinic filter

Only clinics with any activity (97153/97154/97155) in the 2026+ filtered dataset appear on the main summary tab. Clinics in `config/clinics.csv` that haven't started services yet (like Columbus in mid-2026) are hidden. They still appear in the Clinic Mapping reference tab.

### What to look for

- **Portfolio Total drift**: moves outside 5-8% band = investigate
- **Outlier clinics**: L90 color scale surfaces high/low
- **Sudden month-over-month spikes**: often small-N volatility for low-volume clinics
- **Unmapped %**: sudden growth may mean a new clinic address needs adding to `config/clinics.csv`

---

## Parent Training Report: Weekly

**Purpose:** track parent/caregiver training delivery per active client across clinics and individual clients.

**Data source:** billing CSVs, filtered to 2026+ data only.

### The Metric

**Formula:** `97156 hours ÷ number of qualifying clients per clinic and portfolio-wide`.

- **97156**: Family adaptive behavior treatment guidance (parent training / caregiver training)
- Hours = units × 0.25 (each CPT unit = 15 minutes)

**Interpretation:** on average, how many hours of parent training each qualifying client received during a period. Different from supervision, this is a per-client "dosage" measure, not a ratio.

### Column Formulas

All summary columns normalized to a ~30-day scale for direct comparability:

- **L7 × 4 hrs** = Σ 97156 hours in L7 × 4 ÷ count(distinct clients with ≥1 unit of 97153 in L7)
- **L30 hrs** (baseline) = Σ 97156 hours in L30 ÷ count(distinct clients with ≥8 hrs of 97153 in L30)
- **L90 ÷ 3 hrs** = Σ 97156 hours in L90 ÷ 3 ÷ count(distinct clients with ≥8 hrs of 97153 in EACH of 3 rolling 30-day sub-windows within L90)
- **Monthly (Jan-26 hrs, etc.)** = Σ 97156 hours in that month ÷ count(distinct clients with ≥8 hrs of 97153 in that same month)

The ×4 and ÷3 scaling are shown in the column headers for clarity. All columns therefore express "hours per qualifying client per ~30-day period."

### Client Qualification Rules

**Different thresholds by window:**

- **L7:** ≥1 unit of 97153 in L7 (low bar; captures anyone currently active)
- **L30:** ≥8 hrs of 97153 in L30 (moderate bar; ~2 sessions/week over 30 days)
- **L90:** ≥8 hrs of 97153 in EACH of 3 rolling 30-day sub-windows (stricter; requires consistent activity throughout the 90 days)
- **Monthly:** ≥8 hrs of 97153 in that month (same threshold as L30 but per calendar month)

**Why L90 uses 3 sub-windows:** captures "consistently active" clients only. A client active only in the most recent 30 days would qualify for L30 but not L90.

### Tab-by-tab

**1. Parent Training (main matrix)**
- Rows: active clinics alphabetically + "Unmapped" + "Apollo Total"
- Columns: L7 × 4 hrs | L30 hrs | L90 ÷ 3 hrs | then months, newest first (for example Sep-26 hrs, Aug-26 hrs, ...), trailing 12 months, never earlier than Jan-26
- Cells: hours per qualifying client for that clinic × window (blank if 0 qualifying clients)
- L90 color-scaled
- Column headers include "hrs" to prevent SWA classifier from displaying values as percentages

**2. Parent Training by Client**
- Rows: every (client × center) with ≥8 hrs of 97153 in L30
- Columns: Client ID | Initials | Center | L7 Direct Units | L30 97156 Hours | months (newest first, trailing 12)
- Historical-only clients are DROPPED (unlike supervision's client tab, which uses L7 threshold)
- Autofilter and frozen panes on

**3. Methodology**: formulas, windows, exclusions

**4. Clinic Mapping**: same reference as supervision

### Windows

Same as supervision, anchored to latest DateOfService, not calendar date.

### Clinic Filter

Same as supervision, clinics with any 97153/97154/97156 activity in the 2026+ dataset appear on the main summary tab. Others hidden from summary but present in Clinic Mapping reference tab.

### Key Behavior Difference vs. Supervision

**Main tab:** each column recomputes qualifying clients independently. A client active in Feb-Mar but inactive now still shows up in the Feb-26 and Mar-26 columns' calculations.

**Client tab:** a (client × center) pair appears only if that pair currently clears ≥8 hrs of 97153 in L30. Historically-active clients who've dropped below this threshold are excluded entirely from the client tab.

This is intentional, the main tab shows the full historical picture, but the client tab focuses on currently-active clients since it's used for individual outreach and clinical review.

### What to look for

- **Portfolio Total drift**: moves outside expected band (typically ~0.5-1.5 hrs/client/month) = investigate
- **Outlier clinics**: L90 ÷ 3 color scale surfaces high/low delivery
- **L7 × 4 vs L30 divergence**: recent surge or drop that hasn't shown up in the monthly average yet
- **Client tab: high monthly hours with low L7 Direct Units**: client just wrapped up an intensive parent training block
- **Client tab: 0 in "L30 97156 Hours" but qualifying**: this can't happen (qualification requires 97156 activity). If you see it, something's wrong with the data pipeline.
- **Growing Unmapped hours**: a new clinic address needs adding to `config/clinics.csv`

### Portfolio Numbers (as of Aug 2026)

- Apollo total L7 × 4 hrs: ~0.5 hrs/client/30d
- Apollo total L30: ~0.9 hrs/client/30d
- Apollo total L90 ÷ 3: ~1.0 hrs/client/30d
- ~334 (client × center) pairs qualifying for L30 client tab
- Mapping rate: ~98%

---

## Client & Insurance Roster: Weekdays

**Purpose:** who is in active treatment right now, which insurer covers them, and which site serves them.

**Data source:** billing CSVs, last 30 days (L30), counted back from the latest 97153 date of service. Void and deleted lines and zero-unit lines are excluded.

**Delivery:** portal only. Refreshed each weekday at 9:00 AM ET. No email.

### Who counts

- **Active clients:** billed for 97153 at least once in L30. This was 336 clients on 10/5/2026.
- **Other Services clients:** billed for any other code in L30 but no 97153, for example only assessments (97151) or only parent training (97156). A quick count on 10/5/2026 gave 53 (389 clients billed for anything, minus 336).

### Rules

- **Payor:** the primary (`P:`) payor on the client's most recent claim in L30. If that date has no `P:` line, the payor on the latest line is used. Payor names use the same grouping as the revenue report.
- **Other payors in L30:** any other payor billed for that client in L30.
- **Site:** the clinic where most of the client's L30 units were delivered, using `config/clinics.csv`. Units at home or other unmapped addresses decide the site only if the client had no clinic units in L30.
- **Initials:** first 2 letters of first name + first 2 of last (John Smith → JoSm).
- **Most common code (by hours):** Other Services roster only. The code with the most hours in L30 (hours = units × 0.25). Ties go to the lower code number.

### Tabs

1. **By Payor**: Payor | Clients | % of Clients, with a Total row
2. **By Site**: one row per site, one column for each of the 8 payors with the most clients, an All Other column, and a Total column. The subtitle lists the payors in All Other.
3. **Roster**: Client ID | Initials | Site | Payor | Other payors in L30 | Last 97153 date
4. **Other Services - By Payor**: same layout, Other Services clients
5. **Other Services - By Site**: same layout, Other Services clients
6. **Other Services - Roster**: same columns plus Most common code (by hours), with Last service date in place of Last 97153 date

### What to look for

- **Active count drifting down** while Other Services rises: clients waiting on authorizations or stuck in assessment
- **Unmapped site row:** clients served only at home or by telehealth, or a new clinic address missing from `config/clinics.csv`
- **Other payors in L30:** clients with a coverage change during the month

---

## Adding New Metrics

If leadership requests a new metric that doesn't fit existing tabs:

1. Confirm the data exists in the CSV exports (spot-check by column name)
2. Prototype the calculation in a Cloud Shell Python script or Excel
3. Add a tab to the appropriate build script
4. Test locally against real data
5. Deploy

No hardcoded schema in any of the reports, new tabs can be added, existing ones modified. Main constraint is Excel file size (currently ~40-100 KB range, plenty of headroom).

---

## Example Numbers (as of last known run)

**Revenue Report:**
- L365 Revenue: ~$26M
- Portfolio DSO (60-day): ~90 days
- Top payor: CareSource (~30% of AR)

**AR Report:**
- Net AR (Insurance): ~$4M
- Net AR (Patient): ~$200K
- Aged 365+: <5% of AR (healthy)

**Supervision Report:**
- Portfolio L90 supervision ratio: 6.3%
- ~309 (client × center) rows in Supervision by Client tab
- 97-98% mapping rate

**Parent Training Report:**
- Portfolio L30: ~0.9 hrs/client/30d
- ~334 (client × center) rows in Parent Training by Client tab
- 97-98% mapping rate

**Client & Insurance Roster (10/5/2026):**
- 336 active clients (97153 in L30)
- about 53 Other Services clients

Use these as sanity checks. Wildly different numbers on a new run = check input data (Troubleshooting doc has the file-naming diagnostic).
