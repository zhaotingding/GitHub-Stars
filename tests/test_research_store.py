"""Research persistence and schema upgrades use disposable SQLite databases only."""
import json
import sqlite3
import time
from datetime import datetime, timezone

import pytest

from github_stars.research_store import encode
from github_stars.store import Store

NOW = datetime(2026, 11, 6, 10, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "research.db")


def repository(store, identity=1):
    store.upsert({"id": identity, "full_name": f"owner/project{identity}", "stargazers_count": 123}, "research", NOW)


def job(store, identity="job", *, state="running", expires=None):
    settings = {"deadline": time.time() + 1000, "credential_source": "private-source", "api_key": "never-public-key"}
    scope = {"records": [{"body": "private frozen raw README"}], "images": [{"data_url": "data:image/png;base64,PRIVATE"}]}
    sources = [{"label": "R1", "name": "owner/project1", "kind": "repository", "url": "https://github.com/owner/project1",
                "sha": "readme-sha", "captured": NOW.isoformat(), "text": "selected public evidence", "repo_id": 1}]
    store.execute("INSERT INTO research_jobs(id,question,mode,created,expires,state,settings,scope,sources,terms) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (identity, "机器人证据", "agent", time.time(), expires if expires is not None else time.time() + 7 * 86400,
                   state, encode(settings), encode(scope), encode(sources), encode(["robot"])))
    return identity


def step(store, identity="job", *, number=1, state="received", image=""):
    prepared = {"week": "2026-W45", "settings": {"api_key": "private-step-key"},
                "input": "data:image/png;base64,PRIVATE", "image": image}
    return store.execute("INSERT INTO research_steps(job_id,number,kind,state,prepared,reserve,created,response,response_id,"
                         "input_tokens,output_tokens,actual_model,actual_tier,cost) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (identity, number, "image" if image else "decision", state, encode(prepared), .04, time.time(),
                          '{"status":"completed","private":"raw response"}' if state == "received" else "", "resp-original" if state == "received" else "",
                          50, 20, "actual-model", "default", .01))


def test_v2_to_v3_keeps_repo_personal_state_and_existing_workflow_data(tmp_path):
    path = tmp_path / "v2.db"
    original = Store(path)
    repository(original)
    original.execute("UPDATE repos SET readme='legacy README',readme_sha='',readme_url='https://github.com/owner/project1',"
                     "readme_at=?,feedback='dismissed',study_state='focus',manual=1", (NOW.isoformat(),))
    original.execute("INSERT INTO digests(week,created,note,mail_state) VALUES('2026-W44',?,'frozen note','sent')", (NOW.isoformat(),))
    original.execute("INSERT INTO selections VALUES('2026-W44',1,1,?)", (encode({"full_name": "frozen/name"}),))
    original.execute("INSERT INTO ai_jobs(repo_id,week,created,status,model,evidence,result) VALUES(1,'2026-W44',?,'done','old-model','old-evidence','old-result')", (NOW.isoformat(),))
    original.set_state("last_scan_day", "2026-11-06")
    tables = ["repos", "snapshots", "digests", "selections", "ai_jobs", "state"]
    before = {table: original.rows(f"SELECT * FROM {table}") for table in tables}
    # v2 has these same core tables, without research tables or their user_version.
    with sqlite3.connect(path) as db:
        for table in ("research_documents", "research_jobs", "research_steps", "research_bookmarks", "research_image_cache", "research_image_claims"):
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=2")
    upgraded = Store(path)
    assert upgraded.one("PRAGMA user_version")["user_version"] == 3
    assert {table: upgraded.rows(f"SELECT * FROM {table}") for table in tables} == before
    archived = upgraded.one("SELECT * FROM research_documents")
    assert archived["text"] == "legacy README" and archived["captured"] == NOW.isoformat()
    assert archived["repo_id"] == 1 and archived["sha"].startswith("legacy:")
    assert Store(path).one("SELECT count(*) n FROM research_documents")["n"] == 1
    upgraded.cache_readme(1, "fresh README", "new-sha", "https://github.com/owner/project1", NOW.isoformat())
    assert upgraded.one("SELECT count(*) n FROM research_documents")["n"] == 2
    assert upgraded.one("SELECT * FROM research_documents WHERE id=?", (archived["id"],)) == archived


