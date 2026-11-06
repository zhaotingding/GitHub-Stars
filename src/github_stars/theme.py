from __future__ import annotations

import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PALETTES = {
    "dark": {"bg": "#121a23", "card": "#1c2834", "ink": "#e8eef5", "muted": "#acbac9",
             "accent": "#56c6a0", "selected": "#2b5149", "border": "#405264"},
    "light": {"bg": "#edf2f5", "card": "#f8fafc", "ink": "#1c2c3b", "muted": "#586b7d",
              "accent": "#23775d", "selected": "#cce8dd", "border": "#c3cfda"},
}


def configure_ui_fonts(root):
    available = set(tkfont.families(root))
    preferred = ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei")
    family = next((name for name in preferred if name in available),
                  tkfont.nametofont("TkDefaultFont", root=root).actual("family"))
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                 "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
        tkfont.nametofont(name, root=root).configure(family=family)
    root.option_add("*Font", (family, 10))
    return family


def _titlebar(window, dark):
    if os.name != "nt":
        return
    try:
        import ctypes
        window.update_idletasks()  # 创建原生 HWND 后再设置标题栏，不改变 Windows 全局主题。
        handle = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(bool(dark))
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, attribute, ctypes.byref(value), ctypes.sizeof(value))
            if result == 0:
                break
    except (AttributeError, OSError, tk.TclError):
        pass  # 系统版本不支持时保留普通标题栏，应用内容仍使用所选主题。


def apply_theme(root, name="dark") -> dict:
    if name not in PALETTES:
        raise ValueError("主题需要为 dark 或 light")
    palette = PALETTES[name].copy()  # 返回副本，界面不能改写共享色板。
    root.theme_name = name
    root.theme_palette = palette
    style = ttk.Style(root)
    if style.theme_use() != "clam":
        style.theme_use("clam")  # 原生 Windows ttk 主题可能忽略背景色。
    style.configure(".", background=palette["bg"], foreground=palette["ink"],
                    bordercolor=palette["border"], lightcolor=palette["border"], darkcolor=palette["border"])
    style.map(".", foreground=[("disabled", palette["muted"])])
    style.configure("TFrame", background=palette["bg"])
    style.configure("Card.TFrame", background=palette["card"])
    style.configure("TLabel", background=palette["bg"], foreground=palette["ink"])
    style.configure("Muted.TLabel", foreground=palette["muted"])
    style.configure("TButton", background=palette["card"], foreground=palette["ink"])
    style.map("TButton", background=[("active", palette["selected"]), ("pressed", palette["selected"])],
              foreground=[("disabled", palette["muted"]), ("active", palette["ink"])])
    style.configure("Accent.TButton", background=palette["accent"],
                    foreground=palette["bg"] if name == "dark" else palette["card"])
    style.map("Accent.TButton", background=[("active", palette["accent"]), ("pressed", palette["accent"])],
              foreground=[("disabled", palette["muted"]), ("active", palette["bg"] if name == "dark" else palette["card"])])
    for class_name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(class_name, fieldbackground=palette["card"], background=palette["card"],
                        foreground=palette["ink"], insertcolor=palette["ink"], arrowcolor=palette["ink"],
                        selectbackground=palette["selected"], selectforeground=palette["ink"])
        style.map(class_name, fieldbackground=[("readonly", palette["card"]), ("disabled", palette["card"])],
                  foreground=[("disabled", palette["muted"]), ("readonly", palette["ink"])],
                  selectforeground=[("readonly", palette["ink"])],
                  selectbackground=[("readonly", palette["selected"])])
    style.configure("Treeview", background=palette["card"], fieldbackground=palette["card"], foreground=palette["ink"])
    style.configure("Treeview.Heading", background=palette["bg"], foreground=palette["ink"])
    style.map("Treeview", background=[("selected", palette["selected"])], foreground=[("selected", palette["ink"])])
    style.map("Treeview.Heading", background=[("active", palette["selected"])])
    style.configure("TNotebook", background=palette["bg"])
    style.configure("TNotebook.Tab", background=palette["card"], foreground=palette["muted"])
    style.map("TNotebook.Tab", background=[("selected", palette["selected"]), ("active", palette["selected"])],
              foreground=[("selected", palette["ink"]), ("active", palette["ink"])])
    for class_name in ("TCheckbutton", "TRadiobutton"):
        style.configure(class_name, background=palette["bg"], foreground=palette["ink"])
        style.map(class_name, background=[("active", palette["bg"])],
                  foreground=[("disabled", palette["muted"]), ("active", palette["ink"])])
    for class_name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(class_name, background=palette["border"], troughcolor=palette["bg"], arrowcolor=palette["ink"])
    style.configure("TLabelframe", background=palette["bg"])
    style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["ink"])
    for option, value in (("background", palette["card"]), ("foreground", palette["ink"]),
                          ("selectBackground", palette["selected"]), ("selectForeground", palette["ink"])):
        root.option_add(f"*TCombobox*Listbox.{option}", value)  # 尚未创建的下拉列表也使用当前色板。

    def update(widget):
        role = getattr(widget, "theme_role", "")
        background = palette["card"] if role == "card" else palette["bg"]
        foreground = palette["muted"] if role == "muted" else palette["accent"] if role == "accent" else palette["ink"]
        if isinstance(widget, (tk.Tk, tk.Toplevel)):
            widget.configure(background=palette["bg"])
            widget.theme_name = name
            widget.theme_palette = palette
            _titlebar(widget, name == "dark")
        elif isinstance(widget, ttk.Widget):
            if isinstance(widget, ttk.Frame) and role == "card":
                widget.configure(style="Card.TFrame")
            elif isinstance(widget, ttk.Label) and role == "muted":
                widget.configure(style="Muted.TLabel")
            # ttk.Entry/Combobox 也继承 tk.Entry，必须先排除，颜色由 ttk.Style 设置。
        elif isinstance(widget, (tk.Text, tk.Entry, tk.Listbox, tk.Spinbox)):
            options = dict(background=palette["card"], foreground=palette["ink"],
                           selectbackground=palette["selected"], selectforeground=palette["ink"],
                           highlightbackground=palette["border"], highlightcolor=palette["accent"])
            if isinstance(widget, (tk.Text, tk.Entry, tk.Spinbox)):
                options["insertbackground"] = palette["ink"]
            if isinstance(widget, (tk.Entry, tk.Spinbox)):
                options.update(disabledbackground=palette["card"], disabledforeground=palette["muted"],
                               readonlybackground=palette["card"])
            widget.configure(**options)
            if isinstance(widget, tk.Text):
                # 现有富文本标签常带固定颜色，切换时一并更新，保持禁用状态与内容不变。
                for tag in widget.tag_names():
                    if tag != "sel" and widget.tag_cget(tag, "foreground"):
                        widget.tag_configure(tag, foreground=palette["accent"] if tag == "title" else palette["ink"])
        elif isinstance(widget, (tk.Frame, tk.LabelFrame, tk.Canvas)):
            widget.configure(background=background, highlightbackground=palette["border"])
            if isinstance(widget, tk.LabelFrame):
                widget.configure(foreground=foreground)
            if isinstance(widget, tk.Canvas):
                for item in widget.find_all():
                    if widget.type(item) == "text":
                        widget.itemconfigure(item, fill=foreground)
        elif isinstance(widget, (tk.Label, tk.Message)):
            widget.configure(background=background, foreground=foreground)
        elif isinstance(widget, (tk.Button, tk.Checkbutton, tk.Radiobutton)):
            widget.configure(background=background, foreground=foreground,
                             activebackground=palette["selected"], activeforeground=palette["ink"],
                             disabledforeground=palette["muted"])
            if isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
                widget.configure(selectcolor=palette["card"])
        if isinstance(widget, ttk.Combobox):
            popup = f"{widget}.popdown.f.l"
            if widget.tk.call("winfo", "exists", popup):
                widget.tk.call(popup, "configure", "-background", palette["card"], "-foreground", palette["ink"],
                               "-selectbackground", palette["selected"], "-selectforeground", palette["ink"])
        for child in widget.winfo_children():
            update(child)

    update(root)
    return palette


