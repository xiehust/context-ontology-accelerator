#!/usr/bin/env python3
"""Generate the AnyCompany HR v2 demo dataset (deterministic, stdlib only).

Every derived number follows the AnyCompany handbook (HR-LV-001, HR-AT-001,
HR-EX-001, FIN-TR-001, HR-BN-001, HR-PY-001, HR-EM-001, HR-CP-001, HR-PF-001).
The original 24 employees, 21 leave requests and 8 overtime records are kept
verbatim so earlier demo questions keep their answers.

Usage: python3 gen.py <out_dir>
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import random
import sys
from collections import defaultdict

D = dt.date
TODAY = D(2026, 10, 20)
CUTOFF = D(2026, 10, 19)  # last day with actuals
DATA_START = D(2025, 1, 1)
HERE = os.path.dirname(os.path.abspath(__file__))
ORIG = os.path.join(HERE, "seed")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "out")
rng = random.Random(20261020)
ANOMALIES: list[dict] = []  # answer key for the demo script


def note(kind: str, **kw) -> None:
    ANOMALIES.append({"kind": kind, **kw})


# ───────────────────────────── calendar ─────────────────────────────
# (name, first_day, last_day, statutory_days, adjusted_workdays)
HOLIDAYS = [
    ("元旦", D(2025, 1, 1), D(2025, 1, 1), [D(2025, 1, 1)], []),
    (
        "春节",
        D(2025, 1, 28),
        D(2025, 2, 4),
        [D(2025, 1, 28), D(2025, 1, 29), D(2025, 1, 30), D(2025, 1, 31)],
        [D(2025, 1, 26), D(2025, 2, 8)],
    ),
    ("清明节", D(2025, 4, 4), D(2025, 4, 6), [D(2025, 4, 4)], []),
    ("劳动节", D(2025, 5, 1), D(2025, 5, 5), [D(2025, 5, 1), D(2025, 5, 2)], [D(2025, 4, 27)]),
    ("端午节", D(2025, 5, 31), D(2025, 6, 2), [D(2025, 5, 31)], []),
    (
        "国庆节、中秋节",
        D(2025, 10, 1),
        D(2025, 10, 8),
        [D(2025, 10, 1), D(2025, 10, 2), D(2025, 10, 3), D(2025, 10, 6)],
        [D(2025, 9, 28), D(2025, 10, 11)],
    ),
    ("元旦", D(2026, 1, 1), D(2026, 1, 3), [D(2026, 1, 1)], [D(2026, 1, 4)]),
    (
        "春节",
        D(2026, 2, 15),
        D(2026, 2, 23),
        [D(2026, 2, 16), D(2026, 2, 17), D(2026, 2, 18), D(2026, 2, 19)],
        [D(2026, 2, 14), D(2026, 2, 28)],
    ),
    ("清明节", D(2026, 4, 4), D(2026, 4, 6), [D(2026, 4, 5)], []),
    ("劳动节", D(2026, 5, 1), D(2026, 5, 5), [D(2026, 5, 1), D(2026, 5, 2)], [D(2026, 5, 9)]),
    ("端午节", D(2026, 6, 19), D(2026, 6, 21), [D(2026, 6, 19)], []),
    ("中秋节", D(2026, 9, 25), D(2026, 9, 27), [D(2026, 9, 25)], []),
    (
        "国庆节",
        D(2026, 10, 1),
        D(2026, 10, 7),
        [D(2026, 10, 1), D(2026, 10, 2), D(2026, 10, 3)],
        [D(2026, 9, 20), D(2026, 10, 10)],
    ),
]
CAL: dict[D, dict] = {}


def build_calendar() -> None:
    hol, stat, adj = {}, set(), set()
    for name, a, b, s, w in HOLIDAYS:
        d = a
        while d <= b:
            hol[d] = name
            d += dt.timedelta(days=1)
        stat.update(s)
        adj.update(w)
    d = D(2024, 7, 1)
    while d <= D(2026, 12, 31):
        if d in adj:
            t = "ADJUSTED_WORKDAY"
        elif d in hol:
            t = "HOLIDAY"
        elif d.weekday() >= 5:
            t = "WEEKEND"
        else:
            t = "WORKDAY"
        rate = 3.0 if d in stat else (2.0 if t in ("HOLIDAY", "WEEKEND") else 1.5)
        CAL[d] = {
            "day_type": t,
            "holiday_name": hol.get(d, ""),
            "statutory": d in stat,
            "rate": rate,
            "workday": t in ("WORKDAY", "ADJUSTED_WORKDAY"),
        }
        d += dt.timedelta(days=1)


def is_wd(d: D) -> bool:
    return CAL[d]["workday"]


def days(a: D, b: D):
    d = a
    while d <= b:
        yield d
        d += dt.timedelta(days=1)


def workdays(a: D, b: D) -> list[D]:
    return [d for d in days(a, b) if is_wd(d)]


def next_wd(d: D) -> D:
    while not is_wd(d):
        d += dt.timedelta(days=1)
    return d


def prev_wd(d: D) -> D:
    while not is_wd(d):
        d -= dt.timedelta(days=1)
    return d


def add_wd(d: D, n: int) -> D:
    """Return the date n workdays after workday d (n=0 -> d)."""
    while n > 0:
        d += dt.timedelta(days=1)
        if is_wd(d):
            n -= 1
    return d


def sub_wd(d: D, n: int) -> D:
    while n > 0:
        d -= dt.timedelta(days=1)
        if is_wd(d):
            n -= 1
    return d


def month_end(y: int, m: int) -> D:
    return D(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)


def years_between(a: D, b: D) -> float:
    return (b - a).days / 365.25


def full_years(a: D, b: D) -> int:
    y = b.year - a.year - ((b.month, b.day) < (a.month, a.day))
    return max(0, y)


def add_months(d: D, n: int) -> D:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return D(y, m, min(d.day, month_end(y, m).day))


def r2(x: float) -> float:
    return round(x + 1e-9, 2)


def floor_half(x: float) -> float:
    return math.floor(x * 2 + 1e-9) / 2


# ───────────────────────────── org ─────────────────────────────
CITY_TIER = {
    "北京": 1,
    "上海": 1,
    "广州": 1,
    "深圳": 1,
    "成都": 2,
    "杭州": 2,
    "南京": 2,
    "武汉": 2,
    "西安": 2,
    "重庆": 2,
    "厦门": 2,
    "青岛": 2,
    "天津": 2,
    "合肥": 2,
    "苏州": 3,
    "无锡": 3,
    "佛山": 3,
    "东莞": 3,
}

DEPTS = [  # code, cn, en, parent, head, city, budget
    ("EXEC", "总裁办", "Executive Office", "", "EMP-1001", "上海", 2),
    ("ENG", "研发中心", "Engineering", "", "EMP-1002", "上海", 2),
    ("ENG-PLT", "平台研发组", "Platform Engineering", "ENG", "EMP-2018", "上海", 26),
    ("ENG-APP", "应用研发组", "Application Engineering", "ENG", "EMP-2046", "成都", 22),
    ("ENG-DATA", "数据智能组", "Data & AI", "ENG", "EMP-2060", "上海", 14),
    ("ENG-QA", "质量保障组", "Quality Assurance", "ENG", "EMP-2071", "成都", 12),
    ("PRD", "产品部", "Product", "", "EMP-1015", "上海", 10),
    ("PRD-UX", "用户体验组", "UX Design", "PRD", "EMP-2083", "上海", 6),
    ("HR", "人力资源部", "HR Operations", "", "EMP-1008", "上海", 9),
    ("FIN", "财务部", "Finance", "", "EMP-1011", "上海", 9),
    ("SAL", "销售部", "Sales", "", "EMP-1020", "北京", 2),
    ("SAL-N", "华北销售组", "North China Sales", "SAL", "EMP-1020", "北京", 11),
    ("SAL-E", "华东销售组", "East China Sales", "SAL", "EMP-2090", "上海", 11),
    ("SAL-S", "华南销售组", "South China Sales", "SAL", "EMP-2095", "深圳", 9),
    ("CS", "客户成功部", "Customer Success", "", "EMP-1031", "深圳", 10),
    ("CS-SUP", "技术支持组", "Technical Support", "CS", "EMP-2101", "成都", 12),
    ("MKT", "市场部", "Marketing", "", "EMP-1040", "上海", 9),
    ("ADM", "行政部", "Administration", "", "EMP-1045", "上海", 6),
]
DEPT = {d[0]: d for d in DEPTS}
TOP = {d[0]: (d[3] or d[0]) for d in DEPTS}

LEVELS = [  # level, track, title, band_min, band_max, allowance
    ("INT", "INTERN", "实习生", 4000, 6000, 0),
    ("P3", "PROFESSIONAL", "助理工程师 / 专员", 8000, 12000, 0),
    ("P4", "PROFESSIONAL", "工程师 / 主管", 12000, 18000, 0),
    ("P5", "PROFESSIONAL", "高级工程师 / 高级主管", 16000, 25000, 0),
    ("P6", "PROFESSIONAL", "资深工程师 / 资深主管", 22000, 35000, 0),
    ("P7", "PROFESSIONAL", "专家", 30000, 48000, 800),
    ("P8", "PROFESSIONAL", "高级专家", 42000, 65000, 1500),
    ("M1", "MANAGEMENT", "经理", 30000, 45000, 2000),
    ("M2", "MANAGEMENT", "高级经理 / 部门负责人", 40000, 60000, 3000),
    ("M3", "MANAGEMENT", "总监", 55000, 85000, 5000),
    ("M4", "MANAGEMENT", "首席执行官", 90000, 140000, 8000),
]
LV = {rec[0]: rec for rec in LEVELS}
P_LADDER = ["P3", "P4", "P5", "P6", "P7", "P8"]
M_LADDER = ["P5", "P6", "P7", "M1", "M2", "M3", "M4"]

SURN = list(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤"
)
MALE = [
    "浩然",
    "子轩",
    "宇航",
    "俊豪",
    "博文",
    "志强",
    "建华",
    "天佑",
    "文涛",
    "嘉懿",
    "明轩",
    "思源",
    "宏伟",
    "家豪",
    "振宇",
    "鹏飞",
    "伟",
    "峰",
    "超",
    "磊",
    "健",
    "勇",
    "斌",
    "亮",
    "涛",
    "旭东",
    "晨阳",
    "梓睿",
    "皓轩",
    "立诚",
    "子墨",
    "一凡",
    "承泽",
    "景行",
    "知远",
    "泽宇",
    "海洋",
    "国栋",
    "嘉树",
    "云帆",
]
FEMALE = [
    "欣怡",
    "梓涵",
    "诗琪",
    "雨萱",
    "思彤",
    "佳琪",
    "梦瑶",
    "晓彤",
    "雅婷",
    "婉清",
    "可馨",
    "语桐",
    "静怡",
    "丽娟",
    "芳",
    "敏",
    "颖",
    "琳",
    "倩",
    "洁",
    "慧",
    "蕾",
    "若彤",
    "心怡",
    "一诺",
    "沐晴",
    "安琪",
    "晨曦",
    "书瑶",
    "子衿",
    "清欢",
    "芷若",
    "紫萱",
    "嘉宁",
    "雨桐",
    "凯琳",
    "思雨",
    "秀英",
    "海燕",
    "佳慧",
]
GENDER_OLD = {
    "周明哲": "M",
    "沈佳怡": "F",
    "钱志远": "M",
    "许若曦": "F",
    "赵子龙": "M",
    "林静": "F",
    "王磊": "M",
    "刘洋": "M",
    "陈思远": "M",
    "黄婷": "F",
    "吴昊": "M",
    "孙悦": "F",
    "马俊杰": "M",
    "郭晓雯": "F",
    "何嘉欣": "F",
    "罗一鸣": "M",
    "梁雪": "F",
    "宋凯": "M",
    "韩冰": "F",
    "唐诗涵": "F",
    "冯毅": "M",
    "邓可": "F",
    "曹阳": "M",
    "彭丽": "F",
}


def read_csv(name: str) -> list[dict]:
    with open(os.path.join(ORIG, name + ".csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


EMP: dict[str, dict] = {}
USED_NAMES: set[str] = set()
USED_IDS: set[str] = set()


def pd(s: str) -> D | None:
    return D.fromisoformat(s) if s else None


def new_name(g: str) -> str:
    while True:
        n = rng.choice(SURN) + rng.choice(MALE if g == "M" else FEMALE)
        if n not in USED_NAMES:
            USED_NAMES.add(n)
            return n


def new_id(lo: int, hi: int) -> str:
    while True:
        i = f"EMP-{rng.randint(lo, hi)}"
        if i not in USED_IDS:
            USED_IDS.add(i)
            return i


def level_for_career(years: float, ladder: list[str]) -> str:
    cut = [(1, "P3"), (3, "P4"), (6, "P5"), (10, "P6"), (15, "P7"), (99, "P8")]
    for y, rec in cut:
        if years < y:
            return rec if rec in ladder else ladder[0]
    return ladder[-1]


def make_emp(eid, name, dept, city, level, mgr, hire, career, status, bmonth, gender, **kw) -> dict:
    e = dict(
        employee_id=eid,
        name=name,
        department_code=dept,
        city=city,
        job_level=level,
        manager_id=mgr,
        hire_date=hire,
        career_start_date=career,
        employment_status=status,
        birth_month=bmonth,
        gender=gender,
        employee_category=kw.get("category", "FULL_TIME"),
        work_hour_system=kw.get("whs", "STANDARD"),
        termination_date=kw.get("term"),
        regularization_date=None,
        education=kw.get("edu", "本科"),
        has_child_under_3=kw.get("child", False),
        original=kw.get("original", False),
    )
    EMP[eid] = e
    USED_IDS.add(eid)
    USED_NAMES.add(name)
    return e


def build_org() -> None:
    old = read_csv("employees")
    eng_team = {"EMP-2018": "ENG-PLT", "EMP-2046": "ENG-APP"}
    make_emp(
        "EMP-1001", "陆远航", "EXEC", "上海", "M4", "", D(2012, 6, 1), D(2001, 7, 1), "regular", 3, "M", edu="硕士"
    )
    for r in old:
        dept = r["department_code"]
        mgr = r["manager_id"]
        if r["employee_id"] in eng_team:
            dept = eng_team[r["employee_id"]]
        elif dept == "ENG" and mgr in eng_team:
            dept = eng_team[mgr]
        elif dept == "SAL" and mgr == "EMP-1020":
            dept = "SAL-N"
        if not mgr:
            mgr = "EMP-1001"
        status = r["employment_status"]
        e = make_emp(
            r["employee_id"],
            r["name"],
            dept,
            r["city"],
            r["job_level"],
            mgr,
            pd(r["hire_date"]),
            pd(r["career_start_date"]),
            status,
            int(r["birth_month"]),
            GENDER_OLD[r["name"]],
            edu=rng.choice(["本科", "本科", "硕士"]),
            original=True,
        )
        if r["employee_id"] == "EMP-3524":
            # hired 2026-03-09 with a 6-month probation: regularized 2026-09-10 (HR-EM-001 2.1/3.1)
            e["employment_status"] = "regular"
        if r["employee_id"] == "EMP-3112":
            e["has_child_under_3"] = True
    # new heads
    heads = [
        ("EMP-1040", "MKT", "上海", "M2", "EMP-1001", "F"),
        ("EMP-1045", "ADM", "上海", "M2", "EMP-1001", "M"),
        ("EMP-2060", "ENG-DATA", "上海", "M1", "EMP-1002", "M"),
        ("EMP-2071", "ENG-QA", "成都", "M1", "EMP-1002", "F"),
        ("EMP-2083", "PRD-UX", "上海", "M1", "EMP-1015", "F"),
        ("EMP-2090", "SAL-E", "上海", "M1", "EMP-1020", "M"),
        ("EMP-2095", "SAL-S", "深圳", "M1", "EMP-1020", "M"),
        ("EMP-2101", "CS-SUP", "成都", "M1", "EMP-1031", "M"),
    ]
    for eid, dept, city, lvl, mgr, g in heads:
        cy = rng.randint(11, 18)
        career = D(2026 - cy, 7, 1)
        hire = D(rng.randint(2014, 2020), rng.randint(1, 12), 1)
        hire = next_wd(hire) if hire >= D(2024, 7, 1) else hire
        make_emp(
            eid,
            new_name(g),
            dept,
            city,
            lvl,
            mgr,
            hire,
            career,
            "regular",
            rng.randint(1, 12),
            g,
            edu=rng.choice(["本科", "硕士", "硕士"]),
        )
    # staff
    plan = {
        "ENG-PLT": 14,
        "ENG-APP": 11,
        "ENG-DATA": 11,
        "ENG-QA": 9,
        "PRD": 6,
        "PRD-UX": 5,
        "HR": 6,
        "FIN": 6,
        "SAL-N": 6,
        "SAL-E": 9,
        "SAL-S": 7,
        "CS": 5,
        "CS-SUP": 10,
        "MKT": 7,
        "ADM": 4,
    }
    lv_w = [("P3", 10), ("P4", 26), ("P5", 30), ("P6", 20), ("P7", 11), ("P8", 3)]
    career_rng = {"P3": (0.2, 2), "P4": (1, 4), "P5": (3, 8), "P6": (5, 12), "P7": (8, 18), "P8": (12, 22)}
    for dept, n in plan.items():
        head = DEPT[dept][4]
        city = DEPT[dept][5]
        for _ in range(n):
            lvl = rng.choices([rec for rec, _ in lv_w], [w for _, w in lv_w])[0]
            if dept in ("ADM", "CS-SUP") and lvl in ("P7", "P8"):
                lvl = "P5"
            cy_f = rng.uniform(*career_rng[lvl])
            career = D(int(2026.5 - cy_f), 7, 1)
            earliest = max(career + dt.timedelta(days=30), D(2012, 9, 1))
            span = (D(2026, 9, 30) - earliest).days
            hire = earliest + dt.timedelta(days=int(span * (rng.random() ** 1.15)))
            hire = next_wd(hire) if hire >= D(2024, 7, 1) else hire
            g = rng.choice("MF")
            whs = "COMPREHENSIVE" if dept == "CS-SUP" else "STANDARD"
            age = 22 + (2026 - career.year)
            child = 28 <= age <= 40 and rng.random() < 0.14
            make_emp(
                new_id(3000, 3999),
                new_name(g),
                dept,
                city,
                lvl,
                head,
                hire,
                career,
                "regular",
                rng.randint(1, 12),
                g,
                whs=whs,
                child=child,
                edu=rng.choices(["大专", "本科", "硕士", "博士"], [1, 6, 3, 0.3])[0],
            )
    # interns (HR-BN-001 1.2): summer 2026
    for dept in ("ENG-PLT", "ENG-PLT", "ENG-DATA", "ENG-DATA", "MKT", "PRD-UX"):
        g = rng.choice("MF")
        hire = next_wd(D(2026, rng.choice([6, 7]), rng.randint(1, 20)))
        make_emp(
            new_id(5000, 5999),
            new_name(g),
            dept,
            DEPT[dept][5],
            "INT",
            DEPT[dept][4],
            hire,
            D(2027, 7, 1),
            "intern",
            rng.randint(1, 12),
            g,
            category="INTERN",
            edu="硕士",
        )
    # leavers (HR-EM-001 5-7)
    leavers = [
        e
        for e in EMP.values()
        if not e["original"]
        and e["job_level"].startswith("P")
        and e["employee_category"] == "FULL_TIME"
        and e["hire_date"] < D(2025, 3, 1)
    ]
    for e in rng.sample(leavers, 11):
        e["termination_date"] = prev_wd(D(2025, 3, 1) + dt.timedelta(days=rng.randint(0, 560)))
        e["employment_status"] = "resigned"
    # regularization: 6-month probation for 3-year contracts (HR-EM-001 2.1)
    for e in EMP.values():
        if e["employee_category"] == "INTERN":
            continue
        reg = add_months(e["hire_date"], 6) + dt.timedelta(days=1)
        if reg <= TODAY:
            e["regularization_date"] = reg
            if e["employment_status"] == "probation":
                e["employment_status"] = "regular"
        elif e["employment_status"] != "resigned":
            e["employment_status"] = "probation"
    # one probation employee terminated during probation (3 days notice, HR-EM-001 5.1)
    probs = [e for e in EMP.values() if e["employment_status"] == "probation" and not e["original"]]
    if probs:
        p = probs[0]
        p["termination_date"] = D(2026, 9, 30)
        p["employment_status"] = "resigned"
        note("probation_resignation", employee_id=p["employee_id"], name=p["name"])


def active_on(e: dict, d: D) -> bool:
    return e["hire_date"] <= d and (e["termination_date"] is None or d <= e["termination_date"])


def employed_wd(e: dict, a: D, b: D) -> list[D]:
    lo = max(a, e["hire_date"])
    hi = min(b, e["termination_date"] or b)
    return workdays(lo, hi) if lo <= hi else []


# ───────────────────────────── careers: levels, ratings, salary ─────────────────────────────
CYCLES = [
    ("2024-H2", D(2024, 12, 31), D(2025, 1, 20)),
    ("2025-H1", D(2025, 6, 30), D(2025, 7, 18)),
    ("2025-H2", D(2025, 12, 31), D(2026, 1, 22)),
    ("2026-H1", D(2026, 6, 30), D(2026, 7, 17)),
]
RATINGS = ["S", "A", "B", "C", "D"]
RATING_W = [8, 22, 58, 10, 2]
ADJ_PCT = {"S": 0.12, "A": 0.08, "B": 0.04, "C": 0.0, "D": 0.0}  # HR-CP-001 4.2
BONUS_MONTHS = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}  # HR-CP-001 5.1
COMPANY_FACTOR = {2024: 1.0, 2025: 0.9}  # HR-CP-001 5.1
REVIEWS: list[dict] = []
RATING: dict[tuple[str, str], str] = {}
SALARY: dict[str, list[dict]] = defaultdict(list)
PROMO: dict[str, list[tuple[D, str]]] = defaultdict(list)


def build_careers() -> None:
    for e in EMP.values():
        lvl = e["job_level"]
        if lvl == "INT":
            continue
        ladder = M_LADDER if lvl.startswith("M") else P_LADDER
        cy_at_hire = years_between(e["career_start_date"], e["hire_date"])
        entry = level_for_career(cy_at_hire, ladder)
        if lvl.startswith("M"):
            entry = rng.choice(["P6", "P7"]) if cy_at_hire > 6 else "P5"
            if lvl == "M4":
                entry = "M3"
        if ladder.index(entry) > ladder.index(lvl):
            entry = lvl
        end = e["termination_date"] or TODAY
        slots = [
            D(y, m, 1)
            for y in range(2013, 2027)
            for m in (4, 10)
            if add_months(e["hire_date"], 18) <= D(y, m, 1) <= end
        ]
        steps = ladder.index(lvl) - ladder.index(entry)
        # pick promotion dates with >= 18 months between them (HR-CP-001 3.2)
        fixed: list[D] = []
        for s in sorted(rng.sample(slots, len(slots))):
            if len(fixed) == steps:
                break
            if (not fixed or s >= add_months(fixed[-1], 18)) and (
                rng.random() < 0.45 or len(slots) - slots.index(s) <= (steps - len(fixed)) * 3
            ):
                fixed.append(s)
        # if fewer promotions fit, the employee joined at a higher level
        entry = ladder[ladder.index(lvl) - len(fixed)]
        cur = entry
        for s in fixed:
            cur = ladder[ladder.index(cur) + 1]
            PROMO[e["employee_id"]].append((s, cur))
        e["entry_level"] = entry
    # performance reviews (HR-PF-001)
    rid = 0
    for e in sorted(EMP.values(), key=lambda x: x["employee_id"]):
        if e["employee_category"] == "INTERN":
            continue
        talent = rng.gauss(0, 0.8)
        for cyc, cend, fin in CYCLES:
            if e["hire_date"] > cend - dt.timedelta(days=90):
                continue  # HR-PF-001 2.2: <3 months in the cycle -> not rated
            if e["termination_date"] and e["termination_date"] < fin:
                continue
            w = [max(0.2, RATING_W[i] * math.exp(-talent * (i - 2) * 0.6)) for i in range(5)]
            rating = rng.choices(RATINGS, w)[0]
            # a promotion in Apr/Oct requires S/A in the preceding cycle (HR-CP-001 3.2)
            for s, _ in PROMO[e["employee_id"]]:
                if cend < s <= cend + dt.timedelta(days=290) and rating not in ("S", "A"):
                    rating = "A"
            rid += 1
            changed = rng.random() < 0.12
            REVIEWS.append(
                dict(
                    review_id=f"PR-{cyc}-{rid:04d}",
                    employee_id=e["employee_id"],
                    review_cycle=cyc,
                    cycle_end_date=cend,
                    rating=rating,
                    pre_calibration_rating=(rng.choice([r for r in "SABC" if r != rating]) if changed else rating),
                    reviewer_id=e["manager_id"] or "EMP-1001",
                    finalized_date=fin,
                )
            )
            RATING[(e["employee_id"], cyc)] = rating
    # salary history (HR-CP-001)
    for e in EMP.values():
        lvl0 = e.get("entry_level", e["job_level"])
        lo, hi = LV[lvl0][3], LV[lvl0][4]
        base = round((lo + (hi - lo) * rng.uniform(0.05, 0.45)) / 100) * 100
        hist = [dict(effective_date=e["hire_date"], job_level=lvl0, base=base, allow=LV[lvl0][5], reason="HIRE")]
        if e["employee_category"] != "INTERN":
            promos = dict(PROMO[e["employee_id"]])
            end = e["termination_date"] or TODAY
            lvl = lvl0
            for y in range(e["hire_date"].year, 2027):
                for m in (4, 10):
                    d = D(y, m, 1)
                    if d <= e["hire_date"] or d > end:
                        continue
                    reason, pct = None, 0.0
                    if m == 4 and e["hire_date"] <= D(y - 1, 9, 30):  # HR-CP-001 4.1
                        r = RATING.get((e["employee_id"], f"{y - 1}-H2"))
                        if r is None and y <= 2024:  # history before the first stored cycle (2024-H2)
                            r = rng.choices(RATINGS, RATING_W)[0]
                        pct = ADJ_PCT[r] if r else 0.0  # unrated -> no adjustment (HR-CP-001 4.3)
                        reason = "ANNUAL_ADJUST" if pct > 0 else None
                    if d in promos:
                        lvl = promos[d]
                        new = max(base * (1 + pct) * 1.12, LV[lvl][3])
                        reason = "PROMOTION"
                    elif reason:
                        new = base * (1 + pct)
                    else:
                        continue
                    new = min(new, LV[lvl][4] * 1.1)
                    base = round(new / 100) * 100
                    hist.append(dict(effective_date=d, job_level=lvl, base=base, allow=LV[lvl][5], reason=reason))
            assert lvl == e["job_level"], (e["employee_id"], lvl, e["job_level"])
        SALARY[e["employee_id"]] = hist


def salary_on(eid: str, d: D) -> dict:
    cur = None
    for h in SALARY[eid]:
        if h["effective_date"] <= d:
            cur = h
    return cur or SALARY[eid][0]


def mgr_on(e: dict) -> str:
    return e["manager_id"] or "EMP-1001"


def dept_head(e: dict) -> str:
    top = TOP[e["department_code"]]
    h = DEPT[top][4]
    return h if h != e["employee_id"] else "EMP-1001"


# ───────────────────────────── leave ─────────────────────────────
LEAVES: list[dict] = []
LEAVE_DAYS: dict[str, dict[D, tuple[str, float, str]]] = defaultdict(dict)  # eid -> date -> (type, frac, req)
REASON = {
    "ANNUAL": ["家庭旅行", "回老家探亲", "个人休整", "陪家人", "出国旅行", "处理个人事务"],
    "SICK": ["感冒发烧", "肠胃炎", "就医复查", "腰椎不适", "牙科手术"],
    "PERSONAL": ["办理房产手续", "孩子入学", "家中装修", "处理家庭事务"],
    "COMP": ["加班调休"],
    "BIRTHDAY": ["生日假"],
    "PARENTAL": ["陪伴孩子"],
    "MARRIAGE": ["结婚"],
    "PATERNITY": ["配偶生育"],
    "MATERNITY": ["生育"],
    "BEREAVEMENT": ["家中老人去世"],
}
SEQ: defaultdict[int, int] = defaultdict(int)


def lr_id(year: int) -> str:
    SEQ[year] += 1
    base = 200 if year == 2026 else 0
    return f"LR-{year}-{base + SEQ[year]:04d}"


def free(eid: str, ds: list[D]) -> bool:
    return all(d not in LEAVE_DAYS[eid] for d in ds)


def add_leave(e, ltype, start, n, status=None, frac=1.0, cal_days=False, submitted=None, cert=None, rid=None):
    eid = e["employee_id"]
    if cal_days:
        ds = [start + dt.timedelta(days=i) for i in range(n)]
        dcount = float(n)
        wds = [d for d in ds if is_wd(d)]
    else:
        start = next_wd(start)
        end = add_wd(start, n - 1)
        ds = workdays(start, end)
        wds = ds
        dcount = n * frac if n == 1 else float(n)
    end = ds[-1]
    if not free(eid, wds) or not active_on(e, start) or not active_on(e, end):
        return None
    if submitted is None:
        lead = 3 if n <= 3 else (10 if n <= 10 else 20)  # HR-LV-001 4.1
        if ltype in ("SICK",):
            submitted = start if rng.random() < 0.3 else end + dt.timedelta(days=rng.randint(0, 2))
            submitted = min(submitted, CUTOFF)
        else:
            submitted = sub_wd(start, lead + rng.randint(0, 8))
        submitted = max(submitted, e["hire_date"])
    if submitted > CUTOFF:
        return None
    if status is None:
        if start > CUTOFF:
            status = rng.choices(["PENDING", "APPROVED"], [6, 4])[0]
        else:
            status = rng.choices(["APPROVED", "REJECTED", "WITHDRAWN"], [94, 3, 3])[0]
    if cert is None:
        cert = (rng.random() > 0.12) if (ltype == "SICK" and n >= 2) else None  # HR-LV-001 6.2
    rid = rid or lr_id(start.year)
    approver = mgr_on(e)
    if n > 10 and ltype == "ANNUAL":
        approver = dept_head(e)
    row = dict(
        request_id=rid,
        employee_id=eid,
        leave_type=ltype,
        start_date=start,
        end_date=end,
        days=dcount,
        status=status,
        approver_id=approver,
        submitted_date=submitted,
        reason=rng.choice(REASON[ltype]),
        certificate_submitted=cert,
    )
    LEAVES.append(row)
    if status in ("APPROVED", "PENDING"):
        for d in wds:
            LEAVE_DAYS[eid][d] = (ltype, frac if n == 1 else 1.0, rid if status == "APPROVED" else "")
    if ltype == "SICK" and n >= 2 and cert is False and status == "APPROVED":
        note("sick_without_certificate", request_id=rid, employee_id=eid, days=dcount)
    return row


def annual_quota(e: dict, year: int) -> tuple[float, float, float]:
    """(statutory, company, total) per HR-LV-001 1.2-1.5 (2025 rules: company leave flat 5, HR-GEN-000 5)."""
    jan1 = D(year, 1, 1)
    cy = full_years(e["career_start_date"], jan1)
    st = 0 if cy < 1 else 5 if cy < 10 else 10 if cy < 20 else 15
    if year >= 2026:
        ten = full_years(e["hire_date"], jan1)
        co = 5 if ten < 3 else 7 if ten < 5 else 10
    else:
        co = 5
    if e["hire_date"] > jan1:
        frac = ((D(year, 12, 31) - e["hire_date"]).days + 1) / 365
        # statutory needs 12 months of total career (HR-LV-001 3.1); prorate both parts
        cy_h = full_years(e["career_start_date"], e["hire_date"])
        st_full = 0 if cy_h < 1 else st
        tot = floor_half(frac * (st_full + co))
        st_p = floor_half(frac * st_full)
        return st_p, tot - st_p, tot
    return float(st), float(co), float(st + co)


def build_leaves() -> None:
    old = read_csv("leave_requests")
    for r in old:
        e = EMP[r["employee_id"]]
        row = dict(
            request_id=r["request_id"],
            employee_id=r["employee_id"],
            leave_type=r["leave_type"],
            start_date=pd(r["start_date"]),
            end_date=pd(r["end_date"]),
            days=float(r["days"]),
            status=r["status"],
            approver_id=r["approver_id"],
            submitted_date=pd(r["submitted_date"]),
            reason=rng.choice(REASON["ANNUAL"]),
            certificate_submitted=None,
        )
        LEAVES.append(row)
        if row["status"] in ("APPROVED", "PENDING"):
            for d in workdays(row["start_date"], row["end_date"]):
                LEAVE_DAYS[r["employee_id"]][d] = (
                    "ANNUAL",
                    1.0 if row["days"] >= 1 else row["days"],
                    r["request_id"] if row["status"] == "APPROVED" else "",
                )
    SEQ[2026] = 21  # continue after LR-2026-0121 → new ones start at LR-2026-0222
    originals = {e["employee_id"] for e in EMP.values() if e["original"]}
    for e in sorted(EMP.values(), key=lambda x: x["employee_id"]):
        if e["employee_category"] == "INTERN":
            continue
        eid = e["employee_id"]
        for year in (2025, 2026):
            if not active_on(e, D(year, 12, 31)) and not (e["termination_date"] and e["termination_date"].year == year):
                continue
            lo = max(D(year, 1, 2), e["hire_date"])
            hi = min(D(year, 12, 23), e["termination_date"] or D(year, 12, 23))
            if lo >= hi:
                continue
            # life events
            if e["has_child_under_3"] and rng.random() < 0.7:
                add_leave(e, "PARENTAL", lo + dt.timedelta(days=rng.randint(10, 300)), rng.choice([1, 2, 3]))
            # birthday leave (HR-LV-001 10, new in 2026; regular employees only)
            if year == 2026 and rng.random() < 0.75:
                bd = D(2026, e["birth_month"], rng.randint(1, 25))
                if e["regularization_date"] and e["regularization_date"] <= bd and lo <= bd <= hi:
                    add_leave(e, "BIRTHDAY", bd, 1)
            # sick (HR-LV-001 6)
            for _ in range(rng.choices([0, 1, 2, 3], [35, 35, 20, 10])[0]):
                d = lo + dt.timedelta(days=rng.randint(0, max(1, (hi - lo).days)))
                add_leave(e, "SICK", d, rng.choices([1, 2, 3], [60, 30, 10])[0])
            if rng.random() < 0.08:
                add_leave(
                    e, "PERSONAL", lo + dt.timedelta(days=rng.randint(0, max(1, (hi - lo).days))), rng.choice([1, 2])
                )
            if eid in originals and year == 2026:
                continue  # keep the original 2026 annual-leave balances untouched
            st, co, tot = annual_quota(e, year)
            target = tot * (rng.uniform(0.55, 1.0) if year == 2025 else rng.uniform(0.35, 0.95))
            used, tries = 0.0, 0
            while used < target - 0.4 and tries < 40:
                tries += 1
                left = target - used
                n = rng.choices([1, 2, 3, 4, 5, 8], [30, 20, 18, 12, 14, 6])[0]
                n = int(min(n, max(1, math.floor(left))))
                frac = 0.5 if (n == 1 and (left < 1 or rng.random() < 0.15)) else 1.0
                d = lo + dt.timedelta(days=rng.randint(0, max(1, (hi - lo).days)))
                row = add_leave(e, "ANNUAL", d, n, frac=frac)
                if row and row["status"] in ("APPROVED", "PENDING"):
                    used += row["days"]
    # rare life events
    pool = [e for e in EMP.values() if e["employee_category"] == "FULL_TIME" and not e["termination_date"]]
    for e in rng.sample(pool, 2):
        add_leave(e, "MARRIAGE", D(2025, rng.randint(4, 11), rng.randint(1, 20)), 10)
    for e in [p for p in pool if p["gender"] == "M" and p["has_child_under_3"]][:2]:
        add_leave(e, "PATERNITY", D(2025, rng.randint(2, 10), rng.randint(1, 20)), 15)
    moms = [p for p in pool if p["gender"] == "F" and p["has_child_under_3"] and p["hire_date"] < D(2024, 6, 1)][:1]
    for e in moms:
        add_leave(e, "MATERNITY", D(2025, 3, 3), 158, cal_days=True, status="APPROVED")
    for e in rng.sample(pool, 3):
        add_leave(e, "BEREAVEMENT", D(2026, rng.randint(1, 9), rng.randint(1, 25)), rng.choice([3, 5]))
    # deliberately late annual-leave submissions (violate HR-LV-001 4.1)
    late = [
        rec
        for rec in LEAVES
        if rec["leave_type"] == "ANNUAL"
        and rec["status"] == "APPROVED"
        and rec["days"] >= 4
        and rec["start_date"] > D(2025, 3, 1)
        and not EMP[rec["employee_id"]]["original"]
    ]
    for rec in rng.sample(late, min(4, len(late))):
        rec["submitted_date"] = sub_wd(rec["start_date"], 1)
        note(
            "late_annual_leave_submission",
            request_id=rec["request_id"],
            employee_id=rec["employee_id"],
            days=rec["days"],
            start=str(rec["start_date"]),
            submitted=str(rec["submitted_date"]),
        )


def build_comp_leave(ots: list[dict]) -> None:
    """COMP leave from approved COMP_LEAVE overtime; 4-hour units, within 3 months (HR-AT-001 5.2)."""
    bank = defaultdict(list)
    for o in ots:
        if o["approval_status"] == "APPROVED" and o["compensation_method"] == "COMP_LEAVE":
            bank[o["employee_id"]].append(o)
    for eid, lst in bank.items():
        e = EMP[eid]
        hours = 0.0
        for o in sorted(lst, key=lambda x: x["work_date"]):
            hours += o["overtime_hours"]
            if hours >= 4 and rng.random() < 0.5:
                units = int(hours // 4)
                use = min(units, 2)
                d = o["work_date"] + dt.timedelta(days=rng.randint(5, 80))
                if d > CUTOFF + dt.timedelta(days=20):
                    continue
                row = add_leave(e, "COMP", d, 1, frac=0.5 if use == 1 else 1.0)
                if row and row["status"] in ("APPROVED", "PENDING"):
                    hours -= use * 4


# ───────────────────────────── overtime ─────────────────────────────
OTS: list[dict] = []


def t2m(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def m2t(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def ot_meta(
    e, wd: D, start: str, end: str, hours: float, status: str, comp: str | None = None, submitted: D | None = None
) -> dict:
    c = CAL[wd]
    otype = "STATUTORY_HOLIDAY" if c["statutory"] else ("REST_DAY" if not c["workday"] else "WORKDAY")
    if comp is None:
        if otype == "STATUTORY_HOLIDAY":
            comp = "PAID"  # HR-AT-001 5.4
        elif e["work_hour_system"] == "COMPREHENSIVE":
            comp = "COMP_LEAVE"
        else:
            comp = rng.choices(["COMP_LEAVE", "PAID"], [55, 45] if otype == "WORKDAY" else [45, 55])[0]
    if submitted is None:
        submitted = wd - dt.timedelta(days=rng.randint(0, 3))
    return dict(
        employee_id=e["employee_id"],
        work_date=wd,
        end_time=end,
        overtime_hours=hours,
        approval_status=status,
        approver_id=mgr_on(e),
        start_time=start,
        overtime_type=otype,
        compensation_method=comp,
        submitted_date=submitted,
        reason=rng.choice(
            [
                "版本发布",
                "线上故障处理",
                "客户演示准备",
                "季度结账",
                "项目交付",
                "大促保障",
                "投标材料准备",
                "数据迁移",
                "年度预算编制",
                "客户现场支持",
            ]
        ),
    )


def build_overtime() -> None:
    old = read_csv("overtime_records")
    for r in old:
        e = EMP[r["employee_id"]]
        wd = D.fromisoformat(r["work_date"])
        hrs = float(r["overtime_hours"])
        start = m2t(t2m(r["end_time"]) - int(hrs * 60))
        row = ot_meta(
            e, wd, start, r["end_time"], hrs, r["approval_status"], comp="PAID", submitted=wd - dt.timedelta(days=1)
        )
        row["approver_id"] = r["approver_id"]
        row["record_id"] = r["record_id"]
        OTS.append(row)
    # intensity by department/month
    busy = {
        "ENG": {3, 6, 9, 11, 12},
        "SAL": {3, 6, 9, 12},
        "CS": {1, 6, 11, 12},
        "FIN": {1, 4, 7, 10, 12},
        "HR": {1, 3, 7},
        "PRD": {3, 9},
        "MKT": {5, 10, 11},
        "ADM": {1},
        "EXEC": set(),
    }
    base_rate = {
        "ENG": 0.06,
        "SAL": 0.035,
        "CS": 0.045,
        "FIN": 0.03,
        "HR": 0.02,
        "PRD": 0.03,
        "MKT": 0.03,
        "ADM": 0.02,
        "EXEC": 0.0,
    }
    seq: defaultdict[int, int] = defaultdict(int)
    taken = {(o["employee_id"], o["work_date"]) for o in OTS}
    for e in sorted(EMP.values(), key=lambda x: x["employee_id"]):
        if e["employee_category"] == "INTERN" or e["job_level"] in ("M3", "M4"):
            continue
        top = TOP[e["department_code"]]
        grind = rng.lognormvariate(0, 0.6)
        for d in days(max(DATA_START, e["hire_date"]), min(CUTOFF, e["termination_date"] or CUTOFF)):
            if e["original"] and d >= D(2026, 10, 1):
                continue  # October 2026 for the original 24 stays exactly as before
            if d in LEAVE_DAYS[e["employee_id"]]:
                continue
            c = CAL[d]
            p = base_rate[top] * grind * (2.2 if d.month in busy[top] else 1.0)
            if not c["workday"]:
                p *= 0.18
            if e["work_hour_system"] == "COMPREHENSIVE" and not c["statutory"]:
                p *= 0.3 if c["workday"] else 0.0
            if c["statutory"]:
                p = 0.12 if top in ("CS", "ENG") else 0.01
            if rng.random() >= p or (e["employee_id"], d) in taken:
                continue
            if c["workday"]:
                startm = 18 * 60 + rng.choice([0, 0, 15, 30, 60])
                hrs = rng.choices([1.5, 2, 2.5, 3, 3.5, 4, 5], [12, 20, 18, 18, 12, 12, 8])[0]
            else:
                startm = rng.choice([9, 10, 13, 14]) * 60 + rng.choice([0, 30])
                hrs = rng.choices([3, 4, 5, 6, 8], [15, 30, 20, 20, 15])[0]
            end = m2t(startm + int(hrs * 60))
            recent = d > CUTOFF - dt.timedelta(days=12)
            status = rng.choices(["APPROVED", "PENDING", "REJECTED"], [70, 25, 5] if recent else [94, 0, 6])[0]
            row = ot_meta(e, d, m2t(startm), end, float(hrs), status)
            seq[d.year] += 1
            row["record_id"] = f"OT-{d.year}-{(100 if d.year == 2026 else 0) + seq[d.year]:04d}"
            OTS.append(row)
            taken.add((e["employee_id"], d))
    # after-the-fact submissions: not counted (HR-AT-001 5.1)
    cand = [o for o in OTS if o["approval_status"] == "REJECTED" and o["work_date"].year == 2026]
    for o in rng.sample(cand, min(5, len(cand))):
        o["submitted_date"] = o["work_date"] + dt.timedelta(days=rng.randint(3, 9))
        note("overtime_submitted_after_the_fact", record_id=o["record_id"], employee_id=o["employee_id"])


# ───────────────────────────── attendance (2026-07-01 .. cutoff) ─────────────────────────────
ATT: list[dict] = []
ATT_START = D(2026, 7, 1)
REMOTE_REQ: list[dict] = []


def build_remote_requests() -> dict[str, list[tuple[D, D, int]]]:
    approved = defaultdict(list)
    pool = [
        e
        for e in EMP.values()
        if e["employee_category"] == "FULL_TIME"
        and e["employment_status"] == "regular"
        and not e["termination_date"]
        and e["job_level"] not in ("M2", "M3", "M4")
    ]
    picks = rng.sample(pool, 9)
    reasons = ["照顾术后家人", "孕期身体原因", "子女年幼需接送", "本人康复期", "照顾年迈父母"]
    for i, e in enumerate(picks):
        start = D(2026, rng.choice([4, 5, 6, 7, 8]), rng.randint(1, 20))
        end = add_months(start, 3) - dt.timedelta(days=1)  # HR-AT-001 4.2: <= 3 months
        dpw = rng.choice([3, 3, 4, 5])
        status = "APPROVED"
        mgr_ok, hrbp_ok = "APPROVED", "APPROVED"
        if i == 7:
            mgr_ok, hrbp_ok, status = "APPROVED", "PENDING", "PENDING"  # only one approval: not effective
        if i == 8:
            mgr_ok, hrbp_ok, status = "APPROVED", "REJECTED", "REJECTED"
        REMOTE_REQ.append(
            dict(
                request_id=f"RW-2026-{i + 1:03d}",
                employee_id=e["employee_id"],
                start_date=start,
                end_date=end,
                remote_days_per_week=dpw,
                reason=rng.choice(reasons),
                manager_approval=mgr_ok,
                hrbp_approval=hrbp_ok,
                status=status,
                submitted_date=start - dt.timedelta(days=rng.randint(3, 10)),
            )
        )
        if status == "APPROVED":
            approved[e["employee_id"]].append((start, end, dpw))
    return approved


def build_attendance() -> None:
    approved = build_remote_requests()
    ot_by = {(o["employee_id"], o["work_date"]): o for o in OTS}
    actives = [e for e in EMP.values() if e["employee_category"] in ("FULL_TIME", "INTERN")]
    latecomers = set(rng.sample([e["employee_id"] for e in actives if e["employment_status"] == "regular"], 6))
    over_remote = set(
        rng.sample(
            [
                e["employee_id"]
                for e in actives
                if e["employment_status"] == "regular" and e["employee_id"] not in approved
            ],
            5,
        )
    )
    prob_remote = [e["employee_id"] for e in actives if e["employment_status"] == "probation"][:1]
    for eid in sorted(over_remote):
        note("remote_over_2_days_without_approval", employee_id=eid)
    for eid in prob_remote:
        note("probation_remote_work", employee_id=eid)
    for eid in sorted(latecomers):
        note("frequent_late_arrival", employee_id=eid)
    # remote rejected/pending requesters keep working remote anyway (policy breach)
    for r in REMOTE_REQ:
        if r["status"] != "APPROVED":
            over_remote.add(r["employee_id"])
            note("remote_request_not_approved_but_remote", employee_id=r["employee_id"], request_id=r["request_id"])
    fake_ot: list[dict] = []
    for e in sorted(actives, key=lambda x: x["employee_id"]):
        eid = e["employee_id"]
        pref = rng.sample(range(5), 2)  # usual remote weekdays
        normal_remote = rng.choices([0, 1, 2], [30, 40, 30])[0]
        if e["employment_status"] == "probation" or e["employee_category"] == "INTERN":
            normal_remote = 0
        if TOP[e["department_code"]] in ("ADM",) or e["job_level"] in ("M3", "M4"):
            normal_remote = 0
        for d in employed_wd(e, ATT_START, CUTOFF):
            row = dict(
                employee_id=eid,
                work_date=d,
                work_mode="OFFICE",
                check_in="",
                check_out="",
                attendance_status="NORMAL",
                punch_corrected=False,
                leave_request_id="",
            )
            lv = LEAVE_DAYS[eid].get(d)
            if lv and lv[2] and lv[1] >= 1.0:
                row.update(attendance_status="ON_LEAVE", work_mode="", leave_request_id=lv[2])
                ATT.append(row)
                continue
            wk = d.weekday()
            remote = False
            if d.weekday() < 5:
                if any(a <= d <= b for a, b, n in approved.get(eid, [])):
                    n = max(n for a, b, n in approved[eid] if a <= d <= b)
                    remote = wk < n
                elif eid in over_remote:
                    remote = wk in (0, 2, 4)
                elif eid in prob_remote:
                    remote = wk in (0, 4)
                else:
                    remote = wk in pref[:normal_remote]
            row["work_mode"] = "REMOTE" if remote else "OFFICE"
            late = eid in latecomers and rng.random() < 0.35
            cin = (
                (10 * 60 + rng.randint(5, 50))
                if late
                else int(min(max(rng.gauss(9 * 60 + 10, 22), 8 * 60), 9 * 60 + 58))
            )
            cout = cin + 9 * 60 + rng.randint(-5, 50)
            status = "LATE" if late else "NORMAL"
            if rng.random() < 0.015:
                cout = 15 * 60 + rng.randint(0, 50)
                status = "EARLY_LEAVE"
            o = ot_by.get((eid, d))
            if o:
                cout = t2m(o["end_time"])
                if (
                    o["approval_status"] == "APPROVED"
                    and o["overtime_hours"] >= 3
                    and o["work_date"] >= ATT_START
                    and len(fake_ot) < 3
                    and rng.random() < 0.08
                    and not e["original"]
                ):
                    cout = 18 * 60 + rng.randint(5, 40)  # punched out long before the claimed OT end
                    fake_ot.append(o)
                    note(
                        "overtime_end_time_not_supported_by_attendance",
                        record_id=o["record_id"],
                        employee_id=eid,
                        ot_end=o["end_time"],
                        check_out=m2t(cout),
                    )
            if lv and lv[1] < 1.0:  # half-day leave in the morning
                cin = 13 * 60 + rng.randint(30, 59)
                cout = max(cout, 18 * 60 + rng.randint(0, 40))
                status = "NORMAL"
                row["leave_request_id"] = lv[2]
            row["check_in"], row["check_out"], row["attendance_status"] = m2t(cin), m2t(min(cout, 23 * 60 + 59)), status
            if rng.random() < 0.012:
                row["check_out"] = ""
                row["attendance_status"] = "MISSING_PUNCH"
                if rng.random() < 0.6:
                    row["check_out"] = m2t(cout)
                    row["punch_corrected"] = True
                    row["attendance_status"] = "NORMAL"
            ATT.append(row)
    # one unexcused absence (HR-AT-001 6.2)
    cand = [
        a
        for a in ATT
        if a["attendance_status"] == "NORMAL"
        and a["work_date"] > D(2026, 9, 1)
        and not EMP[a["employee_id"]]["original"]
    ]
    a = rng.choice(cand)
    a.update(check_in="", check_out="", attendance_status="ABSENT", work_mode="OFFICE")
    note("unexcused_absence", employee_id=a["employee_id"], date=str(a["work_date"]))


# ───────────────────────────── business trips & expenses ─────────────────────────────
TRIPS: list[dict] = []
EXP: list[dict] = []
HOTEL_CAP = {"P": (600, 450, 350), "S": (800, 600, 450), "M3": (1200, 900, 700)}
MEAL_RATE = {1: 120, 2: 100, 3: 80}


def hotel_cap(level: str, tier: int) -> int:
    if level in ("M3", "M4"):
        k = "M3"
    elif level in ("P7", "P8", "P9", "M1", "M2"):
        k = "S"
    else:
        k = "P"
    return HOTEL_CAP[k][tier - 1]


def next_thursday_pay(reviewed: dt.datetime) -> D:
    """HR-EX-001 7.1: paid every Thursday; reviewed after Wed 18:00 rolls to next week's Thursday."""
    d = reviewed.date()
    days_to_thu = (3 - d.weekday()) % 7
    thu = d + dt.timedelta(days=days_to_thu)
    cutoff = dt.datetime.combine(thu - dt.timedelta(days=1), dt.time(18, 0))
    if reviewed >= cutoff:
        thu += dt.timedelta(days=7)
    return thu


