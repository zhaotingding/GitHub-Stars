"""Browser feature flows use temporary storage and offline model responses only."""
import json
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
from test_research import answer, configure, install_transport, put_repository, reply
from test_web import finished, submit
from test_workflow import NOW, repository

from github_stars.config import Paths
from github_stars.service import Service
from github_stars.store import STUDY_STATES
from github_stars.web import WebServer


@pytest.fixture
def isolated_service(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("isolated web feature flows must not use credentials or external services")

    monkeypatch.setattr(Paths, "secret", forbidden)
    paths = Paths(tmp_path)
    config = paths.load()
    config["schedule"]["enabled"] = False
    config["ai"]["auto_analyze"] = False
    paths.save(config)
    return Service(paths, github_factory=forbidden, research_client_factory=forbidden, clock=lambda: NOW)


@contextmanager
def browser_session(service):
    server = WebServer(service.paths, port=0, service=service, schedule=False)
    server.start()
    client = httpx.Client(base_url=server.url, timeout=5, trust_env=False)
    try:
        assert client.get("/").status_code == 200
        token = client.get("/api/state").json()["csrf"]
        client.headers.update({"Origin": server.url.rstrip("/"), "X-Stars-CSRF": token})
        yield server, client
    finally:
        deadline = time.monotonic() + 5
        while server.http.app.busy and time.monotonic() < deadline:
            time.sleep(.01)
        assert not server.http.app.busy, "test must release its background worker"
        client.close()
        server.close()


@pytest.fixture
def feature_browser(isolated_service):
    with browser_session(isolated_service) as session:
        yield session


def control(client, action, **args):
    return client.post("/api/control", json={"action": action, "args": args})


def complete_research(server, client):
    service = server.http.app.service
    configure(service)
    put_repository(service)
    requests, _ = install_transport(service, lambda _: httpx.Response(200, json=reply()))
    identity = submit(client, "research", {"question": "机器人感知项目有什么证据", "mode": "standard", "repo_ids": [1]})
    assert finished(server, identity)["state"] == "done"
    job = client.get("/api/research", params={"id": identity}).json()
    assert job["state"] == "done" and len(requests) == 1
    return identity, requests


def test_project_search_queries_saved_metadata_without_fetching_or_generating(feature_browser):
    server, client = feature_browser
    store = server.http.app.store
    store.upsert(repository(1, "Robotics"), "research", NOW)
    store.upsert(repository(2, "astronomy"), "research", NOW)

    def names(query):
        response = client.get("/api/projects", params={"q": query})
        assert response.status_code == 200
        return [row["name"] for row in response.json()["projects"]]

    assert set(names("")) == {"owner1/project1", "owner2/project2"}
    assert names("ROBOTICS") == ["owner1/project1"]
    assert names("OWNER2/PROJECT2") == ["owner2/project2"]
    assert names("不存在的研究方向") == []
    assert names("%' OR 1=1 --") == []
    assert client.get("/api/projects", params={"q": "x" * 201}).status_code == 400
    assert not store.rows("SELECT * FROM ai_jobs")
    assert not store.rows("SELECT * FROM web_operations")


def test_project_details_without_saved_readme_do_not_fetch_or_generate(feature_browser):
    server, client = feature_browser
    store = server.http.app.store
    item = repository(1)
    item["description"] = '<script>window.untrusted = true</script> 研究资料'
    store.upsert(item, "research", NOW)

    for _ in range(2):
        response = client.get("/api/project", params={"id": 1})
        assert response.status_code == 200
        project = response.json()
        assert project["readme"] == "" and project["analysis"] is None and project["jobs"] == []
        assert project["metadata"]["description"] == item["description"]
        assert project["study_state"] == "pending"
    assert client.get("/api/project", params={"id": 999}).status_code == 404
    assert client.get("/api/project", params={"id": "invalid"}).status_code == 400
    assert client.get("/api/tutorial", params={"id": 1}).status_code == 404
    assert not store.rows("SELECT * FROM ai_jobs")
    assert not store.rows("SELECT * FROM research_documents")
    assert not store.rows("SELECT * FROM web_operations")


def test_all_study_states_survive_browser_and_service_restart(isolated_service):
    isolated_service.store.upsert(repository(1), "research", NOW)
    with browser_session(isolated_service) as (_, client):
        for state in STUDY_STATES:
            response = control(client, "study_state", repo_id=1, state=state)
            assert response.status_code == 200
            assert client.get("/api/project?id=1").json()["study_state"] == state
            assert client.get("/api/state").json()["projects"][0]["study_state"] == state
        assert control(client, "study_state", repo_id=1, state="unsupported").status_code == 400
        expected = state
    reopened = Service(isolated_service.paths, clock=lambda: NOW)
    with browser_session(reopened) as (_, client):
        assert client.get("/api/project?id=1").json()["study_state"] == expected
        assert client.get("/api/state").json()["projects"][0]["study_state"] == expected
        assert not reopened.store.rows("SELECT * FROM ai_jobs")


def test_answer_citations_bookmark_feedback_and_history_remain_local_after_restart(isolated_service):
    with browser_session(isolated_service) as (server, client):
        identity, requests = complete_research(server, client)
        job = client.get("/api/research", params={"id": identity}).json()
        assert job["result"] == answer() and job["calls"] == 1
        source = next(source for source in job["sources"] if source["label"] == "R1")
        assert source["sha"] == "sha-1" and source["captured"] == NOW.isoformat()
        assert "robot perception" in source["text"]
        assert source["url"] == "https://github.com/owner1/project1/blob/main/README.md"
        assert job["result"]["claims"][0]["sources"] == [source["label"]]
        assert control(client, "research_bookmark", job_id=identity, saved=True).json()["saved"]
        assert client.get("/api/state").json()["bookmarks"][0]["id"] == identity
        assert control(client, "research_bookmark", job_id=identity, saved=False).json()["saved"] is False
        assert client.get("/api/state").json()["bookmarks"] == []
        assert control(client, "research_bookmark", job_id=identity, saved=True).json()["saved"]
        for rating, expected in (("useful", "useful"), ("irrelevant", "irrelevant"), ("clear", ""), ("useful", "useful")):
            response = control(client, "research_feedback", job_id=identity, rating=rating)
            assert response.status_code == 200 and response.json()["feedback"] == expected
        assert len(requests) == 1

    reopened = Service(isolated_service.paths, clock=lambda: NOW)
    with browser_session(reopened) as (_, client):
        for _ in range(2):
            state = client.get("/api/state").json()
            assert identity in {item["id"] for item in state["research"]}
            assert identity in {item["id"] for item in state["bookmarks"]}
            restored = client.get("/api/research", params={"id": identity}).json()
            assert restored["saved"] and restored["feedback"] == "useful"
            assert restored["result"] == answer() and restored["sources"] == job["sources"]
        assert len(requests) == 1
        assert len(reopened.store.research_steps(identity)) == 1


def test_expired_bookmark_can_be_read_and_removed_without_model(feature_browser):
    server, client = feature_browser
    identity, requests = complete_research(server, client)
    assert control(client, "research_bookmark", job_id=identity, saved=True).status_code == 200
    store = server.http.app.store
    store.execute("UPDATE research_jobs SET expires=? WHERE id=?", (time.time() - 1, identity))
    store.research_prune()

    archived = client.get("/api/research", params={"id": identity}).json()
    assert archived["state"] == "archived" and archived["saved"]
    assert archived["result"] == answer()
    assert archived["sources"][0]["sha"] == "sha-1" and "text" not in archived["sources"][0]
    assert not archived["can_resume"] and not archived["can_continue"]
    response = control(client, "research_bookmark", job_id=identity, saved=False)
    assert response.status_code == 200 and response.json()["state"] == "deleted"
    assert client.get("/api/state").json()["bookmarks"] == []
    assert client.get("/api/research", params={"id": identity}).status_code == 400
    assert len(requests) == 1


def test_unfinished_answer_and_invalid_control_values_cannot_create_feedback_or_bookmarks(feature_browser):
    server, client = feature_browser
    identity = submit(client, "research", {"question": "没有资料的研究问题", "mode": "standard"})
    assert finished(server, identity)["state"] == "done"
    assert client.get("/api/research", params={"id": identity}).json()["state"] == "empty"
    for action, args in (
        ("research_bookmark", {"job_id": identity, "saved": True}),
        ("research_bookmark", {"job_id": identity, "saved": "true"}),
        ("research_feedback", {"job_id": identity, "rating": "useful"}),
        ("research_feedback", {"job_id": identity, "rating": "unsupported"}),
    ):
        assert control(client, action, **args).status_code == 400
    assert client.get("/api/state").json()["bookmarks"] == []
    assert server.http.app.store.research_public(identity)["feedback"] == ""
    assert not server.http.app.store.rows("SELECT * FROM research_steps")


@pytest.mark.parametrize("action", ["research_resume", "research_continue"])
def test_explicit_research_controls_dispatch_once_per_operation(feature_browser, monkeypatch, action):
    server, client = feature_browser
    identity = "a" * 32
    calls = []

    def run(name, **kwargs):
        calls.append((name, kwargs))
        return {"message": "隔离控制完成", "research_job": {"id": identity, "state": "done"}}

    monkeypatch.setattr(server.http.app.service, "run", run)
    operation = submit(client, action, {"job_id": identity})
    row = finished(server, operation)
    assert row["state"] == "done" and json.loads(row["result"])["research_job_id"] == identity
    submit(client, action, {"job_id": identity}, operation)
    assert calls == [(action, {"job_id": identity})]


def test_research_cancel_remains_available_while_background_worker_is_busy(feature_browser, monkeypatch):
    server, client = feature_browser
    service = server.http.app.service
    original = service.run
    entered, release = threading.Event(), threading.Event()

    def run(action, **kwargs):
        if action != "research":
            return original(action, **kwargs)
        identity = kwargs["job_id"]
        now = time.time()
        service.store.execute(
            "INSERT INTO research_jobs(id,question,mode,created,expires,state,settings,scope) VALUES(?,?,?,?,?,?,?,?)",
            (identity, kwargs["question"], "standard", now, now + 3600, "running", "{}", "{}"))
        entered.set()
        assert release.wait(5), "test must release its research worker"
        return {"message": "已停止后续步骤", "research_job": original("research_status", job_id=identity)}

    monkeypatch.setattr(service, "run", run)
    identity = submit(client, "research", {"question": "正在运行的隔离研究", "mode": "standard"})
    try:
        assert entered.wait(2)
        assert client.get("/api/state").json()["busy"]
        for _ in range(2):
            response = control(client, "research_cancel", job_id=identity)
            assert response.status_code == 200 and response.json()["state"] == "cancelled"
        assert server.http.app.busy
        assert not service.store.rows("SELECT * FROM research_steps")
    finally:
        release.set()
    assert finished(server, identity)["state"] == "done"
    assert client.get("/api/research", params={"id": identity}).json()["state"] == "cancelled"
