import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from openai import OpenAI

from github_stars import ai, mailer
from github_stars.config import Paths, validate
from github_stars.github import GitHub, GitHubError
from github_stars.ranking import rank
from github_stars.reports import digest_text, html_document
from github_stars.service import Service
from github_stars.store import exclusive

NOW = datetime(2026, 11, 6, 19, 5, tzinfo=ZoneInfo("Asia/Shanghai"))


def repository(number, topic="deepfake", stars=500):
    return {"id": number, "full_name": f"owner{number}/project{number}", "description": f"{topic} detection toolkit",
            "topics": [topic], "stargazers_count": stars, "pushed_at": "2026-11-01T00:00:00Z",
            "created_at": "2026-09-01T00:00:00Z", "archived": False, "fork": False,
            "language": "Python", "license": {"spdx_id": "MIT"}, "html_url": f"https://github.com/owner{number}/project{number}"}


class FakeGitHub:
    calls = 0

    def __init__(self, token):
        pass

    def search(self, *args):
        self.calls += 1
        return [repository(1), repository(2), repository(3), repository(4, "agent"), repository(5, "shopping")]

    def readme(self, name):
        return ("# Tool\nA useful research repository.\n## Installation\npip install example\n" * 10, "blob-sha", f"https://github.com/{name}/blob/main/README.md")

    def close(self):
        pass


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(Paths, "secret", lambda *_: "")  # 测试从不使用用户真实密钥。
    return Service(Paths(tmp_path), github_factory=FakeGitHub, clock=lambda: NOW)


def seed(service):
    service.run("scan")
    return service.store.one("SELECT * FROM repos WHERE id=1")


def ai_config(service):
    config = service.paths.load()
    config["ai"].update(enabled=True, model="test-model")
    return config


def mail_config(service):
    config = service.paths.load()
    config["email"].update(enabled=True, host="smtp.invalid", sender="sender@example.com", recipient="reader@example.com")
    return config


def test_defaults_and_corrupt_config_are_not_overwritten(service):
    config = service.paths.load()
    assert not config["ai"]["enabled"] and not config["email"]["enabled"]
    assert config["digest"]["max_projects"] == 3
    service.paths.settings.write_text("schedule: broken", encoding="utf-8")
    with pytest.raises(ValueError):
        service.paths.load()
    assert service.paths.settings.read_text() == "schedule: broken"


@pytest.mark.parametrize("section,key,value", [("digest", "max_projects", 0), ("digest", "hot_slots", 7),
                                               ("schedule", "daily_hour", True), ("email", "security", "plain"),
                                               ("discovery", "research_queries", []), ("ai", "enabled", "false")])
def test_invalid_settings(service, section, key, value):
    config = service.paths.load()
    config[section][key] = value
    with pytest.raises(ValueError):
        validate(config)


def test_scan_deduplicates_snapshots_and_reuses_readmes(service):
    seed(service)
    service.run("scan")
    assert service.store.one("SELECT count(*) n FROM repos")["n"] == 5
    assert service.store.one("SELECT count(*) n FROM snapshots")["n"] == 5
    assert service.store.state("last_scan_day") == "2026-11-06"


def test_digest_cap_ratio_dedup_and_snapshot(service):
    seed(service)
    week = service.run("digest")
    rows = service.store.rows("SELECT * FROM selections WHERE week=?", (week,))
    assert len(rows) == 3
    assert sum(json.loads(r["snapshot"])["bucket"] == "hot" for r in rows) == 1
    service.run("digest")
    assert service.store.one("SELECT count(*) n FROM selections")["n"] == 3
    before = digest_text(service.store, week)
    service.store.execute("UPDATE repos SET name='changed/name'")
    assert digest_text(service.store, week) == before  # 历史周报保存当时入选证据。


def test_dismissed_unrelated_and_weak_evidence_do_not_enter_digest(service):
    seed(service)
    service.store.execute("UPDATE repos SET feedback='dismissed' WHERE id=1")
    service.store.execute("UPDATE repos SET readme='' WHERE id IN (2,3)")
    week = service.run("digest")
    assert [r["repo_id"] for r in service.store.rows("SELECT * FROM selections WHERE week=?", (week,))] == [4]
    assert service.store.one("SELECT score FROM repos WHERE id=5")["score"] == 0


def test_cooldown_across_weeks(service):
    seed(service)
    week = service.run("digest")
    previous = {r["repo_id"] for r in service.store.rows("SELECT * FROM selections WHERE week=?", (week,))}
    service.clock = lambda: NOW + timedelta(days=7)
    service.run("scan")
    new_week = service.run("digest")
    assert new_week != week
    assert not previous.intersection(r["repo_id"] for r in service.store.rows("SELECT * FROM selections WHERE week=?", (new_week,)))