def themed_dialog(parent, title, message, confirm=False) -> bool:
    window = tk.Toplevel(parent)
    window.withdraw()  # 先完成布局和配色，避免深色主题下闪出亮色对话框。
    window.title(title)
    window.resizable(False, False)
    if parent.winfo_toplevel().state() != "withdrawn":
        window.transient(parent.winfo_toplevel())  # 启动失败时父根窗口隐藏，子对话框仍须可显示。
    content = ttk.Frame(window, padding=24)
    content.pack(fill="both", expand=True)
    label = ttk.Label(content, text=message, justify="left", wraplength=520)
    label.pack(fill="x", pady=(0, 22))
    buttons = ttk.Frame(content)
    buttons.pack(fill="x")
    answer = False

    def finish(value):
        nonlocal answer
        answer = value
        window.destroy()

    if confirm:
        ttk.Button(buttons, text="取消", command=lambda: finish(False)).pack(side="right", padx=(10, 0))
    accepted = ttk.Button(buttons, text="确认" if confirm else "确定", style="Accent.TButton", command=lambda: finish(True))
    accepted.pack(side="right")
    window.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    window.bind("<Escape>", lambda _: finish(False))
    window.bind("<Return>", lambda _: finish(True))
    previous_grab = parent.grab_current()  # 关闭嵌套对话框后恢复原有模态窗口。
    apply_theme(window, getattr(parent._root(), "theme_name", "dark"))
    window.update_idletasks()
    top = parent.winfo_toplevel()
    x = max(0, top.winfo_rootx() + (top.winfo_width() - window.winfo_reqwidth()) // 2)
    y = max(0, top.winfo_rooty() + (top.winfo_height() - window.winfo_reqheight()) // 2)
    window.geometry(f"+{x}+{y}")
    window.deiconify()
    window.wait_visibility()
    window.grab_set()
    accepted.focus_set()
    window.wait_window()
    if previous_grab is not None and previous_grab.winfo_exists():
        previous_grab.grab_set()
    return answer


def start_error_dialog(message, theme="dark"):
    root = tk.Tk()
    root.withdraw()
    apply_theme(root, theme)
    try:
        themed_dialog(root, "GitHub Stars++ · 启动失败", message)
    finally:
        root.destroy()
