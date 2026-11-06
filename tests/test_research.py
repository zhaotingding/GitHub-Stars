"""Research integration checks use real SDK serialization and an offline HTTP transport."""
import json
import time
from datetime import timedelta

import httpx
import pytest
from test_workflow import NOW, repository, response_payload, sdk_client

from github_stars.config import Paths
from github_stars.service import Service


def answer(label="R1", *, agent=False):
    value = {"claims": [{"text": "README 作者描述了机器人感知能力，尚未实测。", "sources": [label]}],
             "limitations": ["仅依据保存的 README，未运行项目。"]}
    return {"action": "answer", "terms": [], "source": "", **value} if agent else value


def action(name, source="", terms=None):
    return {"action": name, "terms": terms or [], "source": source, "claims": [], "limitations": []}


def reply(value=None, *, status="completed", identity="resp_research", usage=True):
    payload = response_payload(status, json.dumps(value if value is not None else answer(), ensure_ascii=False))
    payload["id"] = identity
    payload["model"] = "actual-research-model"
    payload["service_tier"] = "default"
    if not usage:
        payload["usage"] = None
    return payload


def configure(service, **settings):
    config = service.paths.load()
    config["ai"].update(enabled=True, model="fallback-model", credential_source="msgx")
    config["research"].update({"model": "research-model", "input_cny_per_million": 1.0,
                               "output_cny_per_million": 2.0, "max_cost_cny": 1.0, **settings})
    service.paths.save(config)
    return config


def put_repository(service, identity=1, *, text=None, topic="robotics", sha=None):
    data = repository(identity, topic)
    service.store.upsert(data, "research", NOW)
    service.store.cache_readme(identity, text or ("# Robotics toolkit\nA robot perception and vision project.\n" * 90),
                               sha or f"sha-{identity}", f"https://github.com/owner{identity}/project{identity}/blob/main/README.md",
                               NOW.isoformat())


@pytest.fixture
def research_service(tmp_path, monkeypatch):
    def no_secret(*_args, **_kwargs):
        raise AssertionError("isolated research tests must never read user credentials")
    monkeypatch.setattr(Paths, "secret", no_secret)
    service = Service(Paths(tmp_path), clock=lambda: NOW)
    configure(service)
    put_repository(service)
    return service


def install_transport(service, handler):
    requests, selected_settings = [], []
    def transport(request):
        requests.append(request)
        return handler(request)
    def factory(settings):
        selected_settings.append(dict(settings))
        return sdk_client(transport)
    service.research_client_factory = factory
    return requests, selected_settings


def start(service, **kwargs):
    return service.run("research", question="机器人感知项目有什么证据", **kwargs)["research_job"]


def get_body(request):
    return json.loads(request.content)


def model_input(request):
    return json.loads(get_body(request)["input"])


def test_standard_answer_freezes_citable_sources_and_records_sdk_usage(research_service):
    service = research_service
    requests, settings = install_transport(service, lambda _: httpx.Response(200, json=reply()))
    job = start(service)
    assert job["state"] == "done" and job["calls"] == 1
    assert job["result"] == answer()
    assert {source["label"] for source in job["sources"]} == {"R1"}
    source = job["sources"][0]
    assert source["sha"] == "sha-1" and source["captured"] == NOW.isoformat()
    assert source["url"].startswith("https://github.com/")
    body = get_body(requests[0])
    assert body["model"] == "research-model" and body["store"] is True
    assert body["text"]["format"]["type"] == "json_schema" and body["text"]["format"]["strict"] is True
    assert "低权限" in body["instructions"] and "不能声称已验证" in body["instructions"]
    assert settings[0]["credential_source"] == "msgx"
    step = service.store.research_steps(job["id"])[0]
    assert step["applied"] == 1 and step["response_id"] == "resp_research"
    assert (step["input_tokens"], step["output_tokens"], step["actual_model"]) == (120, 80, "actual-research-model")
    assert step["cost"] == pytest.approx(.00028)
    assert json.loads(step["response"])["output"]
    assert service.store.one("SELECT count(*) n FROM ai_jobs")["n"] == 0
    assert start(service, job_id=job["id"])["result"] == answer()
    assert service.run("research_resume", job_id=job["id"])["research_job"]["state"] == "done"
    assert len(requests) == 1