def test_cache_readme_archives_each_version_without_rewriting_first_capture(store):
    repository(store)
    first, second = "2026-11-04T10:00:00+00:00", "2026-11-05T10:00:00+00:00"
    store.cache_readme(1, "old body", "first-sha", "https://github.com/owner/project1/blob/old/README.md", first)
    store.cache_readme(1, "new body", "second-sha", "https://github.com/owner/project1/blob/new/README.md", second)
    store.cache_readme(1, "new body", "second-sha", "https://github.com/owner/project1", NOW.isoformat())
    versions = store.rows("SELECT sha,text,captured FROM research_documents ORDER BY id")
    assert versions == [{"sha": "first-sha", "text": "old body", "captured": first},
                        {"sha": "second-sha", "text": "new body", "captured": second}]
    assert store.one("SELECT readme,readme_at FROM repos WHERE id=1") == {"readme": "new body", "readme_at": NOW.isoformat()}
    with pytest.raises(ValueError):
        store.cache_readme(999, "orphan", "sha", "", NOW.isoformat())
    assert store.one("SELECT count(*) n FROM research_documents")["n"] == 2


def test_public_job_contains_only_reviewable_fields_without_raw_input_settings_or_response(store):
    job(store)
    step(store)
    public = store.research_public("job")
    payload = json.dumps(public)
    assert public["can_resume"] and public["calls"] == 1 and public["reserved_cny"] == .04
    for private in ("settings", "scope", "private-source", "never-public-key", "private-step-key", "data:image/png", "raw response", "private frozen raw README"):
        assert private not in payload


