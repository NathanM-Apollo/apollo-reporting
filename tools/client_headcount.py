"""
Monthly client headcount roll-forward, based on 97153 billing only.

Rules
- A client is active from their first 97153 date until their last one, as long as
  no gap between visits is longer than GAP_DAYS. A longer gap ends the stretch.
- Add: first 97153 date of a stretch (a client's first ever, or first back after a
  gap longer than GAP_DAYS). Counted in that date's month.
- Churn: last 97153 date of a stretch. Counted in that date's month. A client with
  no 97153 in the newest month of data counts as churned for now, even if their gap
  is still under GAP_DAYS. If they come back within GAP_DAYS, the next run removes
  that churn on its own, since the whole table is rebuilt from billing every time.
- End Headcount: clients active on the last day of the month. Beg = prior month's End.

Usage
  python3 client_headcount.py <billing_csv_folder> [output_xlsx]
"""
import glob
import os
import sys

import pandas as pd

GAP_DAYS = 150
REPORT_START = '2025-01-01'
REPORT_END = '2026-09-30'

billing_dir = sys.argv[1]
out_xlsx = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser('~/client_headcount_test.xlsx')

# ---- Load 97153 lines from every billing file ----
files = sorted(glob.glob(os.path.join(billing_dir, '**', '*.csv'), recursive=True))
print(f'{len(files)} billing files')
parts = []
for f in files:
    d = pd.read_csv(f, usecols=['ClientId', 'ProcedureCode', 'DateOfService', 'UnitsOfService'],
                    dtype={'ClientId': str, 'ProcedureCode': str}, low_memory=False)
    d = d[d['ProcedureCode'].astype(str).str.strip().str.startswith('97153')]
    parts.append(d)
df = pd.concat(parts, ignore_index=True)
df['DateOfService'] = pd.to_datetime(df['DateOfService'], errors='coerce')
df['UnitsOfService'] = pd.to_numeric(df['UnitsOfService'], errors='coerce')
df['ClientId'] = df['ClientId'].astype(str).str.strip()
df = df.dropna(subset=['DateOfService', 'ClientId'])
df = df[df['UnitsOfService'] > 0]          # drops reversals / zero-unit lines
df = df[df['DateOfService'] <= pd.Timestamp('today')]
print(f'{len(df):,} 97153 lines, {df["ClientId"].nunique():,} clients, '
      f'{df["DateOfService"].min():%m/%d/%Y} to {df["DateOfService"].max():%m/%d/%Y}')

data_end = df['DateOfService'].max()
# Newest month = the report's last month (Sep-26). Data after it still counts toward
# whether a client is active, so a client seen in early October isn't churned.
final_month_start = pd.Period(REPORT_END, freq='M').start_time.normalize()
asof = min(data_end, pd.Timestamp(REPORT_END))

# ---- Build each client's active stretches ----
stretches = []   # (client, start, last_date, churned)
for client, dates in df.groupby('ClientId')['DateOfService']:
    ds = sorted(dates.dt.normalize().unique())
    start = prev = ds[0]
    for d in ds[1:]:
        if (d - prev).days > GAP_DAYS:
            stretches.append((client, start, prev, True))
            start = d
        prev = d
    # last stretch: still active only if they have 97153 in the newest month
    stretches.append((client, start, prev, prev < final_month_start))
st = pd.DataFrame(stretches, columns=['ClientId', 'start', 'last', 'churned'])

# ---- Monthly table ----
rows = []
for m in pd.period_range(REPORT_START, REPORT_END, freq='M'):
    m_start, m_end = m.start_time.normalize(), m.end_time.normalize()
    prev_end = m_start - pd.Timedelta(days=1)

    def active_on(day):
        return int(((st['start'] <= day) & (~st['churned'] | (st['last'] > day))).sum())

    beg = active_on(prev_end)
    adds = int(((st['start'] >= m_start) & (st['start'] <= m_end)).sum())
    churn = int((st['churned'] & (st['last'] >= m_start) & (st['last'] <= m_end)).sum())
    end = active_on(m_end)
    assert beg + adds - churn == end, f'{m}: {beg}+{adds}-{churn} != {end}'
    rows.append({'Month': m.strftime('%b-%y'), 'Beg Headcount': beg, 'Adds': adds,
                 'Churn': churn, 'End Headcount': end})
table = pd.DataFrame(rows)

prov_from = (asof - pd.Timedelta(days=GAP_DAYS)).to_period('M').strftime('%b-%y')
note = (f'Churn from {prov_from} on includes clients with no 97153 in '
        f'{asof:%b-%y} who are still within {GAP_DAYS} days of their last visit. '
        f'Those come off churn if the client returns. Billing data through {data_end:%m/%d/%Y}.')

print()
print(table.to_string(index=False))
print()
print(note)

with pd.ExcelWriter(out_xlsx) as xw:
    table.to_excel(xw, sheet_name='Client Headcount', index=False, startrow=0)
    pd.DataFrame({'Note': [note]}).to_excel(xw, sheet_name='Client Headcount',
                                             index=False, header=False, startrow=len(table) + 2)
print(f'\nSaved: {out_xlsx}')