EXP_SEQ: defaultdict[int, int] = defaultdict(int)


def add_claim(
    e,
    cat,
    exp_date,
    amount,
    approved_amount=None,
    desc="",
    ot=None,
    trip=None,
    submitted=None,
    nights=None,
    status=None,
):
    eid = e["employee_id"]
    if submitted is None:
        lim = 30 if cat.startswith("TRAVEL") else 60
        submitted = exp_date + dt.timedelta(days=min(lim - 1, int(rng.expovariate(1 / 9))))
    if submitted > CUTOFF or (e["termination_date"] and submitted > e["termination_date"]):
        return None
    EXP_SEQ[exp_date.year] += 1
    cid = f"EX-{exp_date.year}-{EXP_SEQ[exp_date.year]:05d}"
    approved_amount = amount if approved_amount is None else approved_amount
    mgr = mgr_on(e)
    path = [mgr]
    if amount > 2000:
        path.append(dept_head(e))
    if amount > 10000:
        path.append("FIN-BP")
    if status is None:
        status = "PAID"
    appr_date = add_wd(next_wd(submitted), rng.randint(1, 4))
    reviewed = dt.datetime.combine(
        add_wd(appr_date, rng.randint(0, 2)), dt.time(rng.randint(9, 19), rng.choice([0, 15, 30, 45]))
    )
    paid = next_thursday_pay(reviewed)
    if status == "PAID" and paid > CUTOFF:
        status = "APPROVED" if reviewed.date() <= CUTOFF else "SUBMITTED"
    if status in ("SUBMITTED",):
        appr_date, reviewed = None, None
    if status == "REJECTED":
        approved_amount, reviewed = 0.0, None
    EXP.append(
        dict(
            claim_id=cid,
            employee_id=eid,
            category=cat,
            expense_date=exp_date,
            amount=r2(amount),
            approved_amount=r2(approved_amount),
            submitted_date=submitted,
            status=status,
            approval_path=">".join(path),
            approved_date=appr_date if status != "REJECTED" else None,
            finance_reviewed_at=reviewed.strftime("%Y-%m-%d %H:%M")
            if reviewed and status in ("APPROVED", "PAID")
            else "",
            paid_date=paid if status == "PAID" else None,
            related_overtime_id=ot or "",
            related_trip_id=trip or "",
            nights=nights,
            description=desc,
        )
    )
    return EXP[-1]