def test_partial_scan_does_not_seal_week(service):
    class Broken(FakeGitHub):
        def search(self, *args):
            raise GitHubError("GitHub 请求受限")
    service.github_factory = Broken
    assert "部分完成" in service.run("scan")
    assert service.store.state("last_scan_day") == ""
    with pytest.raises(ValueError, match="未完整成功"):
        service.run("digest")


def test_tick_daily_idempotence_and_no_default_paid_calls(service):
    service.run("tick")
    service.run("tick")
    assert service.store.one("SELECT count(*) n FROM scans")["n"] == 1
    assert service.store.one("SELECT count(*) n FROM digests")["n"] == 1
    assert service.store.one("SELECT count(*) n FROM ai_jobs")["n"] == 0
    assert service.store.one("SELECT mail_state FROM digests")["mail_state"] == "pending"


def test_tick_before_due_and_disabled(service):
    service.clock = lambda: NOW.replace(hour=8)
    service.run("tick")
    assert not service.store.rows("SELECT * FROM scans")
    config = service.paths.load()
    config["schedule"]["enabled"] = False
    service.paths.save(config)
    service.clock = lambda: NOW
    assert "关闭" in service.run("tick")


def test_restart_marks_uncertain_calls_and_email(service):
    seed(service)
    week = service.run("digest")
    service.store.execute("UPDATE digests SET mail_state='sending'")
    service.store.execute("INSERT INTO ai_jobs(repo_id,week,created,status,model,evidence) VALUES (1,?,?,'submitting','test','{}')", (week, NOW.isoformat()))
    service.run("tick")
    assert service.store.one("SELECT status FROM ai_jobs")["status"] == "unknown"
    assert service.store.one("SELECT mail_state FROM digests")["mail_state"] == "unknown"


def test_growth_requires_distinct_days(service):
    row = seed(service)
    config = service.paths.load()
    _, _, reasons = rank(row, config, NOW)
    assert any("增速未知" in r for r in reasons)
    _, _, reasons = rank(row, config, NOW, {"stars": 400, "day": "2026-11-04"})
    assert any("+100" in r and "2 天" in r for r in reasons)


def test_lock_blocks_concurrent_work_and_releases(service):
    with exclusive(service.paths.data / "worker.lock"):
        with pytest.raises(RuntimeError, match="正在运行"):
            service.run("scan")
    seed(service)


def response_payload(status="completed", text=None):
    tutorial = {key: f"中文 {key}，依据 README，未执行" for key in ("summary", "relevance", "tutorial", "limitations")}
    return {"id": "resp_test", "created_at": 1793963100, "object": "response", "model": "test-model", "status": status,
            "output": [{"type": "message", "id": "msg_test", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text if text is not None else json.dumps(tutorial), "annotations": []}]}],
            "usage": {"input_tokens": 120, "output_tokens": 80, "total_tokens": 200}}


def sdk_client(handler):
    return OpenAI(api_key="fake-test-key", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_real_sdk_structured_request_cache_and_usage(service):
    row = seed(service)
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload())
    with sdk_client(handler) as client:
        result = ai.generate(service.paths, service.store, ai_config(service), row, NOW, client=client)
        ai.generate(service.paths, service.store, ai_config(service), row, NOW, client=client)
    assert result["summary"].startswith("中文")
    assert len(requests) == 1
    assert requests[0]["text"]["format"]["type"] == "json_schema"
    assert requests[0]["max_output_tokens"] == 5000
    job = service.store.one("SELECT * FROM ai_jobs")
    assert job["status"] == "completed" and job["input_tokens"] == 120 and job["output_tokens"] == 80
    assert "_sha" in json.loads(job["result"])


def test_network_timeout_blocks_auto_resubmit(service):
    row = seed(service)
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("network lost", request=request)
    with sdk_client(handler) as client:
        with pytest.raises(RuntimeError, match="未知"):
            ai.generate(service.paths, service.store, ai_config(service), row, NOW, client=client)
        with pytest.raises(ValueError, match="不会重复"):
            ai.generate(service.paths, service.store, ai_config(service), row, NOW, client=client)
    assert len(requests) == 1
    assert service.store.one("SELECT status FROM ai_jobs")["status"] == "unknown"


@pytest.mark.parametrize("status,text", [("incomplete", None), ("completed", "not JSON")])
def test_invalid_response_keeps_usage_and_raw_result(service, status, text):
    row = seed(service)
    with sdk_client(lambda req: httpx.Response(200, json=response_payload(status, text))) as client:
        with pytest.raises(RuntimeError):
            ai.generate(service.paths, service.store, ai_config(service), row, NOW, client=client)
    job = service.store.one("SELECT * FROM ai_jobs")
    assert job["status"] == "invalid" and job["response_id"] == "resp_test"
    assert job["input_tokens"] == 120 and "output" in json.loads(job["result"])