def test_apply_is_idempotent_and_atomic_with_step_marker(store):
    job(store)
    identity = step(store)
    store.execute("CREATE TRIGGER simulate_full_disk BEFORE UPDATE OF result ON research_jobs BEGIN SELECT RAISE(ABORT, 'full disk'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.research_apply("job", identity, state="done", result={"claims": ["kept"]})
    assert not store.one("SELECT applied FROM research_steps WHERE id=?", (identity,))["applied"]
    assert store.research_job("job")["result"] == {}
    store.execute("DROP TRIGGER simulate_full_disk")
    store.research_apply("job", identity, state="done", result={"claims": ["kept"]})
    store.research_apply("job", identity, result={"claims": ["must not replace"]})
    assert store.research_job("job")["result"] == {"claims": ["kept"]}
    assert store.one("SELECT applied FROM research_steps WHERE id=?", (identity,))["applied"]


def test_apply_requires_original_received_step_owned_by_unexpired_job(store):
    job(store)
    job(store, "other")
    prepared = step(store, state="prepared")
    foreign = step(store, "other")
    for identity in (prepared, foreign, 999):
        with pytest.raises(ValueError):
            store.research_apply("job", identity, state="done")
    received = step(store, number=2)
    store.execute("UPDATE research_jobs SET expires=0 WHERE id='job'")
    with pytest.raises(ValueError):
        store.research_apply("job", received, state="done")
    assert not store.one("SELECT applied FROM research_steps WHERE id=?", (received,))["applied"]


def test_late_cancelled_response_retains_usage_and_applied_marker_without_advancing_results(store):
    job(store)
    identity = step(store)
    assert store.research_cancel("job")["state"] == "cancelled"
    store.research_apply("job", identity, state="done", result={"late": True}, tools=99, sources=[])
    current = store.research_job("job")
    assert current["state"] == "cancelled" and current["result"] == {} and current["tools"] == 0 and current["sources"]
    received = store.one("SELECT * FROM research_steps WHERE id=?", (identity,))
    assert received["applied"] and received["input_tokens"] == 50 and received["response_id"] == "resp-original"
    store.research_update("job", state="running")
    assert store.research_job("job")["state"] == "cancelled"


def test_expiry_scrubs_raw_data_preserves_usage_bookmark_and_unknown_image_claim(store):
    job(store, state="done")
    store.research_update("job", result={"claims": [{"text": "answer", "sources": ["R1"]}]})
    store.research_bookmark("job", True)
    received = step(store)
    unknown = step(store, number=2, state="unknown", image="unknown-image")
    prepared = step(store, number=3, state="prepared", image="safe-unsubmitted-image")
    store.execute("INSERT INTO research_image_claims VALUES('unknown-image',?)", (unknown,))
    store.execute("INSERT INTO research_image_claims VALUES('safe-unsubmitted-image',?)", (prepared,))
    store.execute("UPDATE research_jobs SET expires=0 WHERE id='job'")
    store.research_prune()
    assert not store.rows("SELECT * FROM research_jobs")
    assert store.rows("SELECT * FROM research_image_claims") == [{"fingerprint": "unknown-image", "step_id": unknown}]
    kept = store.one("SELECT * FROM research_steps WHERE id=?", (received,))
    assert json.loads(kept["prepared"]) == {"week": "2026-W45"} and kept["response"] == ""
    assert (kept["reserve"], kept["cost"], kept["input_tokens"], kept["output_tokens"], kept["response_id"]) == (.04, .01, 50, 20, "resp-original")
    archived = store.research_public("job")
    assert archived["state"] == "archived" and archived["saved"] and not archived["can_resume"] and not archived["can_continue"]
    assert archived["result"]["claims"][0]["text"] == "answer"
    assert "text" not in archived["sources"][0] and "repo_id" not in archived["sources"][0]
    assert "data:image/png" not in json.dumps(archived)
    removed = store.research_bookmark("job", False)
    assert removed["state"] == "deleted" and not removed["saved"]
    with pytest.raises(ValueError):
        store.research_public("job")


def test_bookmark_rejects_unfinished_answer_and_removes_unsafe_source_link(store):
    job(store)
    with pytest.raises(ValueError):
        store.research_bookmark("job", True)
    sources = store.research_job("job")["sources"]
    sources[0]["url"] = "javascript:alert(1)"
    store.research_update("job", state="done", sources=sources)
    store.research_bookmark("job", True)
    pointers = json.loads(store.one("SELECT sources FROM research_bookmarks")["sources"])
    assert pointers[0]["url"] == "" and "text" not in pointers[0]
    with pytest.raises(ValueError):
        store.research_bookmark("job", "yes")


def test_interrupt_marks_unknown_without_new_steps_and_supports_local_recovery(store):
    job(store)
    received = step(store)
    job(store, "submitted")
    submitted = step(store, "submitted", state="submitting")
    job(store, "prepared")
    step(store, "prepared", state="prepared")
    store.research_interrupt()
    assert store.research_job("job")["state"] == "paused"
    assert store.research_job("submitted")["state"] == "blocked"
    assert store.research_job("prepared")["state"] == "continuable"
    assert store.one("SELECT state FROM research_steps WHERE id=?", (submitted,))["state"] == "unknown"
    assert store.one("SELECT response_id FROM research_steps WHERE id=?", (received,))["response_id"] == "resp-original"
    assert store.one("SELECT count(*) n FROM research_steps")["n"] == 3


def test_feedback_is_explicit_and_requires_completed_answer(store):
    job(store)
    with pytest.raises(ValueError):
        store.research_feedback("job", "useful")
    store.research_update("job", state="done")
    assert store.research_feedback("job", "useful")["feedback"] == "useful"
    assert store.research_feedback("job", "irrelevant")["feedback"] == "irrelevant"
    assert store.research_feedback("job", "clear")["feedback"] == ""
    with pytest.raises(ValueError):
        store.research_feedback("job", "invented")