def build_trips_and_expenses() -> None:
    trip_rate = {
        "SAL": 0.9,
        "CS": 0.5,
        "ENG": 0.08,
        "PRD": 0.2,
        "MKT": 0.35,
        "FIN": 0.1,
        "HR": 0.12,
        "ADM": 0.05,
        "EXEC": 0.8,
    }
    dests = list(CITY_TIER)
    tseq = 0
    for e in sorted(EMP.values(), key=lambda x: x["employee_id"]):
        if e["employee_category"] == "INTERN":
            continue
        top = TOP[e["department_code"]]
        lvl = e["job_level"]
        start = max(DATA_START, e["hire_date"])
        end = min(CUTOFF - dt.timedelta(days=3), e["termination_date"] or CUTOFF)
        months = max(0, (end - start).days / 30)
        for _ in range(int(rng.gauss(trip_rate[top] * months, 1.2) if months else 0)):
            dep = next_wd(start + dt.timedelta(days=rng.randint(0, max(1, (end - start).days))))
            if dep > end:
                continue
            nights = rng.choices([1, 2, 3, 4], [35, 35, 20, 10])[0]
            ret = dep + dt.timedelta(days=nights)
            dest = rng.choice([c for c in dests if c != e["city"]])
            tier = CITY_TIER[dest]
            tseq += 1
            tid = f"TR-{dep.year}-{tseq:04d}"
            dep_t = rng.choice(["07:30", "09:15", "13:40", "16:20"])
            ret_t = rng.choice(["11:10", "15:30", "18:45", "20:30"])
            appr = "APPROVED"
            pre = dep - dt.timedelta(days=rng.randint(2, 10))
            if rng.random() < 0.03:
                pre = dep + dt.timedelta(days=rng.randint(1, 2))  # emergency trip, filed afterwards (FIN-TR-001 1.3)
            TRIPS.append(
                dict(
                    trip_id=tid,
                    employee_id=eid_(e),
                    origin_city=e["city"],
                    destination_city=dest,
                    city_tier=tier,
                    depart_date=dep,
                    depart_time=dep_t,
                    return_date=ret,
                    return_time=ret_t,
                    purpose=rng.choice(
                        ["客户拜访", "项目交付", "售前演示", "行业展会", "客户培训", "供应商审计", "投标答辩"]
                    ),
                    approval_status=appr,
                    submitted_date=pre,
                    approver_id=mgr_on(e),
                )
            )
            cap = hotel_cap(lvl, tier)
            # hotel
            over = rng.random() < 0.025
            nightly = cap * (rng.uniform(1.05, 1.35) if over else rng.uniform(0.6, 0.98))
            amount = round(nightly) * nights
            add_claim(
                e,
                "TRAVEL_HOTEL",
                ret,
                amount,
                approved_amount=min(amount, cap * nights),
                desc=f"{dest}住宿{nights}晚",
                trip=tid,
                nights=nights,
            )
            if over:
                note(
                    "hotel_over_cap",
                    trip_id=tid,
                    employee_id=e["employee_id"],
                    level=lvl,
                    city=dest,
                    nightly=round(nightly),
                    cap=cap,
                )
            # meal allowance (FIN-TR-001 5.1/5.2): half day if depart >= 12:00 or return < 12:00
            n_days = nights + 1 - (0.5 if dep_t >= "12:00" else 0) - (0.5 if ret_t < "12:00" else 0)
            add_claim(e, "TRAVEL_MEAL_ALLOWANCE", ret, MEAL_RATE[tier] * n_days, desc=f"伙食补助{n_days}天", trip=tid)
            # intercity transport
            fare = (
                rng.choice([553, 667, 934, 1280, 1650, 2140]) * 2
                if rng.random() < 0.5
                else rng.choice([310, 420, 557]) * 2
            )
            add_claim(e, "TRAVEL_INTERCITY", ret, fare, desc="往返交通", trip=tid)
            # local transport in destination (<=150/day)
            loc = sum(rng.randint(20, 120) for _ in range(nights + 1))
            add_claim(
                e,
                "TRAVEL_LOCAL",
                ret,
                loc,
                approved_amount=min(loc, 150 * (nights + 1)),
                desc="目的地市内交通",
                trip=tid,
            )
    # overtime meals / taxis (HR-EX-001 2): taxi needs end >= 21:00 and an approved OT record
    for o in OTS:
        e = EMP[o["employee_id"]]
        if o["approval_status"] == "REJECTED":
            continue
        end = t2m(o["end_time"])
        cap_meal = 40 if o["work_date"].year == 2025 else 50  # 2025 rule: 40 (HR-GEN-000 5)
        meal_ok = (o["overtime_type"] == "WORKDAY" and end >= 20 * 60) or (
            o["overtime_type"] != "WORKDAY" and o["overtime_hours"] >= 4
        )
        if meal_ok and rng.random() < 0.55:
            amt = rng.uniform(22, cap_meal)
            if rng.random() < 0.006:
                amt = cap_meal + rng.uniform(5, 30)
                note(
                    "overtime_meal_over_cap",
                    employee_id=e["employee_id"],
                    record_id=o["record_id"],
                    amount=round(amt, 2),
                    cap=cap_meal,
                )
            add_claim(
                e,
                "OT_MEAL",
                o["work_date"],
                amt,
                approved_amount=min(amt, cap_meal),
                ot=o["record_id"],
                desc="加班餐费",
            )
        if (
            end >= 21 * 60
            and o["overtime_type"] == "WORKDAY"
            and rng.random() < 0.6
            and o["approval_status"] == "APPROVED"
        ):
            amt = rng.uniform(28, 140)
            add_claim(
                e, "OT_TAXI", o["work_date"], amt, approved_amount=min(amt, 150), ot=o["record_id"], desc="加班打车回家"
            )
    # policy violations: taxi without an approved OT / before 21:00
    staff = [
        e
        for e in EMP.values()
        if e["employee_category"] == "FULL_TIME" and not e["termination_date"] and not e["original"]
    ]
    for e in rng.sample(staff, 3):
        d = next_wd(D(2026, rng.randint(7, 9), rng.randint(1, 25)))
        c = add_claim(e, "OT_TAXI", d, rng.uniform(60, 130), desc="加班打车回家", status="REJECTED")
        if c:
            note("ot_taxi_without_approved_overtime", claim_id=c["claim_id"], employee_id=e["employee_id"])
    rejected_ot = [
        o
        for o in OTS
        if o["approval_status"] == "REJECTED" and t2m(o["end_time"]) >= 21 * 60 and o["work_date"] >= D(2026, 1, 1)
    ]
    for o in rejected_ot[:2]:
        c = add_claim(
            EMP[o["employee_id"]],
            "OT_TAXI",
            o["work_date"],
            rng.uniform(50, 110),
            ot=o["record_id"],
            desc="加班打车回家",
            status="REJECTED",
        )
        if c:
            note("ot_taxi_linked_to_rejected_overtime", claim_id=c["claim_id"], record_id=o["record_id"])
    # local transport, training, office supplies
    for e in sorted(EMP.values(), key=lambda x: x["employee_id"]):
        if e["employee_category"] == "INTERN":
            continue
        top = TOP[e["department_code"]]
        start = max(DATA_START, e["hire_date"])
        end = min(CUTOFF, e["termination_date"] or CUTOFF)
        span = (end - start).days
        if span <= 0:
            continue
        n_local = int(span / 30 * (3.5 if top in ("SAL", "CS") else 0.3))
        for _ in range(n_local):
            d = next_wd(start + dt.timedelta(days=rng.randint(0, span)))
            if d > end:
                continue
            add_claim(e, "LOCAL_TRANSPORT", d, rng.uniform(18, 145), desc="因公外出打车")
        for year in (2025, 2026):
            if rng.random() < 0.3:
                n = rng.choice([1, 1, 2])
                for _ in range(n):
                    d = next_wd(D(year, rng.randint(2, 11 if year == 2025 else 9), rng.randint(1, 25)))
                    if not (start <= d <= end):
                        continue
                    amt = rng.choice([980, 1500, 2600, 3200, 4500, 5800, 6900])
                    add_claim(
                        e,
                        "TRAINING",
                        d,
                        amt,
                        desc=rng.choice(
                            ["AWS 认证考试", "PMP 培训", "外部技术大会", "数据分析课程", "英语课程", "CPA 继续教育"]
                        ),
                    )
            if rng.random() < 0.25:
                d = next_wd(D(year, rng.randint(1, 10 if year == 2026 else 12), rng.randint(1, 25)))
                if start <= d <= end:
                    add_claim(
                        e,
                        "OFFICE_SUPPLY",
                        d,
                        rng.uniform(60, 880),
                        desc=rng.choice(["键盘鼠标", "笔记本支架", "移动硬盘", "耳机"]),
                    )
    # training over annual cap 8000 (HR-EX-001 2 / HR-BN-001 5.1)
    tr: defaultdict[tuple[str, int], float] = defaultdict(float)
    for c in EXP:
        if c["category"] == "TRAINING" and c["status"] != "REJECTED":
            tr[(c["employee_id"], c["expense_date"].year)] += c["amount"]
    for (eid, y), amt in sorted(tr.items()):
        if amt > 8000:
            note("training_over_annual_cap", employee_id=eid, year=y, total=amt)
    one = rng.choice(staff)
    c = add_claim(one, "OFFICE_SUPPLY", next_wd(D(2026, 8, 18)), 1299.0, desc="27 寸显示器", status="REJECTED")
    if c:
        note("office_supply_over_1000_must_use_it_procurement", claim_id=c["claim_id"], employee_id=one["employee_id"])
    # late submissions: 60-180 days needs a head's note; >180 rejected (HR-EX-001 3)
    daily = [
        c
        for c in EXP
        if c["category"] in ("LOCAL_TRANSPORT", "OFFICE_SUPPLY")
        and c["status"] == "PAID"
        and c["expense_date"] < D(2026, 3, 1)
    ]
    for c in rng.sample(daily, 3):
        c["submitted_date"] = c["expense_date"] + dt.timedelta(days=rng.randint(75, 150))
        c["description"] += "（附部门负责人说明）"
        note("expense_submitted_60_to_180_days", claim_id=c["claim_id"])
    # team building per quarter <= 300 x headcount (HR-EX-001 2)
    for code, *_ in DEPTS:
        head = EMP.get(DEPT[code][4])
        if code in ("SAL", "EXEC") or not head:
            continue
        for y, q in [(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2026, 1), (2026, 2), (2026, 3)]:
            qend = month_end(y, q * 3)
            members = [
                x
                for x in EMP.values()
                if x["department_code"] == code and active_on(x, qend) and x["employee_category"] == "FULL_TIME"
            ]
            if not members or rng.random() < 0.3:
                continue
            amt = round(len(members) * rng.uniform(180, 300), 2)
            add_claim(
                head,
                "TEAM_BUILDING",
                next_wd(D(y, q * 3, rng.randint(5, 20))),
                amt,
                desc=f"{DEPT[code][1]} {y}Q{q} 团建（{len(members)} 人）",
            )


