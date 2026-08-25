import json, sqlite3
from pathlib import Path
jobId="d3650550e02044c0920a989438708196"
db = Path('data/agency.db')
c = sqlite3.connect(db)
print("=== QA ===")
for r in c.execute("SELECT layer, passed, score, findings_json FROM qa_reports WHERE job_id=? ORDER BY layer", (jobId,)):
    print(f"QA {r[0]}: passed={bool(r[1])} score={r[2]} findings={r[3][:120]}")
print("=== TASKS ===")
for r in c.execute("SELECT seq, name, state, attempt, duration_ms FROM tasks WHERE job_id=? ORDER BY seq", (jobId,)):
    print(f"TASK {r[0]:02d} {r[1]:20s} {r[2]:8s} att={r[3]} {r[4]}ms")
print("=== COSTS ===")
for r in c.execute("SELECT category, provider, amount_usd FROM costs WHERE job_id=?", (jobId,)):
    print(f"COST {r[0]} {r[1]} ${r[2]}")
print("=== ARTIFACTS ===")
for r in c.execute("SELECT kind, bytes, provenance_json FROM artifacts WHERE job_id=?", (jobId,)):
    prov=json.loads(r[2]) if r[2] else {}
    print(f"ART {r[0]:22s} {str(r[1]):6s}B origin={prov.get('origin','?')} tool={prov.get('tool','')[:20]}")
print("=== DELIVERABLES ===")
for r in c.execute("SELECT platform, manifest_json FROM deliverables WHERE job_id=?", (jobId,)):
    m=json.loads(r[1])
    print(f"DLV {r[0]:20s} dur={m.get('duration_s')} res={m.get('resolution')} title={m.get('title')[:30]}")
print("=== COUNTS ===")
n = c.execute("SELECT count(*) FROM events WHERE job_id=?", (jobId,)).fetchone()[0]
print(f"EVENTS {n}")
n2 = c.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
print(f"AUDIT total {n2}")
# Script
for r in c.execute("SELECT content_json FROM scripts WHERE project_id=(SELECT project_id FROM jobs WHERE id=?)", (jobId,)):
    d=json.loads(r[0])
    print("SCRIPT words", len(d["full_text"].split()), "gen", d.get("generator"))
    print(d["full_text"][:250])