def test_no_local_match_has_no_model_or_credential_request(research_service):
    requests, _ = install_transport(research_service, lambda _: pytest.fail("no matching evidence must not call API"))
    job = research_service.run("research", question="量子纠错拓扑编码", repo_ids=[1])["research_job"]
    assert job["state"] == "empty" and job["calls"] == 0 and not requests
    assert not job["result"] and "没有命中" in job["error"]


def test_queued_response_get_resume_requires_explicit_continue_and_original_scope(research_service):
    service = research_service
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=reply(action("preferences"), identity="resp_queued"))
        return httpx.Response(200, json=reply(status="queued", identity="resp_queued", usage=False) if len(requests) == 1
                              else reply(answer(agent=True), identity="resp_final"))
    requests, _ = install_transport(service, handler)
    job = start(service, mode="agent", repo_ids=[1])
    assert job["state"] == "paused" and job["can_resume"]
    original = service.store.research_job(job["id"])
    put_repository(service, text="REPLACED EVIDENCE unrelated astronomy", sha="changed")
    put_repository(service, 2, text="robotics NEW OUTSIDE SCOPE")
    config = service.paths.load()
    config["research"]["model"] = "new-expensive-model"
    config["profile"]["description"] = "changed profile"
    service.paths.save(config)
    recovered = service.run("research_resume", job_id=job["id"])["research_job"]
    assert recovered["state"] == "continuable" and recovered["can_continue"]
    assert [request.method for request in requests] == ["POST", "GET"]
    assert requests[1].url.path == "/v1/responses/resp_queued"
    completed = service.run("research_continue", job_id=job["id"])["research_job"]
    assert completed["state"] == "done" and len(requests) == 3
    assert get_body(requests[2])["model"] == "research-model"
    body = model_input(requests[2])
    assert "REPLACED EVIDENCE" not in json.dumps(body) and "NEW OUTSIDE SCOPE" not in json.dumps(body)
    assert body["preferences"]["profile"] == original["settings"]["profile"]
    assert service.store.research_job(job["id"])["scope"] == original["scope"]
    assert service.store.research_steps(job["id"])[0]["applied"] == 1


def test_unknown_submission_is_not_reposted_by_same_id_resume_or_continue(research_service):
    service = research_service
    def lost(request):
        raise httpx.ReadTimeout("mock connection lost", request=request)
    requests, _ = install_transport(service, lost)
    identity = "a" * 32
    job = start(service, job_id=identity)
    assert job["state"] == "blocked" and not job["can_resume"]
    assert start(service, job_id=identity)["id"] == identity
    with pytest.raises(ValueError, match="没有可恢复"):
        service.run("research_resume", job_id=identity)
    with pytest.raises(ValueError, match="不能继续"):
        service.run("research_continue", job_id=identity)
    assert len(requests) == 1 and requests[0].method == "POST"
    assert service.store.research_steps(identity)[0]["state"] == "unknown"
    with pytest.raises(ValueError, match="同一编号"):
        service.run("research", question="更换研究问题", job_id=identity)


@pytest.mark.parametrize("value", [action("shell", terms=["robot"]),
                                  {**action("preferences"), "exec": "rm -rf /"},
                                  {**action("preferences"), "claims": answer()["claims"]},
                                  {**answer(agent=True), "source": "R1"},
                                  answer("R999", agent=True),
                                  action("image", "Iunselected")])
def test_invalid_action_or_citation_stops_without_fixup_post(research_service, value):
    service = research_service
    requests, _ = install_transport(service, lambda _: httpx.Response(200, json=reply(value)))
    job = start(service, mode="agent")
    assert job["state"] == "failed" and len(requests) == 1
    assert not job["result"] and service.store.research_job(job["id"])["tools"] == 0
    step = service.store.research_steps(job["id"])[0]
    assert not step["applied"] and step["input_tokens"] == 120 and step["response_id"]
    again = service.run("research_resume", job_id=job["id"])["research_job"]
    assert again["state"] == "failed" and len(requests) == 1