def eid_(e: dict) -> str:
    return e["employee_id"]


# ───────────────────────────── payroll (HR-PY-001 / HR-CP-001) ─────────────────────────────
PAY: list[dict] = []
SI_BOUNDS = {
    ("上海", 2024): (7310, 36549),
    ("上海", 2025): (7460, 37302),
    ("北京", 2024): (6821, 35283),
    ("北京", 2025): (7162, 35811),
    ("深圳", 2024): (4492, 26421),
    ("深圳", 2025): (4775, 27549),
    ("成都", 2024): (4071, 20355),
    ("成都", 2025): (4246, 21228),
    ("上海", 2026): (7690, 38450),
    ("北京", 2026): (7380, 36880),
    ("深圳", 2026): (4920, 28380),
    ("成都", 2026): (4370, 21860),
}
EMPLOYER_SI = {"上海": 0.265, "北京": 0.263, "深圳": 0.21, "成都": 0.255}
IIT = [
    (36000, 0.03, 0),
    (144000, 0.10, 2520),
    (300000, 0.20, 16920),
    (420000, 0.25, 31920),
    (660000, 0.30, 52920),
    (960000, 0.35, 85920),
    (1e18, 0.45, 181920),
]
BONUS_TAX = [
    (3000, 0.03, 0),
    (12000, 0.10, 210),
    (25000, 0.20, 1410),
    (35000, 0.25, 2660),
    (55000, 0.30, 4410),
    (80000, 0.35, 7160),
    (1e18, 0.45, 15160),
]


