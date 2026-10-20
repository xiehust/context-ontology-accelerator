#!/usr/bin/env python3
"""Publish AnyHR v2 CSVs to S3 and create/update the Glue tables (database anyhr, us-west-2).

Usage: python3 publish.py <out_dir> [--dry-run]
Uses the AWS CLI (default credential chain); never reads credentials itself.
"""

import json
import os
import subprocess
import sys
import tempfile

REGION = "us-west-2"
BUCKET = "coa-w2-anyhr-demo-434444145045"
DB = "anyhr"

S, INT, F, DT, B = "string", "int", "double", "date", "boolean"
TABLES = {
    "departments": (
        "部门主数据，含上下级部门、负责人、成本中心与编制预算",
        [
            ("department_code", S, "部门编码，如 ENG、ENG-PLT"),
            ("name_cn", S, "部门中文名"),
            ("name_en", S, "部门英文名"),
            ("head_employee_id", S, "部门负责人员工编号"),
            ("city", S, "部门所在城市"),
            ("parent_department_code", S, "上级部门编码，一级部门为空"),
            ("cost_center", S, "成本中心编码"),
            ("headcount_budget", INT, "年度编制人数"),
        ],
    ),
    "employees": (
        "员工主数据（含在职、试用期、实习、已离职员工）",
        [
            ("employee_id", S, "员工编号 EMP-xxxx"),
            ("name", S, "姓名"),
            ("department_code", S, "所属部门编码（最末级部门）"),
            ("city", S, "常驻办公城市"),
            ("job_level", S, "职级 P3-P8 / M1-M4 / INT"),
            ("manager_id", S, "直属上级员工编号"),
            ("hire_date", DT, "入职日期"),
            ("career_start_date", DT, "参加工作日期，用于计算累计工作年限"),
            ("employment_status", S, "雇佣状态：regular 正式、probation 试用期、intern 实习、resigned 已离职"),
            ("birth_month", INT, "出生月份，用于生日假"),
            ("gender", S, "性别 M/F"),
            ("email", S, "公司邮箱"),
            ("employee_category", S, "员工类别：FULL_TIME 全职、INTERN 实习生"),
            ("work_hour_system", S, "工时制度：STANDARD 标准工时、COMPREHENSIVE 综合计算工时"),
            ("regularization_date", DT, "转正日期，试用期员工为空"),
            ("termination_date", DT, "离职日期（最后工作日），在职为空"),
            ("education", S, "最高学历"),
            ("has_child_under_3", B, "是否有未满 3 周岁子女（育儿假资格）"),
        ],
    ),
    "job_levels": (
        "职级与薪酬带宽（HR-CP-001）",
        [
            ("job_level", S, "职级"),
            ("track", S, "通道：PROFESSIONAL / MANAGEMENT / INTERN"),
            ("title_cn", S, "职级头衔"),
            ("salary_band_min", INT, "月度基本工资带宽下限（元）"),
            ("salary_band_max", INT, "月度基本工资带宽上限（元）"),
            ("position_allowance", INT, "月度岗位津贴（元）"),
        ],
    ),
    "salary_history": (
        "员工薪酬变动记录：入职定薪、年度调薪、晋升调薪",
        [
            ("employee_id", S, "员工编号"),
            ("effective_date", DT, "生效日期"),
            ("job_level", S, "生效后的职级"),
            ("base_salary_monthly", F, "月度基本工资（元，转正口径）"),
            ("position_allowance", F, "月度岗位津贴（元）"),
            ("change_reason", S, "变动原因：HIRE 入职、ANNUAL_ADJUST 年度调薪、PROMOTION 晋升"),
        ],
    ),
    "performance_reviews": (
        "半年度绩效评级（HR-PF-001）",
        [
            ("review_id", S, "评估记录编号"),
            ("employee_id", S, "员工编号"),
            ("review_cycle", S, "绩效周期，如 2025-H2"),
            ("cycle_end_date", DT, "周期结束日"),
            ("rating", S, "定稿评级 S/A/B/C/D"),
            ("pre_calibration_rating", S, "校准前的上级初评评级"),
            ("reviewer_id", S, "评估人（直属上级）员工编号"),
            ("finalized_date", DT, "定稿日期"),
        ],
    ),
    "work_calendar": (
        "公司工作日历（含法定节假日与调休上班日）",
        [
            ("cal_date", DT, "日期"),
            ("day_of_week", INT, "星期几，1=周一 … 7=周日"),
            ("day_type", S, "日期类型：WORKDAY 工作日、WEEKEND 周末、HOLIDAY 节假日放假、ADJUSTED_WORKDAY 调休上班日"),
            ("is_workday", B, "是否需要上班"),
            ("holiday_name", S, "节日名称"),
            ("is_statutory_holiday", B, "是否法定节假日当天（加班 300%）"),
            ("overtime_pay_rate", F, "该日加班工资倍率 1.5 / 2.0 / 3.0"),
        ],
    ),
    "leave_requests": (
        "请假申请记录（年假、病假、调休、生日假、事假、育儿假、婚假等）",
        [
            ("request_id", S, "请假单号"),
            ("employee_id", S, "员工编号"),
            (
                "leave_type",
                S,
                "假期类型：ANNUAL 年假、SICK 病假、COMP 调休、BIRTHDAY 生日假、PERSONAL 事假、PARENTAL 育儿假、MARRIAGE 婚假、PATERNITY 陪产假、MATERNITY 产假、BEREAVEMENT 丧假",
            ),
            ("start_date", DT, "开始日期"),
            ("end_date", DT, "结束日期"),
            ("days", F, "请假天数（工作日，产假为日历天）"),
            ("status", S, "审批状态：APPROVED 已批准、PENDING 待审批、REJECTED 已驳回、WITHDRAWN 已撤回"),
            ("approver_id", S, "审批人员工编号"),
            ("submitted_date", DT, "提交日期"),
            ("reason", S, "请假事由"),
            ("certificate_submitted", B, "病假是否已上传诊断证明（连续病假 2 天及以上需要）"),
        ],
    ),
    "leave_balances": (
        "员工各年度各类假期额度与使用情况",
        [
            ("employee_id", S, "员工编号"),
            ("leave_year", INT, "假期年度"),
            ("leave_type", S, "假期类型 ANNUAL / SICK / PARENTAL"),
            ("statutory_days", F, "法定年休假天数"),
            ("company_days", F, "公司福利年假天数"),
            ("total_days", F, "年度总额度"),
            ("used_days", F, "已使用（已批准）天数"),
            ("pending_days", F, "待审批天数"),
            ("remaining_days", F, "AnyHR 显示的剩余天数 = 总额度 − 已使用，未扣除待审批"),
        ],
    ),
    "overtime_records": (
        "加班申请与记录",
        [
            ("record_id", S, "加班记录编号"),
            ("employee_id", S, "员工编号"),
            ("work_date", DT, "加班日期"),
            ("end_time", S, "加班结束（离开）时间 HH:MM"),
            ("overtime_hours", F, "加班小时数"),
            ("approval_status", S, "审批状态：APPROVED 已批准、PENDING 待审批、REJECTED 已驳回"),
            ("approver_id", S, "审批人员工编号"),
            ("start_time", S, "加班开始时间 HH:MM"),
            ("overtime_type", S, "加班类型：WORKDAY 工作日延时、REST_DAY 休息日、STATUTORY_HOLIDAY 法定节假日"),
            ("compensation_method", S, "补偿方式：PAID 支付加班工资、COMP_LEAVE 调休"),
            ("submitted_date", DT, "提交日期"),
            ("reason", S, "加班事由"),
        ],
    ),
    "attendance_daily": (
        "每日考勤打卡记录（2026-07-01 起）",
        [
            ("employee_id", S, "员工编号"),
            ("work_date", DT, "日期"),
            ("work_mode", S, "办公方式：OFFICE 到岗、REMOTE 远程"),
            ("check_in", S, "上班打卡时间 HH:MM"),
            ("check_out", S, "下班打卡时间 HH:MM"),
            (
                "attendance_status",
                S,
                "考勤结果：NORMAL 正常、LATE 迟到、EARLY_LEAVE 早退、ABSENT 旷工、ON_LEAVE 请假、MISSING_PUNCH 漏打卡",
            ),
            ("punch_corrected", B, "是否经补卡"),
            ("leave_request_id", S, "当天对应的请假单号"),
        ],
    ),
    "remote_work_requests": (
        "专项远程办公申请（每周超过 2 天，HR-AT-001 第 4.2 条）",
        [
            ("request_id", S, "申请编号"),
            ("employee_id", S, "员工编号"),
            ("start_date", DT, "开始日期"),
            ("end_date", DT, "结束日期"),
            ("remote_days_per_week", INT, "每周远程天数"),
            ("reason", S, "申请原因"),
            ("manager_approval", S, "直属上级审批结果"),
            ("hrbp_approval", S, "HRBP 审批结果"),
            ("status", S, "申请状态：APPROVED / PENDING / REJECTED"),
            ("submitted_date", DT, "提交日期"),
        ],
    ),
    "business_trips": (
        "出差申请（FIN-TR-001）",
        [
            ("trip_id", S, "出差申请编号"),
            ("employee_id", S, "员工编号"),
            ("origin_city", S, "出发城市"),
            ("destination_city", S, "目的地城市"),
            ("city_tier", INT, "目的地城市类别 1/2/3"),
            ("depart_date", DT, "出发日期"),
            ("depart_time", S, "出发时间 HH:MM"),
            ("return_date", DT, "返回日期"),
            ("return_time", S, "返回时间 HH:MM"),
            ("purpose", S, "出差事由"),
            ("approval_status", S, "审批状态"),
            ("submitted_date", DT, "提交日期"),
            ("approver_id", S, "审批人员工编号"),
        ],
    ),
    "expense_claims": (
        "费用报销单（日常费用与差旅）",
        [
            ("claim_id", S, "报销单号"),
            ("employee_id", S, "员工编号"),
            (
                "category",
                S,
                "费用类别：LOCAL_TRANSPORT 市内交通、OT_MEAL 加班餐费、OT_TAXI 加班打车、TRAINING 培训认证、OFFICE_SUPPLY 办公用品、TEAM_BUILDING 团建、TRAVEL_HOTEL 差旅住宿、TRAVEL_MEAL_ALLOWANCE 出差伙食补助、TRAVEL_INTERCITY 城际交通、TRAVEL_LOCAL 出差市内交通",
            ),
            ("expense_date", DT, "费用发生日期"),
            ("amount", F, "申报金额（元）"),
            ("approved_amount", F, "核定金额（元），超标部分不予报销"),
            ("submitted_date", DT, "提交日期"),
            ("status", S, "状态：SUBMITTED 审批中、APPROVED 已审核待付款、PAID 已付款、REJECTED 已驳回"),
            ("approval_path", S, "审批路径，按金额分级"),
            ("approved_date", DT, "审批完成日期"),
            ("finance_reviewed_at", S, "财务审核完成时间 YYYY-MM-DD HH:MM"),
            ("paid_date", DT, "付款日期（每周四）"),
            ("related_overtime_id", S, "关联的加班记录编号"),
            ("related_trip_id", S, "关联的出差申请编号"),
            ("nights", INT, "住宿晚数"),
            ("description", S, "费用说明"),
        ],
    ),
    "payroll_monthly": (
        "月度工资条（每月 10 日发放上月工资）",
        [
            ("employee_id", S, "员工编号"),
            ("pay_month", S, "工资所属月份 YYYY-MM"),
            ("pay_date", DT, "发薪日"),
            ("base_salary", F, "当月实发基本工资（试用期 80%、按出勤折算）"),
            ("position_allowance", F, "岗位津贴"),
            ("overtime_pay", F, "加班工资"),
            ("communication_allowance", F, "通讯补贴"),
            ("lunch_allowance", F, "午餐补贴"),
            ("fitness_subsidy", F, "健身补贴（按季度发放）"),
            ("unused_leave_payout", F, "离职未休年假折算"),
            ("unpaid_leave_deduction", F, "事假扣款"),
            ("gross_pay", F, "应发工资（不含年终奖）"),
            ("annual_bonus", F, "年终奖金"),
            ("social_insurance_base", F, "社保公积金缴费基数"),
            ("social_insurance_employee", F, "社保个人缴纳"),
            ("housing_fund_employee", F, "住房公积金个人缴纳 12%"),
            ("supplementary_fund_employee", F, "补充公积金个人缴纳 5%"),
            ("special_deduction", F, "个税专项附加扣除（月）"),
            ("individual_income_tax", F, "工资薪金个税"),
            ("bonus_tax", F, "年终奖单独计税税额"),
            ("net_pay", F, "实发工资"),
            ("employer_total_cost", F, "公司用工总成本"),
            ("is_probation", B, "当月是否试用期"),
        ],
    ),
}


