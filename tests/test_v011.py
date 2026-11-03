import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from test_tutorial_html import lesson_fixture
from test_workflow import NOW, FakeGitHub, ai_config, repository, response_payload, sdk_client, seed

from github_stars import ai
from github_stars.config import Paths
from github_stars.github import GitHubError, parse_repositories
from github_stars.service import Service
from github_stars.store import STUDY_STATES, Store


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(Paths, "secret", lambda *_: "")
    return Service(Paths(tmp_path), github_factory=FakeGitHub, clock=lambda: NOW)


def analysis_fixture():
    return {"summary": "项目解决表示学习问题", "relevance": "可以与研究基线比较", "usage": "先阅读官方示例，来源未提供硬件要求",
            "related_projects": "暂无可核对的相关项目", "limitations": "仅据 README，未运行"}


def response_for(content):
    value = response_payload(text=json.dumps(content, ensure_ascii=False))
    value["service_tier"] = "flex"
    return value


def test_markdown_multiple_links_canonicalized():
    text = "[Superpowers](https://github.com/obra/superpowers)、[技能](https://github.com/addyosmani/agent-skills)。[子目录](https://github.com/citypaul/.dotfiles/tree/main/claude/skills/evaluate-existing-solutions)。https://github.com/OBRA/SUPERPOWERS.git"
    assert parse_repositories(text) == ["obra/superpowers", "addyosmani/agent-skills", "citypaul/.dotfiles"]
    assert parse_repositories("github.com/owner/repository?tab=readme") == ["owner/repository"]
    assert parse_repositories("https://www.github.com/owner/repo.git.") == ["owner/repo"]


@pytest.mark.parametrize("value", ["https://github.com.evil/owner/repo", "https://user:pass@github.com/owner/repo", "https://github.com/topics/ai", "https://github.com/owner", "https://github.com/owner/..", "not a repository"])
def test_import_rejects_non_repository_input(value):
    with pytest.raises(ValueError):
        parse_repositories(value)


def test_manual_import_low_stars_preserves_state_and_scan_calendar(service):
    class ManualGitHub(FakeGitHub):
        def repository(self, name):
            repo = repository(8, "unrelated", 2)
            repo["full_name"] = "new/lowstars"
            return repo
    service.github_factory = ManualGitHub
    result = service.run("import", text="https://github.com/new/lowstars")
    assert result["repo_id"] == 8
    row = service.store.one("SELECT * FROM repos WHERE id=8")
    assert row["manual"] == 1 and row["score"] == 0 and row["readme"]
    assert not service.store.rows("SELECT * FROM scans") and not service.store.state("last_scan_day")
    for state in STUDY_STATES:
        service.run("study_state", repo_id=8, state=state)
        service.run("import", text="https://github.com/new/lowstars/tree/main")
        assert service.store.one("SELECT study_state FROM repos WHERE id=8")["study_state"] == state
    assert service.store.one("SELECT count(*) n FROM repos")["n"] == 1
    with pytest.raises(ValueError):
        service.run("study_state", repo_id=8, state="not-supported")


def test_failed_import_is_visible_without_mutating_scan(service):
    class Missing(FakeGitHub):
        def repository(self, name):
            raise GitHubError("GitHub HTTP 404")
    service.github_factory = Missing
    result = service.run("import", text="https://github.com/none/missing")
    assert "404" in result["message"] and result["repo_id"] is None
    assert not service.store.rows("SELECT * FROM repos") and not service.store.rows("SELECT * FROM scans")


def test_studied_projects_do_not_return_to_weekly_recommendations(service):
    seed(service)
    service.run("study_state", repo_id=1, state="studied")
    week = service.run("digest")
    assert 1 not in [r["repo_id"] for r in service.store.rows("SELECT repo_id FROM selections WHERE week=?", (week,))]


@pytest.mark.parametrize("source,username,target_prefix", [("msgx", "msgx", "msgx/api/"), ("autogpu", "autodl-watcher", "autodl-watcher/llm/")])
def test_existing_windows_credential_contract_utf8_and_reference_only(monkeypatch, source, username, target_prefix):
    import ctypes
    from types import SimpleNamespace

    from github_stars.config import existing_openai_secret
    class Function:
        def __init__(self, call):
            self.call = call
        def __call__(self, *args):
            return self.call(*args)
    kept, targets = [], []
    def read(target, kind, flags, destination):
        targets.append(target)
        credential_type = destination._obj._type_
        encoded = "fake-测试-key".encode("utf-8")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        item = credential_type(UserName=username, CredentialBlobSize=len(encoded), CredentialBlob=blob)
        kept.extend([blob, item])
        ctypes.cast(destination, ctypes.POINTER(ctypes.POINTER(credential_type)))[0] = ctypes.pointer(item)
        return True
    def release(_):
        assert not any(kept[0])  # 解码后清理原生临时缓冲，而不是复制到新凭据。
    api = SimpleNamespace(CredReadW=Function(read), CredFree=Function(release))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: api)
    assert existing_openai_secret(source) == "fake-测试-key"
    assert len(targets) == 1 and targets[0].startswith(target_prefix)


def test_theme_default_persisted_without_replacing_old_config(tmp_path):
    paths = Paths(tmp_path)
    paths.settings.write_text("ai:\n  model: personal-model\n  max_output_tokens: 7000\nprofile:\n  description: 我的方向\n", encoding="utf-8")
    config = paths.ensure_theme()
    assert config["appearance"]["theme"] == "dark"
    assert "theme: dark" in paths.settings.read_text(encoding="utf-8")
    assert config["ai"]["model"] == "personal-model" and config["ai"]["max_output_tokens"] == 7000
    config["appearance"]["theme"] = "light"
    paths.save(config)
    assert Paths(tmp_path).ensure_theme()["appearance"]["theme"] == "light"