def bracket(table, x: float) -> float:
    if x <= 0:
        return 0.0
    for top, rate, quick in table:
        if x <= top:
            return x * rate - quick
    return 0.0


def pay_date(y: int, m: int) -> D:
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return prev_wd(D(ny, nm, 10))


def build_payroll() -> None:
    months = [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 10)]
    ot_pay: defaultdict[tuple[str, int, int], float] = defaultdict(float)
    for o in OTS:
        if o["approval_status"] == "APPROVED" and o["compensation_method"] == "PAID":
            e = EMP[o["employee_id"]]
            base = salary_on(e["employee_id"], o["work_date"])["base"]
            hourly = base / 21.75 / 8  # HR-CP-001 6.1
            ot_pay[(e["employee_id"], o["work_date"].year, o["work_date"].month)] += (
                hourly * o["overtime_hours"] * CAL[o["work_date"]]["rate"]
            )
    fitness = {e["employee_id"]: rng.random() < 0.35 for e in EMP.values()}
    special = {e["employee_id"]: rng.choice([0, 0, 1500, 2000, 3000, 4000, 5000]) for e in EMP.values()}
    supp_opt_out = {e["employee_id"]: rng.random() < 0.15 for e in EMP.values()}
    gross_2025: defaultdict[str, list[float]] = defaultdict(list)
    for e in sorted(EMP.values(), key=lambda x: x["employee_id"]):
        eid = e["employee_id"]
        intern = e["employee_category"] == "INTERN"
        cum_inc = cum_ded = cum_tax = 0.0
        cur_year = None
        si_base_cache = {}
        for y, m in months:
            ms, me = D(y, m, 1), month_end(y, m)
            if not (e["hire_date"] <= me and (e["termination_date"] is None or e["termination_date"] >= ms)):
                continue
            if y != cur_year:
                cum_inc = cum_ded = cum_tax = 0.0
                cur_year = y
            all_wd = workdays(ms, me)
            emp_wd = employed_wd(e, ms, me)
            ratio = len(emp_wd) / len(all_wd)
            sal = salary_on(
                eid, me if not e["termination_date"] or e["termination_date"] > me else e["termination_date"]
            )
            base_contract, allow = sal["base"], sal["allow"]
            probation = (not intern) and (e["regularization_date"] is None or e["regularization_date"] > me)
            base_paid = base_contract * (0.8 if probation else 1.0) * ratio  # HR-EM-001 2.2
            allow_paid = allow * ratio
            daily = base_contract / 21.75
            leave_days = 0.0
            unpaid = 0.0
            for d in emp_wd:
                lv = LEAVE_DAYS[eid].get(d)
                if lv and lv[2]:
                    leave_days += lv[1]
                    if lv[0] == "PERSONAL":
                        unpaid += daily * lv[1]
            otp = 0.0 if intern else ot_pay[(eid, y, m)]
            comm = 0.0 if intern else 200 * ratio
            lunch = 0.0 if intern else 25 * (len(emp_wd) - leave_days)  # HR-BN-001 10.1
            fit = 0.0
            if fitness[eid] and m in (3, 6, 9, 12) and not intern:
                fit = float(sum(rng.choice([0, 120, 150, 200]) for _ in range(3)))
            payout = 0.0
            if e["termination_date"] and ms <= e["termination_date"] <= me and not intern:
                payout = leave_payout(e)
            gross = base_paid + allow_paid + otp + comm + lunch + fit + payout - unpaid
            # annual bonus in March (HR-PY-001 3.3 / HR-CP-001 5)
            bonus = 0.0
            if m == 3 and not intern and e["hire_date"] <= D(y - 1, 9, 30) and active_on(e, pay_date(y, m)):
                r = RATING.get((eid, f"{y - 1}-H2"))
                if r:
                    dec_base = salary_on(eid, D(y - 1, 12, 31))["base"]
                    months_in = (
                        12 if e["hire_date"] <= D(y - 1, 1, 1) else (D(y - 1, 12, 31) - e["hire_date"]).days / 365 * 12
                    )
                    bonus = dec_base * BONUS_MONTHS[r] * COMPANY_FACTOR[y - 1] * min(1.0, months_in / 12)
            # social insurance base (HR-PY-001 4.1/4.3): adjusted every July
            key_year = y if m >= 7 else y - 1
            if key_year not in si_base_cache:
                if intern:
                    si_base_cache[key_year] = 0.0
                elif e["hire_date"] > D(key_year - 1, 1, 31):
                    first = salary_on(eid, e["hire_date"])
                    si_base_cache[key_year] = (
                        first["base"] * (0.8 if e["hire_date"] > D(2024, 1, 1) else 1.0) + first["allow"]
                    )
                elif key_year == 2026 and gross_2025[eid]:
                    si_base_cache[key_year] = sum(gross_2025[eid]) / len(gross_2025[eid])
                else:
                    s = salary_on(eid, D(key_year - 1, 12, 31))
                    si_base_cache[key_year] = (s["base"] + s["allow"]) * 1.12
            lo, hi = SI_BOUNDS[(e["city"], key_year)]
            sib = 0.0 if intern else min(max(si_base_cache[key_year], lo), hi)
            si_emp = sib * 0.105
            hf = sib * 0.12
            supp = 0.0 if (intern or supp_opt_out[eid]) else sib * 0.05
            cum_inc += gross
            cum_ded += si_emp + hf + supp + 5000 + (0 if intern else special[eid])
            tax_total = bracket(IIT, cum_inc - cum_ded)
            iit = max(0.0, tax_total - cum_tax)
            cum_tax += iit
            btax = bracket(BONUS_TAX, bonus / 12) if bonus else 0.0
            if bonus:
                btax = bonus * next(r for t, r, q in BONUS_TAX if bonus / 12 <= t) - next(
                    q for t, r, q in BONUS_TAX if bonus / 12 <= t
                )
            net = gross + bonus - si_emp - hf - supp - iit - btax
            employer = gross + bonus + sib * EMPLOYER_SI[e["city"]] + hf + supp
            if y == 2025:
                gross_2025[eid].append(gross + bonus / 12)
            PAY.append(
                dict(
                    employee_id=eid,
                    pay_month=f"{y}-{m:02d}",
                    pay_date=pay_date(y, m),
                    base_salary=r2(base_paid),
                    position_allowance=r2(allow_paid),
                    overtime_pay=r2(otp),
                    communication_allowance=r2(comm),
                    lunch_allowance=r2(lunch),
                    fitness_subsidy=r2(fit),
                    unused_leave_payout=r2(payout),
                    unpaid_leave_deduction=r2(unpaid),
                    gross_pay=r2(gross),
                    annual_bonus=r2(bonus),
                    social_insurance_base=r2(sib),
                    social_insurance_employee=r2(si_emp),
                    housing_fund_employee=r2(hf),
                    supplementary_fund_employee=r2(supp),
                    special_deduction=0 if intern else special[eid],
                    individual_income_tax=r2(iit),
                    bonus_tax=r2(btax),
                    net_pay=r2(net),
                    employer_total_cost=r2(employer),
                    is_probation=probation,
                )
            )