def test_selected_tools_only_search_frozen_scope_expand_source_and_history(research_service):
    service = research_service
    configure(service, max_calls=6, max_tools=4)
    put_repository(service, 2, text="# Astronomy\nA stellar nebula atlas.", topic="astronomy")
    service.store.execute("INSERT INTO research_documents(repo_id,sha,text,url,captured) VALUES(1,'older',?,?,?)",
                          ("Old robot README historical version", "https://github.com/owner1/project1/blob/old/README.md",
                           (NOW-timedelta(days=2)).isoformat()))
    service.store.execute("INSERT INTO snapshots VALUES(1,?,400)", ((NOW-timedelta(days=2)).date().isoformat(),))
    replies = [action("search", terms=["nebula"]), action("read_source", "R1"), action("history", "R1"),
               action("preferences"), answer(agent=True)]
    requests, _ = install_transport(service, lambda _: httpx.Response(200, json=reply(replies[len(requests)-1], identity=f"resp_{len(requests)}")))
    job = start(service, mode="agent")
    assert job["state"] == "done" and len(requests) == 5
    assert service.store.research_job(job["id"])["tools"] == 4
    inputs = [model_input(request) for request in requests]
    assert "R2" not in {source["label"] for source in inputs[0]["evidence"]}
    assert "R2" in {source["label"] for source in inputs[1]["evidence"]}
    assert len(next(source["text"] for source in inputs[2]["evidence"] if source["label"] == "R1")) > 2400
    assert any(source["kind"] == "readme_version" for source in inputs[3]["evidence"])
    assert [row["change_since_previous"] for row in job["organization"]["timeline"] if row["repo_id"] == 1] == [None, 100]
    assert not service.store.rows("SELECT * FROM research_bookmarks")


@pytest.mark.parametrize("limits,expected_tools", [({"max_calls": 1}, 1), ({"max_tools": 0}, 0)])
def test_call_and_tool_limits_stop_before_next_api(research_service, limits, expected_tools):
    service = research_service
    configure(service, **limits)
    requests, _ = install_transport(service, lambda _: httpx.Response(200, json=reply(action("preferences"))))
    job = start(service, mode="agent")
    assert job["state"] == "limited" and len(requests) == 1
    assert service.store.research_job(job["id"])["tools"] == expected_tools


def test_absolute_deadline_is_not_reset_after_returned_tool(research_service, monkeypatch):
    service = research_service
    current = [time.time()]
    monkeypatch.setattr("github_stars.research.time.time", lambda: current[0])
    def handler(_):
        current[0] += 181
        return httpx.Response(200, json=reply(action("preferences")))
    requests, _ = install_transport(service, handler)
    job = start(service, mode="agent")
    assert job["state"] == "limited" and len(requests) == 1
    deadline = service.store.research_job(job["id"])["settings"]["deadline"]
    with pytest.raises(ValueError, match="不能继续"):
        service.run("research_continue", job_id=job["id"])
    assert service.store.research_job(job["id"])["settings"]["deadline"] == deadline and len(requests) == 1


def test_budget_and_unknown_rates_block_before_post(research_service):
    service = research_service
    configure(service, max_cost_cny=.01, input_cny_per_million=1000.0)
    requests, _ = install_transport(service, lambda _: pytest.fail("insufficient local budget must block submission"))
    job = start(service)
    assert job["state"] == "limited" and job["calls"] == 0 and not requests
    config = service.paths.load()
    config["research"]["input_cny_per_million"] = 0.0
    service.paths.save(config)
    job = start(service)
    assert job["state"] == "failed" and "费率" in job["error"] and not requests


def test_unknown_usage_prevents_additional_charged_step(research_service):
    requests, _ = install_transport(research_service, lambda _: httpx.Response(200, json=reply(action("preferences"), usage=False)))
    job = start(research_service, mode="agent")
    assert job["state"] == "limited" and len(requests) == 1 and "用量未知" in job["error"]


def test_failed_requests_count_toward_weekly_research_cap(research_service):
    service = research_service
    configure(service, max_calls_per_week=1)
    requests, _ = install_transport(service, lambda _: httpx.Response(401, json={"error": {"message": "bad test key"}}))
    first = start(service)
    second = start(service)
    assert first["state"] == "failed" and second["state"] == "limited"
    assert len(requests) == 1 and second["calls"] == 0
    assert "本周" in second["error"]


def test_raw_response_survives_atomic_application_failure_and_local_resume(research_service):
    service = research_service
    service.store.execute("CREATE TRIGGER block_research_result BEFORE UPDATE OF result ON research_jobs BEGIN SELECT RAISE(ABORT, 'disk simulation'); END")
    requests, _ = install_transport(service, lambda _: httpx.Response(200, json=reply()))
    job = start(service)
    assert job["state"] == "paused" and len(requests) == 1
    assert not job["result"] and not service.store.research_steps(job["id"])[0]["applied"]
    assert service.store.research_steps(job["id"])[0]["response"]
    service.store.execute("DROP TRIGGER block_research_result")
    resumed = service.run("research_resume", job_id=job["id"])["research_job"]
    assert resumed["state"] == "done" and len(requests) == 1


