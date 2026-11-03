import tkinter as tk
from tkinter import ttk

import pytest

from github_stars.theme import apply_theme, themed_dialog


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"无图形桌面：{exc}")
    window.geometry("500x350")
    try:
        yield window
    finally:
        for task in window.tk.call("after", "info"):
            window.after_cancel(task)
        window.destroy()


def test_default_theme_and_switch_recolors_existing_child_windows(root):
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True)
    label = tk.Label(frame, text="项目介绍")
    label.pack()
    child = tk.Toplevel(root)
    note = tk.Label(child, text="详细说明")
    note.pack()
    canvas = tk.Canvas(child)
    canvas.pack()
    canvas_text = canvas.create_text(40, 20, text="步骤 1")
    dark = apply_theme(root)
    assert root.theme_name == child.theme_name == "dark"
    assert frame.cget("bg") == label.cget("bg") == child.cget("bg") == dark["bg"]
    assert note.cget("fg") == dark["ink"]
    assert canvas.itemcget(canvas_text, "fill") == dark["ink"]
    light = apply_theme(root, "light")
    assert root.theme_name == child.theme_name == "light"
    assert note.cget("bg") == canvas.cget("bg") == light["bg"]
    assert note.cget("fg") == light["ink"] != dark["ink"]
    assert canvas.itemcget(canvas_text, "fill") == light["ink"]


def test_disabled_readers_readonly_entries_and_ttk_selection_remain_readable(root):
    reader = tk.Text(root, state="normal")
    reader.insert("1.0", "项目分析")
    reader.tag_configure("title", foreground="#ffffff")
    reader.configure(state="disabled")
    entry = tk.Entry(root, state="readonly")
    listed = tk.Listbox(root)
    combo = ttk.Combobox(root, state="readonly", values=["待研究", "正在研究"])
    combo.pack()
    dark = apply_theme(root)
    assert reader.cget("state") == "disabled" and reader.get("1.0", "end").strip() == "项目分析"
    assert reader.cget("bg") == entry.cget("readonlybackground") == listed.cget("bg") == dark["card"]
    assert reader.cget("fg") == dark["ink"]
    assert reader.tag_cget("title", "foreground") == dark["accent"]
    style = ttk.Style(root)
    assert style.lookup("TCombobox", "foreground", ("readonly",)) == dark["ink"]
    assert style.lookup("Treeview", "foreground", ("selected",)) == dark["ink"]
    assert style.lookup("Treeview", "background", ("selected",)) == dark["selected"]
    popup = combo.tk.call("ttk::combobox::PopdownWindow", str(combo))
    popup_list = f"{popup}.f.l"
    assert combo.tk.call(popup_list, "cget", "-background") == dark["card"]
    light = apply_theme(root, "light")
    assert combo.tk.call(popup_list, "cget", "-background") == light["card"]
    assert reader.cget("fg") == light["ink"]


@pytest.mark.parametrize("expected", [False, True])
def test_themed_modal_dialog_result_and_grab_release(root, expected):
    palette = apply_theme(root, "light")
    observed = []
    errors = []

    def buttons(widget):
        result = [widget] if isinstance(widget, ttk.Button) else []
        for child in widget.winfo_children():
            result.extend(buttons(child))
        return result

    def inspect_and_finish():
        dialogs = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
        try:
            assert len(dialogs) == 1
            dialog = dialogs[0]
            observed.append((dialog.theme_name, dialog.cget("bg"), root.grab_current() == dialog))
            selected = next(button for button in buttons(dialog) if button.cget("text") == ("确认" if expected else "取消"))
            selected.invoke()  # 不与其他 GUI 测试争夺系统焦点，仍走真实按钮回调和模态清理。
        except Exception as exc:
            errors.append(exc)
            for dialog in dialogs:
                dialog.destroy()

    def timeout():
        errors.append(AssertionError("主题对话框没有在限时内关闭"))
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()

    root.after(100, inspect_and_finish)
    watchdog = root.after(3000, timeout)
    result = themed_dialog(root, "确认生成教程", "将使用已配置的教程模型。", confirm=True)
    root.after_cancel(watchdog)
    assert not errors, errors
    assert result is expected
    assert observed == [("light", palette["bg"], True)]
    assert root.grab_current() is None


def test_startup_error_style_dialog_is_visible_with_hidden_parent(root):
    apply_theme(root)
    root.withdraw()
    observed = []

    def finish():
        dialogs = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
        if dialogs:
            dialog = dialogs[0]
            observed.append(dialog.winfo_viewable())
            dialog.destroy()

    root.after(300, finish)
    assert themed_dialog(root, "启动失败", "模拟配置错误") is False
    assert observed == [1]
