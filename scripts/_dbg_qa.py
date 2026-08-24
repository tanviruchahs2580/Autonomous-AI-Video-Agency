import json
import sqlite3
import sys
from pathlib import Path

db = sys.argv[1] if len(sys.argv) > 1 else "data/e2edbg/a.db"
c = sqlite3.connect(db)
for r in c.execute("SELECT name,failure_class,substr(error,1,120) FROM tasks WHERE state='failed' ORDER BY id DESC LIMIT 4"):
    print(r)
for r in c.execute("SELECT layer,findings_json,score FROM qa_reports ORDER BY created_at DESC LIMIT 3"):
    print(r[0], r[1][:200], "score", r[2])
for r in c.execute("SELECT content_json FROM scripts ORDER BY created_at DESC LIMIT 1"):
    d = json.loads(r[0])
    print("WORDS:", len(d["full_text"].split()))
    print("TEXT:", d["full_text"][:300])
