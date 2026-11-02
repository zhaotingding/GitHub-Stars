import tkinter as tk

import pytest

from github_stars.config import Paths
from github_stars.gui import App


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
        variable, _, _ = app.forms[("digest", "max_projects")]
        variable.set("2")
        app.save_settings()
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
