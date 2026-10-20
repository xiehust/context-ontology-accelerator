#!/usr/bin/env python3
"""Run one read-only Athena query in the COA namespace workgroup and print rows. Usage: athena.py "<sql>" """

import json
import subprocess
import sys
import time

WG = "coa-w2-dev-dc09046b-28af-4c7b-a03a-4fa63cda243b"


def aws(*a):
    r = subprocess.run(["aws", *a, "--region", "us-west-2", "--output", "json"], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr)
    return json.loads(r.stdout)


sql = sys.argv[1]
assert sql.lstrip().lower().startswith(("select", "with", "show", "describe")), "read-only only"
qid = aws(
    "athena",
    "start-query-execution",
    "--work-group",
    WG,
    "--query-string",
    sql,
    "--query-execution-context",
    "Database=anyhr,Catalog=awsdatacatalog",
)["QueryExecutionId"]
while True:
    st = aws("athena", "get-query-execution", "--query-execution-id", qid)["QueryExecution"]["Status"]
    if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
        break
    time.sleep(1)
if st["State"] != "SUCCEEDED":
    raise SystemExit(st)
rows = aws("athena", "get-query-results", "--query-execution-id", qid)["ResultSet"]["Rows"]
for r in rows[: int(sys.argv[2]) if len(sys.argv) > 2 else 40]:
    print(" | ".join(c.get("VarCharValue", "") for c in r["Data"]))
print(f"({len(rows) - 1} rows)")