def leave_payout(e: dict) -> float:
    """HR-EM-001 7.2 settlement of unused annual leave on termination."""
    t = e["termination_date"]
    y = t.year
    st, co, tot = annual_quota(e, y)
    start = max(D(y, 1, 1), e["hire_date"])
    worked = (t - start).days + 1
    full_st = st if e["hire_date"] <= D(y, 1, 1) else st / max(1e-9, ((D(y, 12, 31) - e["hire_date"]).days + 1) / 365)
    full_co = co if e["hire_date"] <= D(y, 1, 1) else co / max(1e-9, ((D(y, 12, 31) - e["hire_date"]).days + 1) / 365)
    used = sum(
        rec["days"]
        for rec in LEAVES
        if rec["employee_id"] == e["employee_id"]
        and rec["leave_type"] == "ANNUAL"
        and rec["status"] == "APPROVED"
        and rec["start_date"].year == y
    )
    used_st = min(used, st)  # statutory first (HR-LV-001 2.5)
    used_co = used - used_st
    avail_st = math.floor(worked / 365 * full_st) - used_st
    avail_co = worked / 365 * full_co - used_co
    daily = salary_on(e["employee_id"], t)["base"] / 21.75
    pay = max(0.0, avail_st) * daily * 3.0 + max(0.0, avail_co) * daily * 1.0
    note(
        "termination_leave_payout",
        employee_id=e["employee_id"],
        termination=str(t),
        unused_statutory=max(0, avail_st),
        unused_company=round(max(0.0, avail_co), 3),
        payout=round(pay, 2),
    )
    return pay


