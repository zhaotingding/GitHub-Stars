import json
import threading
import time
import tkinter as tk
from tkinter import ttk

import pytest
from test_workflow import NOW, repository

from github_stars.config import Paths
from github_stars.gui import App


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(Paths, "secret", lambda *_: "")
    monkeypatch.setattr(App, "scheduled", lambda _: None)
    paths = Paths(tmp_path)
    config = paths.load()
    config["schedule"]["enabled"] = False
    config["ai"]["auto_analyze"] = False
    paths.save(config)
    try:
        window = App(paths)
    except tk.TclError as exc:
        pytest.skip(f"无图形桌面：{exc}")
    window.dialog = lambda *_args, **_kwargs: False
    window.tabs.select(window.research)
    window.update()
    try:
        yield window
    finally:
        assert not window.busy, "测试不得留下后台任务"
        for task in window.tk.call("after", "info"):
            window.after_cancel(task)
        window.destroy()


def seed_job(app, identity="a" * 32, state="done", expires=None):
    now = time.time()
    source = dict(label="R1", name="owner1/project1", kind="repository", url="https://github.com/owner1/project1",
                  sha="README-sha", captured="2026-11-06T10:00:00+08:00", text="视觉检测工具，来源中的安装说明。")
    result = dict(claims=[dict(text="该项目提供视觉检测工具。", sources=["R1"])], limitations=["未实际运行。"])
    organization = dict(topics=[dict(title="视觉检测", sources=["R1"])], truncated=True,
                        timeline=[dict(day="2026-11-06", name="owner1/project1", stars=500,
                                       change_since_previous=None)], note="Star 为本地观测。")
    app.service.store.execute(
        "INSERT INTO research_jobs(id,question,mode,created,expires,state,settings,scope,sources,result,organization,trace) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (identity, "哪些视觉检测工具适合研究？", "agent", now, expires or now+86400, state,
         json.dumps(dict(deadline=now+180)), "{}", json.dumps([source], ensure_ascii=False),
         json.dumps(result, ensure_ascii=False), json.dumps(organization, ensure_ascii=False),
         json.dumps([dict(action="本地检索", detail="命中1条资料")], ensure_ascii=False)))
    return identity


def pump(app, condition, timeout=3):
    deadline = time.monotonic()+timeout
    while not condition() and time.monotonic() < deadline:
        app.update()
        time.sleep(.01)
    assert condition(), "Tk 后台结果未在限时内返回"
    app.update()


def test_readonly_answer_citation_sources_organization_and_feedback(app):
    identity = seed_job(app)
    panel = app.research
    app.refresh()
    app.update()
    assert app.tabs.tab(panel, "text") == "项目研究"
    assert "该项目提供视觉检测工具" in panel.answer.get("1.0", "end")
    assert "[R1]" in panel.answer.get("1.0", "end")
    assert "未实际运行" in panel.answer.get("1.0", "end")
    for reader in (panel.answer, panel.source_text, panel.organization, panel.trace):
        assert reader.cget("state") == "disabled"
    ranges = panel.answer.tag_ranges("cite:R1")
    assert ranges and panel.answer.tk.call(str(panel.answer), "tag", "bind", "cite:R1", "<Button-1>")
    box = panel.answer.bbox(ranges[0])
    assert box
    panel.answer.event_generate("<Motion>", x=box[0]+2, y=box[1]+2)
    panel.answer.event_generate("<Button-1>", x=box[0]+2, y=box[1]+2)
    app.update()
    assert panel.readers.select() == str(panel.source_page)
    assert "README-sha" in panel.source_text.get("1.0", "end")
    assert "2026-11-06T10:00:00" in panel.source_text.get("1.0", "end")
    assert "采样 / 截断" in panel.organization.get("1.0", "end")
    assert "首次观测，无增量基线" in panel.organization.get("1.0", "end")
    assert "本地检索" in panel.trace.get("1.0", "end")
    panel.feedback_buttons[0].invoke()
    assert app.service.store.research_public(identity)["feedback"] == "useful"
    panel.feedback_buttons[1].invoke()
    assert app.service.store.research_public(identity)["feedback"] == "irrelevant"
    panel.feedback_buttons[2].invoke()
    assert app.service.store.research_public(identity)["feedback"] == ""
    panel.bookmark_button.invoke()
    assert panel.bookmarks.exists(identity)
    assert app.service.store.research_public(identity)["saved"] is True
    panel.bookmark_button.invoke()
    assert not panel.bookmarks.exists(identity)
    app.theme_choice.set("浅色")
    app.change_theme()
    assert panel.answer.cget("bg") == panel.source_text.cget("bg") == app.theme_palette["card"]
    assert panel.answer.cget("state") == "disabled"