def aws(*args, dry=False):
    cmd = ["aws", *args, "--region", REGION, "--output", "json"]
    if dry:
        print("DRY", " ".join(a if len(a) < 80 else a[:77] + "..." for a in cmd))
        return {}
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"FAILED {' '.join(cmd[:4])}: {r.stderr.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else {}


def table_input(name: str) -> dict:
    desc, cols = TABLES[name]
    return {
        "Name": name,
        "Description": desc,
        "TableType": "EXTERNAL_TABLE",
        "Parameters": {"classification": "csv", "skip.header.line.count": "1", "EXTERNAL": "TRUE"},
        "StorageDescriptor": {
            "Columns": [{"Name": c, "Type": t, "Comment": cm} for c, t, cm in cols],
            "Location": f"s3://{BUCKET}/{DB}/{name}/",
            "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
            "SerdeInfo": {
                "SerializationLibrary": "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
                "Parameters": {"field.delim": ",", "serialization.format": ","},
            },
        },
    }


def main():
    out = sys.argv[1]
    dry = "--dry-run" in sys.argv
    existing = {t["Name"] for t in aws("glue", "get-tables", "--database-name", DB).get("TableList", [])}
    for name in TABLES:
        path = os.path.join(out, name, name + ".csv")
        with open(path, encoding="utf-8") as fh:
            header = fh.readline().strip().split(",")
        assert header == [c for c, _, _ in TABLES[name][1]], (name, header)
        aws(
            "s3api",
            "put-object",
            "--bucket",
            BUCKET,
            "--key",
            f"{DB}/{name}/{name}.csv",
            "--body",
            path,
            "--content-type",
            "text/csv; charset=utf-8",
            dry=dry,
        )
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(table_input(name), f, ensure_ascii=False)
        try:
            verb = "update-table" if name in existing else "create-table"
            aws("glue", verb, "--database-name", DB, "--table-input", f"file://{f.name}", dry=dry)
        finally:
            os.unlink(f.name)
        print(("would " if dry else "") + f"{verb.split('-')[0]}d {name} ({len(TABLES[name][1])} cols)")


if __name__ == "__main__":
    main()