# ───────────────────────────── balances ─────────────────────────────
BAL: list[dict] = []


def build_balances() -> None:
    orig = {(r["employee_id"], r["leave_year"], r["leave_type"]): r for r in read_csv("leave_balances")}
    agg: defaultdict[tuple[str, int, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for rec in LEAVES:
        y = rec["start_date"].year
        if rec["status"] == "APPROVED":
            agg[(rec["employee_id"], y, rec["leave_type"])][0] += rec["days"]
        elif rec["status"] == "PENDING":
            agg[(rec["employee_id"], y, rec["leave_type"])][1] += rec["days"]
    for e in sorted(EMP.values(), key=lambda x: x["employee_id"]):
        if e["employee_category"] == "INTERN":
            continue
        for y in (2025, 2026):
            if e["hire_date"] > D(y, 12, 31) or (e["termination_date"] and e["termination_date"] < D(y, 1, 1)):
                continue
            st, co, tot = annual_quota(e, y)
            types = [("ANNUAL", st, co, tot), ("SICK", 0.0, 10.0, 10.0)]
            if e["has_child_under_3"]:
                types.append(("PARENTAL", 5.0, 0.0, 5.0))
            for lt, s, c, t in types:
                u, p = agg[(e["employee_id"], y, lt)]
                k = (e["employee_id"], str(y), lt)
                if k in orig:
                    o = orig[k]
                    assert (float(o["total_days"]), float(o["used_days"]), float(o["pending_days"])) == (t, u, p), (
                        k,
                        t,
                        u,
                        p,
                        o,
                    )
                    s, c = float(o["statutory_days"]), float(o["company_days"])
                BAL.append(
                    dict(
                        employee_id=e["employee_id"],
                        leave_year=y,
                        leave_type=lt,
                        statutory_days=s,
                        company_days=c,
                        total_days=t,
                        used_days=u,
                        pending_days=p,
                        remaining_days=t - u,
                    )
                )
                if lt == "ANNUAL" and u + p > t:
                    note("annual_leave_overdrawn", employee_id=e["employee_id"], year=y, total=t, used=u, pending=p)


# ───────────────────────────── output ─────────────────────────────
def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{v:.1f}"
    s = str(v)
    assert "," not in s and "\n" not in s, s
    return s


def write(name: str, cols: list[str], rows: list[dict]) -> None:
    os.makedirs(os.path.join(OUT, name), exist_ok=True)
    with open(os.path.join(OUT, name, name + ".csv"), "w", encoding="utf-8", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(fmt(r[c]) for c in cols) + "\n")


def data_rows(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        return sum(1 for _ in f) - 1


def main() -> None:
    build_calendar()
    build_org()
    build_careers()
    build_leaves()
    build_overtime()
    build_comp_leave(OTS)
    build_attendance()
    build_trips_and_expenses()
    build_payroll()
    build_balances()

    cal_rows = [
        dict(
            cal_date=d,
            day_of_week=d.isoweekday(),
            day_type=c["day_type"],
            is_workday=c["workday"],
            holiday_name=c["holiday_name"],
            is_statutory_holiday=c["statutory"],
            overtime_pay_rate=c["rate"],
        )
        for d, c in sorted(CAL.items())
        if d >= DATA_START
    ]
    write(
        "work_calendar",
        [
            "cal_date",
            "day_of_week",
            "day_type",
            "is_workday",
            "holiday_name",
            "is_statutory_holiday",
            "overtime_pay_rate",
        ],
        cal_rows,
    )
    write(
        "departments",
        [
            "department_code",
            "name_cn",
            "name_en",
            "head_employee_id",
            "city",
            "parent_department_code",
            "cost_center",
            "headcount_budget",
        ],
        [
            dict(
                department_code=c,
                name_cn=cn,
                name_en=en,
                head_employee_id=h,
                city=ci,
                parent_department_code=p,
                cost_center=f"CC-{1000 + i * 10}",
                headcount_budget=b,
            )
            for i, (c, cn, en, p, h, ci, b) in enumerate(DEPTS)
        ],
    )
    write(
        "job_levels",
        ["job_level", "track", "title_cn", "salary_band_min", "salary_band_max", "position_allowance"],
        [
            dict(job_level=rec, track=t, title_cn=ti, salary_band_min=lo, salary_band_max=hi, position_allowance=a)
            for rec, t, ti, lo, hi, a in LEVELS
        ],
    )
    emp_cols = [
        "employee_id",
        "name",
        "department_code",
        "city",
        "job_level",
        "manager_id",
        "hire_date",
        "career_start_date",
        "employment_status",
        "birth_month",
        "gender",
        "email",
        "employee_category",
        "work_hour_system",
        "regularization_date",
        "termination_date",
        "education",
        "has_child_under_3",
    ]
    for e in EMP.values():
        e["email"] = e["employee_id"].lower().replace("-", "") + "@anycompany.example"
    write("employees", emp_cols, sorted(EMP.values(), key=lambda x: x["employee_id"]))
    write(
        "salary_history",
        ["employee_id", "effective_date", "job_level", "base_salary_monthly", "position_allowance", "change_reason"],
        [
            dict(
                employee_id=eid,
                effective_date=h["effective_date"],
                job_level=h["job_level"],
                base_salary_monthly=h["base"],
                position_allowance=h["allow"],
                change_reason=h["reason"],
            )
            for eid in sorted(SALARY)
            for h in SALARY[eid]
        ],
    )
    write(
        "performance_reviews",
        [
            "review_id",
            "employee_id",
            "review_cycle",
            "cycle_end_date",
            "rating",
            "pre_calibration_rating",
            "reviewer_id",
            "finalized_date",
        ],
        REVIEWS,
    )
    LEAVES.sort(key=lambda rec: (rec["start_date"], rec["request_id"]))
    write(
        "leave_requests",
        [
            "request_id",
            "employee_id",
            "leave_type",
            "start_date",
            "end_date",
            "days",
            "status",
            "approver_id",
            "submitted_date",
            "reason",
            "certificate_submitted",
        ],
        LEAVES,
    )
    write(
        "leave_balances",
        [
            "employee_id",
            "leave_year",
            "leave_type",
            "statutory_days",
            "company_days",
            "total_days",
            "used_days",
            "pending_days",
            "remaining_days",
        ],
        BAL,
    )
    OTS.sort(key=lambda o: (o["work_date"], o["record_id"]))
    write(
        "overtime_records",
        [
            "record_id",
            "employee_id",
            "work_date",
            "end_time",
            "overtime_hours",
            "approval_status",
            "approver_id",
            "start_time",
            "overtime_type",
            "compensation_method",
            "submitted_date",
            "reason",
        ],
        OTS,
    )
    write(
        "attendance_daily",
        [
            "employee_id",
            "work_date",
            "work_mode",
            "check_in",
            "check_out",
            "attendance_status",
            "punch_corrected",
            "leave_request_id",
        ],
        ATT,
    )
    write(
        "remote_work_requests",
        [
            "request_id",
            "employee_id",
            "start_date",
            "end_date",
            "remote_days_per_week",
            "reason",
            "manager_approval",
            "hrbp_approval",
            "status",
            "submitted_date",
        ],
        REMOTE_REQ,
    )
    TRIPS.sort(key=lambda t: t["depart_date"])
    write(
        "business_trips",
        [
            "trip_id",
            "employee_id",
            "origin_city",
            "destination_city",
            "city_tier",
            "depart_date",
            "depart_time",
            "return_date",
            "return_time",
            "purpose",
            "approval_status",
            "submitted_date",
            "approver_id",
        ],
        TRIPS,
    )
    EXP.sort(key=lambda c: (c["expense_date"], c["claim_id"]))
    write(
        "expense_claims",
        [
            "claim_id",
            "employee_id",
            "category",
            "expense_date",
            "amount",
            "approved_amount",
            "submitted_date",
            "status",
            "approval_path",
            "approved_date",
            "finance_reviewed_at",
            "paid_date",
            "related_overtime_id",
            "related_trip_id",
            "nights",
            "description",
        ],
        EXP,
    )
    write("payroll_monthly", list(PAY[0].keys()), PAY)
    with open(os.path.join(OUT, "anomalies.json"), "w", encoding="utf-8") as f:
        json.dump(ANOMALIES, f, ensure_ascii=False, indent=1, default=str)
    counts = {
        n: data_rows(os.path.join(OUT, n, n + ".csv"))
        for n in sorted(os.listdir(OUT))
        if os.path.isdir(os.path.join(OUT, n))
    }
    print(json.dumps(counts, ensure_ascii=False))
    print("anomalies:", len(ANOMALIES))


if __name__ == "__main__":
    main()