def test_weekly_ai_cap_counts_failed_requests(service):
    row = seed(service)
    config = ai_config(service)
    config["ai"]["max_calls_per_week"] = 1
    with sdk_client(lambda req: httpx.Response(401, json={"error": {"message": "bad key"}})) as client:
        with pytest.raises(RuntimeError):
            ai.generate(service.paths, service.store, config, row, NOW, client=client)
        with pytest.raises(ValueError, match="每周 AI"):
            ai.generate(service.paths, service.store, config, row, NOW, retry=True, client=client)


def test_recover_received_response_uses_local_copy_without_new_request(service):
    row = seed(service)
    service.store.execute("""INSERT INTO ai_jobs(repo_id,week,created,status,model,response_id,result,evidence)
                         VALUES (1,'2026-W45',?,'received','original-model','resp_test',?,?)""",
                         (NOW.isoformat(), json.dumps(response_payload()), json.dumps({"sha": "original-sha", "captured": "then"})))
    result = ai.recover(service.paths, service.store, row["id"], NOW)
    assert result["_sha"] == "original-sha"
    assert service.store.one("SELECT count(*) n FROM ai_jobs")["n"] == 1
    assert service.store.one("SELECT status FROM ai_jobs")["status"] == "completed"


def test_recover_known_id_only_gets_original_response(service):
    row = seed(service)
    service.store.execute("""INSERT INTO ai_jobs(repo_id,week,created,status,model,response_id,evidence)
                         VALUES (1,'2026-W45',?,'unknown','original-model','resp_test','{}')""", (NOW.isoformat(),))
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response_payload())
    with sdk_client(handler) as client:
        ai.recover(service.paths, service.store, row["id"], NOW, client=client)
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == "/v1/responses/resp_test"
    assert service.store.one("SELECT input_tokens FROM ai_jobs")["input_tokens"] == 120


def test_upgrade_reuses_config_database_and_user_feedback(service):
    seed(service)
    config = service.paths.load()
    config["profile"]["description"] = "个人研究方向"
    service.paths.save(config)
    service.store.execute("UPDATE repos SET feedback='saved' WHERE id=1")
    reopened = Service(Paths(service.paths.root), github_factory=FakeGitHub, clock=lambda: NOW)
    assert reopened.paths.load()["profile"]["description"] == "个人研究方向"
    assert reopened.store.one("SELECT feedback FROM repos WHERE id=1")["feedback"] == "saved"


def test_higher_schema_is_not_downgraded(service):
    service.store.execute("PRAGMA user_version=2")
    with pytest.raises(RuntimeError, match="更新版本"):
        Service(service.paths)


class SMTP:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_message(self, message):
        self.sent.append(message)
        if self.fail:
            raise OSError("connection lost after DATA")

    def close(self):
        pass


def test_email_sent_once_and_escaped_html(service):
    seed(service)
    week = service.run("digest")
    smtp = SMTP()
    for _ in range(2):
        mailer.send_digest(service.paths, service.store, mail_config(service), week, NOW, factory=lambda: smtp)
    assert len(smtp.sent) == 1
    assert "GitHub Stars++" in smtp.sent[0]["Subject"]
    assert "<script>" not in html_document("<script>alert(1)</script>")
    assert service.store.one("SELECT mail_state FROM digests")["mail_state"] == "sent"


def test_email_unknown_requires_explicit_retry(service):
    seed(service)
    week = service.run("digest")
    smtp = SMTP(fail=True)
    with pytest.raises(RuntimeError, match="未知"):
        mailer.send_digest(service.paths, service.store, mail_config(service), week, NOW, factory=lambda: smtp)
    with pytest.raises(ValueError, match="上次发送结果未知"):
        mailer.send_digest(service.paths, service.store, mail_config(service), week, NOW, factory=lambda: smtp)
    assert len(smtp.sent) == 1
    smtp.fail = False
    mailer.send_digest(service.paths, service.store, mail_config(service), week, NOW, retry=True, factory=lambda: smtp)
    assert len(smtp.sent) == 2


def test_email_preflight_failure_is_safe_to_retry(service):
    seed(service)
    week = service.run("digest")
    def broken():
        raise OSError("could not connect")
    with pytest.raises(RuntimeError, match="尚未发送"):
        mailer.send_digest(service.paths, service.store, mail_config(service), week, NOW, factory=broken)
    assert service.store.one("SELECT mail_state FROM digests")["mail_state"] == "failed"


def test_github_rate_limit_and_incomplete_results_are_explicit():
    with httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(lambda req: httpx.Response(429, headers={"retry-after": "60"}))) as client:
        with pytest.raises(GitHubError, match="受限"):
            GitHub(client=client).search("test", 2)
    with httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"incomplete_results": True, "items": []}))) as client:
        with pytest.raises(GitHubError, match="不完整"):
            GitHub(client=client).search("test", 2)