def test_per_question_attachment_scope_worker_and_cancel_are_responsive(app, monkeypatch):
    panel = app.research
    app.service.store.upsert(repository(1), "research", NOW)
    app.refresh()
    panel.scope.set("雷达当前项目")
    panel.mode.set("受限 Agent")
    panel.question.insert("1.0", "请解释视觉检测截图")
    image = str(app.paths.root / "explicit-screenshot.png")
    monkeypatch.setattr("github_stars.research_ui.filedialog.askopenfilenames", lambda **_: (image,))
    panel.attach()
    assert panel.image_paths == [image]
    assert panel.allow_images.get() is False
    original = app.service.run
    captured, threads = [], []
    submitted, release = threading.Event(), threading.Event()

    def run(action, **kwargs):
        if action != "research":
            return original(action, **kwargs)
        captured.append(kwargs)
        threads.append(threading.get_ident())
        seed_job(app, kwargs["job_id"], "running")
        submitted.set()
        assert release.wait(3)
        return dict(message="已停止", research_job=original("research_status", job_id=kwargs["job_id"]))

    monkeypatch.setattr(app.service, "run", run)
    panel.ask_button.invoke()
    assert not captured and not app.busy  # 缺少本题读图许可时不读文件、不启动网络工作。
    panel.allow_images.set(True)
    try:
        panel.ask_button.invoke()
        pump(app, submitted.is_set)
        assert app.busy
        assert len(threads) == 1 and threads[0] != threading.get_ident()
        request = captured[0]
        assert request["repo_ids"] == [1] and request["mode"] == "agent"
        assert request["image_paths"] == [image] and request["allow_images"] is True
        assert panel.allow_images.get() is False and panel.image_paths == []
        panel.refresh_active()
        assert str(panel.cancel_button.cget("state")) == "normal"
        panel.cancel_button.invoke()  # App.busy 仍为真；停止走短本地接口，不等待 worker.lock。
        assert app.busy and panel.job["state"] == "cancelled"
        assert app.service.store.research_public(request["job_id"])["state"] == "cancelled"
        assert str(panel.ask_button.cget("state")) == "disabled"
    finally:
        release.set()
        pump(app, lambda: not app.busy)
    assert panel.job["state"] == "cancelled"


def test_history_never_submits_and_resume_and_continue_are_explicit(app, monkeypatch):
    identity = seed_job(app, state="paused")
    app.service.store.execute(
        "INSERT INTO research_steps(job_id,number,kind,state,prepared,reserve,created,response_id) VALUES(?,?,?,?,?,?,?,?)",
        (identity, 1, "decision", "received", "{}", .02, time.time(), "original-response"))
    original = app.service.run
    calls, threads = [], []

    def run(action, **kwargs):
        calls.append(action)
        if action in {"research_resume", "research_continue"}:
            assert kwargs["job_id"] == identity
            threads.append(threading.get_ident())
            if action == "research_resume":
                app.service.store.execute("UPDATE research_steps SET applied=1 WHERE job_id=?", (identity,))
                app.service.store.research_update(identity, state="continuable")
            else:
                app.service.store.research_update(identity, state="done")
            return dict(message="原任务已更新", research_job=original("research_status", **kwargs))
        return original(action, **kwargs)

    monkeypatch.setattr(app.service, "run", run)
    panel = app.research
    app.refresh()
    panel.history.selection_set(identity)
    panel.history.event_generate("<<TreeviewSelect>>")
    app.update()
    assert set(calls) == {"research_status"}
    assert str(panel.resume_button.cget("state")) == "normal"
    assert str(panel.continue_button.cget("state")) == "disabled"
    panel.resume_button.invoke()
    pump(app, lambda: not app.busy)
    assert panel.job["id"] == identity and panel.job["state"] == "continuable"
    assert calls.count("research_resume") == 1 and "research_continue" not in calls
    assert str(panel.continue_button.cget("state")) == "normal"
    panel.continue_button.invoke()
    pump(app, lambda: not app.busy)
    assert panel.job["id"] == identity and panel.job["state"] == "done"
    assert calls.count("research_continue") == 1 and "research" not in calls
    assert all(thread != threading.get_ident() for thread in threads)


