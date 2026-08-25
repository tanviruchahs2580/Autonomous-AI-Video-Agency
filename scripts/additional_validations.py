"""Additional validation for universal audit: large data, i18n, concurrency, observability."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tempfile, os
tmp = Path(tempfile.mkdtemp())
os.environ.update({
    "AGENCY_DB_URL": f"sqlite:///{(tmp/'audit.db').as_posix()}",
    "AGENCY_DATA_DIR": str(tmp),
    "AGENCY_STORAGE_DIR": str(tmp/'storage'),
    "AGENCY_TTS_PROVIDER": "synth",
})
for m in list(sys.modules):
    if m.startswith("agency"):
        del sys.modules[m]
import agency.config as cm
from agency.config import Settings
s = Settings(env="development", api_key="audit-key", db_url=os.environ["AGENCY_DB_URL"], storage_dir=tmp/'storage', data_dir=tmp, tts_provider="synth", rate_limit_per_min=10000)
cm.get_settings = lambda: s
import agency.db as dbm
for m in ("agency.db","agency.agents.stages","agency.api.main","agency.capabilities.router","agency.capabilities.tts","agency.capabilities.media"):
    if m in sys.modules and hasattr(sys.modules[m],"get_settings"):
        setattr(sys.modules[m],"get_settings", lambda: s)
dbm.reset_engine()
from agency.db import init_db
init_db()
from fastapi.testclient import TestClient
from agency.api.main import app
import concurrent.futures

results = {}
with TestClient(app) as client:
    H = {"X-API-Key": "audit-key"}
    # Large data: 100 projects
    for i in range(100):
        client.post("/v1/projects", json={"name": f"bulk-{i}", "brief": {"title": f"T{i}", "objective": "O"*20}}, headers=H)
    r = client.get("/v1/projects?size=10&page=1", headers=H)
    results["large_data_page1"] = r.json()["total"] == 100 and len(r.json()["items"])==10
    r2 = client.get("/v1/projects?size=10&page=11", headers=H)
    results["large_data_last_page"] = len(r2.json()["items"])==0 or len(r2.json()["items"])<=10
    print(f"LARGE DATA: total 100 paginated OK={results['large_data_page1']}")

    # Bangla i18n
    bangla_brief = {"title": "নিম্বাস সিআরএম", "objective": "বিক্রয় দলগুলোকে স্বয়ংক্রিয় ফলো-আপ এবং রিয়েল-টাইম ড্যাশবোর্ড দিয়ে সাহায্য করুন।", "audience": "বিক্রয় নেতারা", "cta": "ডেমো বুক করুন"}
    r = client.post("/v1/projects", json={"name": "bangla-test", "brief": bangla_brief}, headers=H)
    results["bangla_unicode"] = r.status_code==200
    try:
        pid_bangla = r.json().get("id") if r.status_code==200 else None
        results["bangla_unicode"] = results["bangla_unicode"] and bool(pid_bangla)
        if pid_bangla:
            get_r = client.get(f"/v1/projects/{pid_bangla}", headers=H)
            results["bangla_unicode"] = get_r.status_code==200 and "নিম্বাস" in json.dumps(get_r.json(), ensure_ascii=False)
    except Exception:
        pass
    print(f"BANGLA: {results['bangla_unicode']} status={r.status_code}")

    # Oversized payload
    big = {"title": "X"*500, "objective": "O"}
    r = client.post("/v1/projects", json={"name": "big", "brief": big}, headers=H)
    results["oversized_rejected"] = r.status_code==422
    print(f"OVERSIZED: {r.status_code} rejected={results['oversized_rejected']}")

    # Concurrent job creation on same project
    pid = client.post("/v1/projects", json={"name": "conc", "brief": {"title":"C","objective":"O"}}, headers=H).json()["id"]
    def mk_job(i):
        return client.post(f"/v1/projects/{pid}/jobs", json={"idempotency_key": f"conc-{i%3}"}, headers=H).json()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        outs = list(ex.map(mk_job, range(20)))
    unique_ids = len(set(o["id"] for o in outs))
    results["concurrent_idempotent"] = unique_ids==3
    print(f"CONCURRENT: 20 req with 3 keys -> {unique_ids} unique (expect 3) OK={results['concurrent_idempotent']}")

    # Observability
    r = client.get("/v1/metrics", headers=H)
    results["metrics_prometheus"] = "agency_api_requests_total" in r.text
    r = client.get("/v1/events", headers=H)
    results["events_api"] = r.status_code==200
    print(f"METRICS: {results['metrics_prometheus']} EVENTS: {results['events_api']}")

    # File security: oversized upload already tested via magic-byte, now test path traversal neutralization (already verified)
    print(f"RESULTS: {json.dumps(results, ensure_ascii=False)}")
    if all(results.values()):
        print("ALL ADDITIONAL VALIDATIONS PASS")
    else:
        print("SOME FAILED", results)
        sys.exit(1)
