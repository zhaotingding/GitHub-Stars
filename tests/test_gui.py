import tkinter as tk
from tkinter import font as tkfont
from types import SimpleNamespace

import pytest
from test_workflow import NOW, repository

from github_stars.config import Paths
from github_stars.gui import App


def test_chinese_ui_renders_glyphs_instead_of_unicode_escapes(tmp_path, monkeypatch):
    monkeypatch.setattr(Paths, "secret", lambda *_: "")
    paths = Paths(tmp_path)
    config = paths.load()
    config["schedule"]["enabled"] = False
    paths.save(config)
    try:
        app = App(paths)
    except tk.TclError as exc:
        pytest.skip(f"无图形桌面：{exc}")
    try:
        app.update_idletasks()
        selected = tkfont.Font(root=app, family=app.ui_font_family, size=11)
        assert selected.actual("family") == app.ui_font_family
        assert selected.measure("每天观察") < selected.measure(r"\u6bcf\u5929\u89c2\u5bdf")
        assert tkfont.nametofont("TkDefaultFont", root=app).actual("family") == app.ui_font_family
    finally:
        for task in app.tk.call("after", "info"):
            app.after_cancel(task)
        app.destroy()


def test_empty_gui_settings_save_and_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(Paths, "secret", lambda *_: "")
    paths = Paths(tmp_path)
    config = paths.load()
    config["schedule"]["enabled"] = False
    paths.save(config)
    try:
        app = App(paths)
    except tk.TclError as exc:
        pytest.skip(f"无图形桌面：{exc}")
    try:
        app.update_idletasks()
        assert "GitHub Stars++" in app.title()
        assert not app.projects.get_children()
        assert "立即采集" in app.detail.get("1.0", "end")
        app.settings_button.invoke()
        app.update()
        assert app.tabs.tab(app.settings, "text") == "设置"
        assert app.tabs.select() == str(app.settings)
        assert app.settings_book.select() == str(app.settings_pages["API连接"])
        api_page = str(app.settings_pages["API连接"])
        for field in (("ai", "model"), ("tutorial", "model"), ("research", "image_model")):
            assert str(app.forms[field][1]).startswith(api_page + ".")
        app.settings_nav.selection_set("发现与筛选")
        app.settings_nav.event_generate("<<TreeviewSelect>>")
        app.update()
        assert app.settings_book.select() == str(app.settings_pages["发现与筛选"])
        variable, _, _ = app.forms[("digest", "max_projects")]
        variable.set("2")
        app.settings_save_button.invoke()
        assert paths.load()["digest"]["max_projects"] == 2
        # 状态栏在窗口内部；最低尺寸下设置页仍能保存。
        app.geometry("1100x740")
        app.tabs.select(app.settings)
        app.update()  # Windows Configure 消息先落地，随后检查子控件布局。
        app.update_idletasks()
        assert app.tabs.winfo_y() + app.tabs.winfo_height() < app.winfo_height()
    finally:
        for task in app.tk.call("after", "info"):
            app.after_cancel(task)
        app.destroy()


def test_inline_state_and_theme_cover_open_child_window(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    config = paths.load()
    config["schedule"]["enabled"] = False
    paths.save(config)
    app = App(paths)
    try:
        app.service.store.upsert(repository(1), "research", NOW)
        app.refresh()
        app.update()
        box = app.projects.bbox("1", "state")
        app.project_cell(SimpleNamespace(x=box[0] + 8, y=box[1] + 8))
        editor = app.state_editor
        assert editor is not None
        editor.set("正在研究")
        editor.event_generate("<<ComboboxSelected>>")
        app.update()
        assert app.service.store.one("SELECT study_state FROM repos WHERE id=1")["study_state"] == "studying"
        assert app.projects.set("1", "state") == "正在研究"
        app.import_dialog()
        child = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
        app.theme_choice.set("浅色")
        app.change_theme()
        assert child.cget("background") == app.theme_palette["bg"]
        assert paths.load()["appearance"]["theme"] == "light"
        child.destroy()
    finally:
        for task in app.tk.call("after", "info"):
            app.after_cancel(task)
        app.destroy()