def test_research_settings_and_safe_usage_ledger(app):
    expected = {"model", "image_model", "image_credential_source", "service_tier", "max_calls", "max_tools",
                "max_images", "max_calls_per_week", "max_output_tokens", "max_input_chars", "timeout_seconds",
                "history_days", "max_cost_cny", "input_cny_per_million", "output_cny_per_million",
                "image_input_cny_per_million", "image_output_cny_per_million", "interests", "exclude_terms"}
    assert expected == {key for section, key in app.forms if section == "research"}
    image_source, source_widget, _ = app.forms[("research", "image_credential_source")]
    assert isinstance(source_widget, ttk.Combobox) and str(source_widget.cget("state")) == "readonly"
    image_source.set("autogpu")
    app.forms[("research", "input_cny_per_million")][0].set("1.25")
    app.forms[("research", "max_cost_cny")][0].set("0.75")
    app.forms[("research", "interests")][1].insert("1.0", "视觉检测\n显存")
    app.save_settings()
    settings = app.paths.load()["research"]
    assert settings["image_credential_source"] == "autogpu"
    assert settings["input_cny_per_million"] == 1.25 and settings["max_cost_cny"] == .75
    assert settings["interests"] == ["视觉检测", "显存"] and settings["exclude_terms"] == []
    identity = seed_job(app)
    app.service.store.execute(
        "INSERT INTO research_steps(job_id,number,kind,state,prepared,reserve,created,response,actual_model,actual_tier) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (identity, 1, "image", "unknown", '{"private":"DO-NOT-LOG-INPUT"}', .08, time.time(),
         "DO-NOT-LOG-RESPONSE", "mock-image-model", "flex"))
    app.refresh()
    usage = app.log_text.get("1.0", "end")
    assert "项目研究请求与估算费用" in usage and "mock-image-model / flex" in usage
    assert "输入 未知 / 输出 未知" in usage and "预留 ¥0.080000" in usage
    assert "DO-NOT-LOG" not in usage and "哪些视觉检测工具" not in usage
    app.geometry("1100x740")
    app.research.readers.select(app.research.source_page)
    app.update()
    assert app.tabs.winfo_y()+app.tabs.winfo_height() < app.winfo_height()
    assert app.research.ask_button.winfo_rootx()+app.research.ask_button.winfo_width() < app.winfo_rootx()+app.winfo_width()
    assert app.research.source_text.winfo_width() > 200 and app.research.source_text.winfo_height() > 80


def test_standard_empty_scope_uses_real_service_without_api(app):
    panel = app.research
    panel.question.insert("1.0", "有哪些显存友好的视觉工具？")
    assert panel.mode.get() == "标准问答" and panel.scope.get() == "全部本地缓存"
    assert not panel.allow_images.get()
    panel.ask_button.invoke()
    pump(app, lambda: not app.busy)
    assert panel.job["state"] == "empty" and panel.job["calls"] == 0
    stored = app.service.store.research_job(panel.active_id)
    assert stored["settings"]["request"]["repo_ids"] is None
    assert stored["settings"]["request"]["allow_images"] is False
    assert stored["mode"] == "standard" and stored["scope"]["images"] == []
    assert panel.history.exists(panel.active_id)
    assert "没有命中本地资料" in panel.answer.get("1.0", "end")
    assert str(panel.bookmark_button.cget("state")) == "disabled"


def test_expired_bookmark_keeps_answer_and_pointers_then_can_be_removed(app):
    identity = seed_job(app)
    app.service.run("research_bookmark", job_id=identity, saved=True)
    app.service.store.execute("UPDATE research_jobs SET expires=? WHERE id=?", (time.time()-1, identity))
    app.service.store.research_prune()
    panel = app.research
    app.refresh()
    assert not panel.history.exists(identity) and panel.bookmarks.exists(identity)
    panel.bookmarks.selection_set(identity)
    panel.bookmarks.event_generate("<<TreeviewSelect>>")
    app.update()
    assert panel.job["state"] == "archived"
    assert "该项目提供视觉检测工具" in panel.answer.get("1.0", "end")
    source = panel.source_text.get("1.0", "end")
    assert "README-sha" in source and "原文已随任务到期清理" in source
    assert "来源中的安装说明" not in source
    for button in (panel.resume_button, panel.continue_button, panel.cancel_button, *panel.feedback_buttons):
        assert str(button.cget("state")) == "disabled"
    panel.bookmark_button.invoke()
    assert not panel.bookmarks.exists(identity)
    assert panel.job is None and panel.active_id is None
    assert "收藏已移除" in panel.answer.get("1.0", "end")


def test_two_images_require_agent_on_attachment_and_after_mode_change(app, monkeypatch):
    panel = app.research
    app.config_data["research"]["max_images"] = 2
    images = (str(app.paths.root / "one.png"), str(app.paths.root / "two.png"))
    monkeypatch.setattr("github_stars.research_ui.filedialog.askopenfilenames", lambda **_: images)
    messages = []
    app.dialog = lambda title, message, **_: messages.append((title, message))
    panel.attach()
    assert panel.image_paths == [] and "受限 Agent" in messages[-1][1]
    panel.mode.set("受限 Agent")
    panel.attach()
    assert panel.image_paths == list(images)
    panel.mode.set("标准问答")
    panel.question.insert("1.0", "比较这两张截图")
    panel.allow_images.set(True)
    panel.ask_button.invoke()
    assert not app.busy and "受限 Agent" in messages[-1][1]
    assert not app.service.store.rows("SELECT id FROM research_jobs")