def test_analysis_cached_but_every_tutorial_is_a_new_request(service):
    row = seed(service)
    config = ai_config(service)
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        payload = analysis_fixture() if body["text"]["format"]["name"] == "project_analysis" else lesson_fixture()
        return httpx.Response(200, json=response_for(payload))
    with sdk_client(handler) as client:
        analysis = ai.generate(service.paths, service.store, config, row, NOW, kind="analysis", client=client)
        ai.generate(service.paths, service.store, config, row, NOW, kind="analysis", client=client)
        first = ai.generate(service.paths, service.store, config, row, NOW, kind="tutorial", client=client)
        second = ai.generate(service.paths, service.store, config, row, NOW, kind="tutorial", client=client)
    assert len(requests) == 3 and first["_job_id"] != second["_job_id"]
    assert analysis["_kind"] == "analysis" and first["_kind"] == "tutorial"
    assert requests[0]["model"] == "test-model" and requests[0]["max_output_tokens"] == 4000
    assert requests[1]["model"] == "gpt-6-luna" and requests[1]["max_output_tokens"] == 18000
    assert requests[1]["service_tier"] == "flex" and config["tutorial"]["prompt"] in requests[1]["instructions"]
    assert json.loads(requests[1]["input"])["initial_analysis"]["summary"] == analysis["summary"]
    assert service.store.one("SELECT actual_tier FROM ai_jobs WHERE kind='tutorial'")["actual_tier"] == "flex"


def test_analysis_failure_does_not_block_tutorial(service):
    row = seed(service)
    config = ai_config(service)
    with sdk_client(lambda _: httpx.Response(401, json={"error": {"message": "fake"}})) as client:
        with pytest.raises(RuntimeError):
            ai.generate(service.paths, service.store, config, row, NOW, kind="analysis", client=client)
    with sdk_client(lambda _: httpx.Response(200, json=response_for(lesson_fixture()))) as client:
        assert ai.generate(service.paths, service.store, config, row, NOW, kind="tutorial", client=client)["_kind"] == "tutorial"


def test_tick_only_generates_analysis_never_tutorial(service, monkeypatch):
    seed(service)
    config = ai_config(service)
    service.paths.save(config)
    kinds = []
    monkeypatch.setattr(ai, "generate", lambda *args, **kwargs: kinds.append(kwargs["kind"]))
    service.run("tick")
    assert kinds and set(kinds) == {"analysis"}


def test_html_export_failure_recovers_locally_without_post(service, monkeypatch):
    row = seed(service)
    config = ai_config(service)
    service.paths.save(config)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response_for(lesson_fixture()))
    with sdk_client(handler) as client:
        result = ai.generate(service.paths, service.store, config, row, NOW, client=client)
    import github_stars.service as service_module
    original = service_module.export_tutorial
    monkeypatch.setattr(service_module, "export_tutorial", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError):
        service.generated_result(row, result, config)
    monkeypatch.setattr(service_module, "export_tutorial", original)
    recovered = service.run("recover", repo_id=row["id"], kind="tutorial")
    assert Path(recovered["path"]).exists() and len(requests) == 1
    assert service.store.one("SELECT status FROM ai_jobs")["status"] == "completed"


def test_v1_database_migrates_legacy_jobs_and_preserves_history(tmp_path):
    database = tmp_path / "old.sqlite3"
    with sqlite3.connect(database) as db:
        db.executescript("""CREATE TABLE repos(id INTEGER PRIMARY KEY,name TEXT,metadata TEXT,bucket TEXT,seen_at TEXT,
          readme TEXT DEFAULT '',readme_sha TEXT DEFAULT '',readme_url TEXT DEFAULT '',readme_at TEXT,score REAL DEFAULT 0,reasons TEXT DEFAULT '[]',feedback TEXT DEFAULT 'new');
          CREATE TABLE ai_jobs(id INTEGER PRIMARY KEY,repo_id INTEGER,week TEXT,created TEXT,status TEXT,model TEXT,response_id TEXT,result TEXT,error TEXT,input_tokens INTEGER,output_tokens INTEGER,evidence TEXT);
          INSERT INTO repos(id,name,feedback) VALUES(1,'one/saved','saved'),(2,'two/ignored','dismissed');
          INSERT INTO ai_jobs(id,repo_id,status,model,result,evidence,input_tokens) VALUES(1,1,'completed','old','original-result','{}',123);
          PRAGMA user_version=1;""")
    store = Store(database)
    store.execute("INSERT INTO digests(week,created,note) VALUES ('2026-W44','then','history')")
    store.execute("INSERT INTO selections VALUES ('2026-W44',1,0,'original-snapshot')")
    Store(database)
    assert store.one("SELECT study_state FROM repos WHERE id=1")["study_state"] == "saved"
    assert store.one("SELECT feedback FROM repos WHERE id=2")["feedback"] == "dismissed"
    job = store.one("SELECT * FROM ai_jobs")
    assert job["kind"] == "legacy" and job["result"] == "original-result" and job["input_tokens"] == 123
    assert store.one("SELECT snapshot FROM selections")["snapshot"] == "original-snapshot"