def test_cancel_after_response_acceptance_saves_usage_but_runs_no_next_tool(research_service):
    service = research_service
    identity = "b" * 32
    def handler(_):
        stopped = service.run("research_cancel", job_id=identity)
        assert stopped["state"] == "cancelled"
        return httpx.Response(200, json=reply(action("search", terms=["robot"])))
    requests, _ = install_transport(service, handler)
    job = start(service, mode="agent", job_id=identity)
    assert job["state"] == "cancelled" and len(requests) == 1
    assert service.store.research_job(identity)["tools"] == 0
    step = service.store.research_steps(identity)[0]
    assert step["response_id"] and step["input_tokens"] == 120 and step["applied"]


def test_bookmark_keeps_only_answer_source_pointers_after_expiration(research_service):
    service = research_service
    install_transport(service, lambda _: httpx.Response(200, json=reply()))
    job = start(service)
    assert service.run("research_bookmark", job_id=job["id"], saved=True)["saved"]
    service.run("research_feedback", job_id=job["id"], rating="useful")
    saved = service.store.one("SELECT * FROM research_bookmarks WHERE id=?", (job["id"],))
    assert all("text" not in source and "body" not in source for source in json.loads(saved["sources"]))
    next_job = start(service)
    assert any(weight > 0 for weight in service.store.research_job(next_job["id"])["settings"]["feedback_weights"].values())
    service.store.execute("UPDATE research_jobs SET expires=0 WHERE id=?", (job["id"],))
    service.store.research_prune()
    archived = service.run("research_status", job_id=job["id"])
    assert archived["state"] == "archived" and archived["result"] == answer()
    assert not archived["can_resume"] and not archived["can_continue"]


def test_creation_week_and_weekly_cap_stay_frozen_after_resume(research_service):
    service = research_service
    configure(service, max_calls_per_week=1)
    def handler(request):
        return httpx.Response(200, json=reply(action("preferences"), identity="resp_week",
                                               status="queued" if request.method == "POST" else "completed"))
    requests, _ = install_transport(service, handler)
    job = start(service, mode="agent")
    service.clock = lambda: NOW + timedelta(days=7)
    assert service.run("research_resume", job_id=job["id"])["research_job"]["state"] == "continuable"
    limited = service.run("research_continue", job_id=job["id"])["research_job"]
    assert limited["state"] == "limited" and "本周" in limited["error"]
    assert [request.method for request in requests] == ["POST", "GET"]
    assert service.store.research_steps(job["id"])[0]["prepared"]["week"] == "2026-W45"


def test_process_interruption_is_marked_unknown_without_new_post(research_service):
    service = research_service
    class ProcessStopped(BaseException):
        pass
    def interrupted(_):
        raise ProcessStopped()
    requests, _ = install_transport(service, interrupted)
    identity = "c" * 32
    with pytest.raises(ProcessStopped):
        start(service, job_id=identity)
    assert service.store.research_steps(identity)[0]["state"] == "submitting"
    reopened = Service(service.paths, clock=lambda: NOW, research_client_factory=service.research_client_factory)
    with pytest.raises(ValueError, match="不能继续"):
        reopened.run("research_continue", job_id=identity)
    assert reopened.run("research_status", job_id=identity)["state"] == "blocked"
    assert reopened.store.research_steps(identity)[0]["state"] == "unknown" and len(requests) == 1


def test_actual_returned_usage_can_stop_followup_even_when_initial_reserve_fit(research_service):
    service = research_service
    def high_usage(_):
        payload = reply(action("preferences"))
        payload["usage"] = {"input_tokens": 2_000_000, "output_tokens": 80, "total_tokens": 2_000_080}
        return httpx.Response(200, json=payload)
    requests, _ = install_transport(service, high_usage)
    job = start(service, mode="agent")
    assert job["state"] == "limited" and len(requests) == 1
    assert service.store.research_steps(job["id"])[0]["cost"] > 1.0
    assert "预算" in job["error"]


def test_cancellation_during_client_preparation_blocks_post(research_service):
    service = research_service
    identity = "d" * 32
    requests = []
    def factory(_):
        service.run("research_cancel", job_id=identity)
        return sdk_client(lambda request: requests.append(request) or pytest.fail("cancelled task cannot submit"))
    service.research_client_factory = factory
    job = start(service, job_id=identity)
    assert job["state"] == "cancelled" and not requests
    assert service.store.research_steps(identity)[0]["state"] == "prepared"
