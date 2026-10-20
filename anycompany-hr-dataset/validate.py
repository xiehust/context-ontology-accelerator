#!/usr/bin/env python3
"""Re-derive cross-table invariants of the AnyHR v2 CSVs (reads only the CSVs, not gen.py state)."""

import csv
import datetime as dt
import math
import sys
from collections import defaultdict

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
ORIG = sys.argv[2] if len(sys.argv) > 2 else "seed"
D = dt.date.fromisoformat
fails: list[str] = []


def rd(n, base=OUT):
    path = f"{base}/{n}/{n}.csv" if base == OUT else f"{base}/{n}.csv"
    return list(csv.DictReader(open(path, encoding="utf-8")))


def check(cond, msg):
    if not cond:
        fails.append(msg)


cal = {D(r["cal_date"]): r for r in rd("work_calendar")}
emp = {r["employee_id"]: r for r in rd("employees")}
lv = rd("leave_requests")
bal = rd("leave_balances")
ot = rd("overtime_records")
pay = rd("payroll_monthly")
sal = defaultdict(list)
for r in rd("salary_history"):
    sal[r["employee_id"]].append(r)
levels = {r["job_level"]: r for r in rd("job_levels")}
exp = rd("expense_claims")
att = rd("attendance_daily")
depts = {r["department_code"]: r for r in rd("departments")}

# 1. originals preserved verbatim
for name, key in [("employees", "employee_id"), ("leave_requests", "request_id"), ("overtime_records", "record_id")]:
    new = {r[key]: r for r in rd(name)}
    for o in rd(name, ORIG):
        n = new.get(o[key])
        check(n is not None, f"{name}: original {o[key]} missing")
        if n:
            for c, v in o.items():
                if name == "employees" and c in ("department_code", "manager_id", "employment_status"):
                    continue  # re-homed into sub-teams / CEO; EMP-3524 regularized
                check(
                    n[c] == v or (c.endswith("days") or c.endswith("hours")) and float(n[c]) == float(v),
                    f"{name} {o[key]}.{c}: {v!r} -> {n[c]!r}",
                )
for o in rd("leave_balances", ORIG):
    n = [
        b
        for b in bal
        if (b["employee_id"], b["leave_year"], b["leave_type"]) == (o["employee_id"], o["leave_year"], o["leave_type"])
    ]
    check(
        len(n) == 1 and all(float(n[0][c]) == float(o[c]) for c in o if c.endswith("days")),
        f"balance {o['employee_id']} changed",
    )

# 2. referential integrity
for e in emp.values():
    check(e["department_code"] in depts, f"dept {e['department_code']}")
    check(not e["manager_id"] or e["manager_id"] in emp, f"manager {e['manager_id']}")
for d in depts.values():
    check(d["head_employee_id"] in emp, f"head {d['head_employee_id']}")
    check(not d["parent_department_code"] or d["parent_department_code"] in depts, "parent dept")
for t in (lv, ot, pay, exp, att):
    for r in t:
        check(r["employee_id"] in emp, f"unknown employee {r['employee_id']}")

# 3. balances == aggregated requests
agg: defaultdict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
for r in lv:
    k = (r["employee_id"], r["start_date"][:4], r["leave_type"])
    if r["status"] == "APPROVED":
        agg[k][0] += float(r["days"])
    elif r["status"] == "PENDING":
        agg[k][1] += float(r["days"])
for b in bal:
    used_d, pend_d = agg[(b["employee_id"], b["leave_year"], b["leave_type"])]
    check(
        abs(float(b["used_days"]) - used_d) < 1e-6 and abs(float(b["pending_days"]) - pend_d) < 1e-6,
        f"balance agg {b['employee_id']} {b['leave_year']} {b['leave_type']}: {b['used_days']}/{b['pending_days']} vs {used_d}/{pend_d}",
    )
    check(
        abs(float(b["remaining_days"]) - (float(b["total_days"]) - float(b["used_days"]))) < 1e-6,
        "remaining = total - used",
    )


# 4. annual quota by policy (HR-LV-001 1.2-1.5; 2025: company 5 flat)
def fy(a, b):
    return max(0, b.year - a.year - ((b.month, b.day) < (a.month, a.day)))


for b in bal:
    if b["leave_type"] != "ANNUAL":
        continue
    e = emp[b["employee_id"]]
    y = int(b["leave_year"])
    jan1 = dt.date(y, 1, 1)
    hire, career = D(e["hire_date"]), D(e["career_start_date"])
    cy = fy(career, jan1)
    st = 0 if cy < 1 else 5 if cy < 10 else 10 if cy < 20 else 15
    co = (5 if fy(hire, jan1) < 3 else 7 if fy(hire, jan1) < 5 else 10) if y >= 2026 else 5
    if hire > jan1:
        st_h = 0 if fy(career, hire) < 1 else st
        exp_tot = math.floor(((dt.date(y, 12, 31) - hire).days + 1) / 365 * (st_h + co) * 2) / 2
    else:
        exp_tot = st + co
    check(float(b["total_days"]) == exp_tot, f"quota {b['employee_id']} {y}: {b['total_days']} vs {exp_tot}")

# 5. leave days == workdays in range (calendar), except the original data and calendar-day leave types
orig_ids = {r["request_id"] for r in rd("leave_requests", ORIG)}
for r in lv:
    if r["request_id"] in orig_ids or r["leave_type"] == "MATERNITY":
        continue
    d0, d1 = D(r["start_date"]), D(r["end_date"])
    n = sum(1 for i in range((d1 - d0).days + 1) if cal[d0 + dt.timedelta(days=i)]["is_workday"] == "true")
    check(
        float(r["days"]) in (n, 0.5) and (float(r["days"]) != 0.5 or n == 1),
        f"leave days {r['request_id']} {r['days']} vs {n}",
    )
    check(cal[d0]["is_workday"] == "true", f"leave starts on non-workday {r['request_id']}")


# 6. payroll overtime pay == sum(approved PAID OT × base/21.75/8 × rate)
def base_on(eid, d):
    cur = None
    for h in sal[eid]:
        if D(h["effective_date"]) <= d:
            cur = h
    return float((cur or sal[eid][0])["base_salary_monthly"])


exp_ot: defaultdict[tuple[str, str], float] = defaultdict(float)
for o in ot:
    if (
        o["approval_status"] == "APPROVED"
        and o["compensation_method"] == "PAID"
        and emp[o["employee_id"]]["employee_category"] != "INTERN"
    ):
        d = D(o["work_date"])
        exp_ot[(o["employee_id"], o["work_date"][:7])] += (
            base_on(o["employee_id"], d) / 21.75 / 8 * float(o["overtime_hours"]) * float(cal[d]["overtime_pay_rate"])
        )
paid_months = {(p["employee_id"], p["pay_month"]) for p in pay}
for p in pay:
    check(
        abs(float(p["overtime_pay"]) - exp_ot[(p["employee_id"], p["pay_month"])]) < 0.02,
        f"OT pay {p['employee_id']} {p['pay_month']}: {p['overtime_pay']} vs {exp_ot[(p['employee_id'], p['pay_month'])]:.2f}",
    )
    comp = sum(
        float(p[c])
        for c in (
            "base_salary",
            "position_allowance",
            "overtime_pay",
            "communication_allowance",
            "lunch_allowance",
            "fitness_subsidy",
            "unused_leave_payout",
        )
    ) - float(p["unpaid_leave_deduction"])
    check(abs(comp - float(p["gross_pay"])) < 0.05, f"gross {p['employee_id']} {p['pay_month']}")
    net = (
        float(p["gross_pay"])
        + float(p["annual_bonus"])
        - sum(
            float(p[c])
            for c in (
                "social_insurance_employee",
                "housing_fund_employee",
                "supplementary_fund_employee",
                "individual_income_tax",
                "bonus_tax",
            )
        )
    )
    check(abs(net - float(p["net_pay"])) < 0.05, f"net {p['employee_id']} {p['pay_month']}")
    check(D(p["pay_date"]).day <= 10 and cal[D(p["pay_date"])]["is_workday"] == "true", f"pay date {p['pay_date']}")
for (eid, m), v in exp_ot.items():
    if m <= "2026-09" and v > 0:
        check((eid, m) in paid_months, f"OT pay with no payroll row {eid} {m}")

# 7. overtime type matches calendar
for o in ot:
    c = cal[D(o["work_date"])]
    t = (
        "STATUTORY_HOLIDAY"
        if c["is_statutory_holiday"] == "true"
        else ("WORKDAY" if c["is_workday"] == "true" else "REST_DAY")
    )
    check(o["overtime_type"] == t, f"OT type {o['record_id']}")
    check(
        not (t == "STATUTORY_HOLIDAY" and o["compensation_method"] != "PAID")
        or o["record_id"].startswith("OT-2026-000"),
        f"statutory OT must be paid {o['record_id']}",
    )

# 8. expenses: paid on Thursdays; paid OT taxis link to approved OT ending >= 21:00
oti = {o["record_id"]: o for o in ot}
for x in exp:
    if x["status"] == "PAID":
        check(D(x["paid_date"]).weekday() == 3, f"paid not Thursday {x['claim_id']}")
        rv = dt.datetime.strptime(x["finance_reviewed_at"], "%Y-%m-%d %H:%M")
        check(D(x["paid_date"]) > rv.date(), f"paid before review {x['claim_id']}")
    if x["category"] == "OT_TAXI" and x["status"] != "REJECTED":
        o = oti.get(x["related_overtime_id"])
        check(o and o["approval_status"] == "APPROVED" and o["end_time"] >= "21:00", f"taxi policy {x['claim_id']}")
    amt = float(x["amount"])
    hops = x["approval_path"].count(">") + 1
    check(
        hops == (1 if amt <= 2000 else 2 if amt <= 10000 else 3),
        f"approval path {x['claim_id']} {amt} {x['approval_path']}",
    )

# 9. attendance: ON_LEAVE references an approved leave covering that day
lvi = {r["request_id"]: r for r in lv}
for a in att:
    if a["attendance_status"] == "ON_LEAVE":
        r = lvi.get(a["leave_request_id"])
        check(r and r["status"] == "APPROVED" and r["start_date"] <= a["work_date"] <= r["end_date"], f"att leave {a}")
    check(cal[D(a["work_date"])]["is_workday"] == "true", f"attendance on non-workday {a['work_date']}")

# 10. salary history ends at the employee's current level, inside band +10%
for eid, hs in sal.items():
    check(hs[-1]["job_level"] == emp[eid]["job_level"], f"level drift {eid}")
    for h in hs:
        lvl = levels[h["job_level"]]
        check(
            float(lvl["salary_band_min"]) * 0.99
            <= float(h["base_salary_monthly"])
            <= float(lvl["salary_band_max"]) * 1.1 + 1,
            f"band {eid} {h['job_level']} {h['base_salary_monthly']}",
        )

print("checks failed:", len(fails))
for f in fails[:40]:
    print(" -", f)
sys.exit(1 if fails else 0)
