from __future__ import annotations

import copy
import json
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

from . import __version__
from .reports import digest_text, export_digest, project_text
from .research_ui import ResearchPanel
from .service import Service
from .store import STUDY_STATES
from .theme import apply_theme, themed_dialog

BG, CARD, INK, MUTED, GREEN = "#f3f6f2", "#ffffff", "#172f29", "#64786f", "#21634e"


class App(tk.Tk):
    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self.service = Service(paths)
        self.config_data = paths.ensure_theme()
        self.auto_attempted = set()
        self.state_editor = None
        self.busy = False
        self.results = queue.Queue()
        self.title(f"GitHub Stars++  ·  {__version__}")
        self.geometry("1320x880")
        self.minsize(1100, 740)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background=BG, foreground=INK)
        style.configure("TButton", padding=(14, 9), borderwidth=0)
        style.configure("Accent.TButton", background=GREEN, foreground="white")
        style.map("Accent.TButton", background=[("active", "#2e8065")])
        style.configure("Treeview", rowheight=38, background=CARD, fieldbackground=CARD, borderwidth=0)
        style.configure("Treeview.Heading", padding=8, background="#e4ece5")
        style.map("Treeview", background=[("selected", "#d3e9dc")], foreground=[("selected", INK)])
        style.configure("TNotebook.Tab", padding=(18, 11))
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=28, pady=(22, 12))
        tk.Label(top, text="✦  GitHub Stars++", bg=BG, fg=INK, font=("Segoe UI", 24, "bold")).pack(side="left")
        tk.Label(top, text="每天观察 · 每周只读几项", bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 11)).pack(side="left", padx=24)
        self.theme_choice = tk.StringVar(value="深色" if self.config_data["appearance"]["theme"] == "dark" else "浅色")
        choice = ttk.Combobox(top, textvariable=self.theme_choice, state="readonly", values=["深色", "浅色"], width=7)
        choice.pack(side="right")
        choice.bind("<<ComboboxSelected>>", lambda _: self.change_theme())
        self.counter = tk.Label(self, bg=BG, fg=MUTED, anchor="w", font=("Microsoft YaHei UI", 11))
        self.counter.pack(fill="x", padx=30, pady=(0, 14))
        self.tabs = ttk.Notebook(self)
        self.radar = ttk.Frame(self.tabs, padding=16)
        self.weekly = ttk.Frame(self.tabs, padding=16)
        self.research = ResearchPanel(self)
        self.settings = ttk.Frame(self.tabs, padding=16)
        self.logs = ttk.Frame(self.tabs, padding=16)
        for widget, name in ((self.radar, "项目雷达"), (self.weekly, "每周精选"), (self.research, "项目研究"),
                             (self.settings, "偏好与连接"), (self.logs, "运行与用量")):
            self.tabs.add(widget, text=name)
        self.status = tk.StringVar(value="准备就绪。首次使用请采集项目，再查看入选理由。")
        ttk.Label(self, textvariable=self.status, wraplength=1200).pack(side="bottom", fill="x", padx=28, pady=12)
        self.tabs.pack(fill="both", expand=True, padx=24)
        self.build_radar()
        self.build_weekly()
        self.build_settings()
        self.log_text = self.reader(self.logs)
        apply_theme(self, self.config_data["appearance"]["theme"])
        self.refresh()
        self.after(200, self.poll)
        self.after(3000, self.scheduled)

    def reader(self, parent):
        frame = tk.Frame(parent, bg=CARD)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, height=1, width=1, wrap="word", bg=CARD, fg=INK, relief="flat", padx=22, pady=18,
                       font=("Microsoft YaHei UI", 11), spacing1=3, spacing3=7)
        bar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.tag_configure("title", font=("Microsoft YaHei UI", 17, "bold"), foreground=GREEN, spacing1=16)
        text.tag_configure("subtitle", font=("Microsoft YaHei UI", 12, "bold"), spacing1=12)
        return text

    def show_text(self, widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for line in value.splitlines():
            tag = "title" if line.startswith(("# ", "## ")) else "subtitle" if line.startswith("### ") else ""
            widget.insert("end", line.lstrip("# ") + "\n" if tag else line + "\n", tag)
        widget.configure(state="disabled")

    def build_radar(self):
        toolbar = ttk.Frame(self.radar)
        toolbar.pack(fill="x", pady=(0, 14))
        ttk.Button(toolbar, text="立即采集", style="Accent.TButton", command=lambda: self.work("正在检索 GitHub…", lambda: self.service.run("scan"))).pack(side="left")
        ttk.Button(toolbar, text="刷新", command=self.refresh).pack(side="left", padx=8)
        ttk.Button(toolbar, text="粘贴仓库链接", command=self.import_dialog).pack(side="left")
        self.search = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.search, width=26).pack(side="right")
        ttk.Label(toolbar, text="搜索项目  ").pack(side="right")
        self.search.trace_add("write", lambda *_: self.refresh_projects())
        pane = ttk.Panedwindow(self.radar, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=2)
        pane.add(right, weight=3)
        self.projects = ttk.Treeview(left, columns=("name", "score", "state", "open"), show="headings", selectmode="browse")
        for key, label, width in (("name", "项目", 230), ("score", "匹配", 54), ("state", "研究状态 ▾", 96), ("open", "GitHub", 72)):
            self.projects.heading(key, text=label)
            self.projects.column(key, width=width, minwidth=50, stretch=key == "name")
        scroll = ttk.Scrollbar(left, command=self.projects.yview)
        self.projects.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.projects.pack(fill="both", expand=True, padx=(0, 12))
        self.projects.bind("<<TreeviewSelect>>", lambda _: self.select_project())
        self.projects.bind("<ButtonRelease-1>", self.project_cell)
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(0, 10))
        for label, callback in (("初始分析", lambda: self.generate("analysis")),
                                ("生成 HTML 教程", lambda: self.generate("tutorial")),
                                ("打开已有教程", self.open_tutorial), ("任务与恢复", self.recovery_dialog)):
            ttk.Button(actions, text=label, command=callback).pack(side="left", padx=2)
        self.detail = self.reader(right)

    def selected(self):
        selected = self.projects.selection()
        return self.service.store.one("SELECT * FROM repos WHERE id=?", (int(selected[0]),)) if selected else None

    def select_project(self):
        row = self.selected()
        if row:
            job = self.service.store.one("SELECT * FROM ai_jobs WHERE repo_id=? AND kind='analysis' ORDER BY id DESC LIMIT 1", (row["id"],))
            tutorial = json.loads(job["result"]) if job and job["status"] == "completed" else None
            text = project_text(row, tutorial)
            if job and job["status"] != "completed":
                text += f"\n\n初始分析任务状态：{job['status']}\n{job['error'] or ''}"
            self.show_text(self.detail, text)
            config = self.paths.load()
            if not job and config["ai"]["enabled"] and config["ai"]["auto_analyze"] and row["id"] not in self.auto_attempted:
                self.after(700, lambda repo_id=row["id"]: self.auto_analyze(repo_id))

    def open_repo(self):
        row = self.selected()
        if row:
            webbrowser.open(f"https://github.com/{row['name']}")

    def generate(self, kind):
        row = self.selected()
        if not row:
            return
        job = self.service.store.one("SELECT * FROM ai_jobs WHERE repo_id=? AND kind=? ORDER BY id DESC LIMIT 1", (row["id"], kind))
        retry = bool(job and job["status"] != "completed")
        if retry and not self.dialog("重新提交会再次消耗 API 用量", "上次任务未成功完成，可能已产生费用。请优先恢复原响应。仍要新建请求吗？", confirm=True):
            return
        self.work("正在生成初始分析…" if kind == "analysis" else "正在生成可视化教程（可能需要数分钟）…",
                  lambda: self.service.run(kind, repo_id=row["id"], retry=retry))

    def open_tutorial(self):
        row = self.selected()
        if row:
            self.work("正在打开已有教程…", lambda: self.service.run("open_tutorial", repo_id=row["id"]))

    def auto_analyze(self, repo_id):
        row = self.selected()
        if self.busy or not row or row["id"] != repo_id or repo_id in self.auto_attempted:
            return
        self.auto_attempted.add(repo_id)
        self.work("正在准备项目初始分析…", lambda: self.service.run("analysis", repo_id=repo_id), quiet=True)

    def project_cell(self, event):
        item = self.projects.identify_row(event.y)
        column = self.projects.identify_column(event.x)
        if not item:
            return
        self.projects.selection_set(item)
        if column == "#4":
            self.open_repo()
        elif column == "#3":
            if self.state_editor is not None:
                self.state_editor.destroy()
            box = self.projects.bbox(item, "state")
            if not box:
                return
            editor = ttk.Combobox(self.projects, state="readonly", values=list(STUDY_STATES.values()))
            self.state_editor = editor
            editor.set(self.projects.set(item, "state"))
            editor.place(x=box[0], y=box[1], width=box[2], height=box[3])

            def save(_=None):
                state = next(key for key, label in STUDY_STATES.items() if label == editor.get())
                try:
                    self.status.set(self.service.run("study_state", repo_id=int(item), state=state))
                except RuntimeError as exc:
                    self.status.set(str(exc))
                editor.destroy()
                self.state_editor = None
                self.refresh_projects()

            editor.bind("<<ComboboxSelected>>", save)
            editor.bind("<Escape>", lambda _: editor.destroy())
            editor.focus_set()

    def change_theme(self):
        config = self.paths.load()
        config["appearance"]["theme"] = "dark" if self.theme_choice.get() == "深色" else "light"
        self.paths.save(config)
        self.config_data["appearance"] = config["appearance"]
        apply_theme(self, config["appearance"]["theme"])

    def dialog(self, title, message, confirm=False):
        return themed_dialog(self, title, message, confirm)

    def import_dialog(self):
        window = tk.Toplevel(self)
        window.title("粘贴 GitHub 仓库链接")
        window.geometry("720x380")
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="粘贴网址或包含多个 Markdown 链接的文字，粘贴后自动导入。\n每次最多 10 个仓库；不会因 Star 少或研究匹配分低而拒绝。", wraplength=650).pack(anchor="w", pady=(0, 14))
        text = tk.Text(frame, height=7, wrap="word", font=("Microsoft YaHei UI", 11))
        text.pack(fill="both", expand=True)

        def submit():
            value = text.get("1.0", "end").strip()
            if value and not self.busy:
                from .github import parse_repositories
                try:
                    parse_repositories(value)
                except ValueError as exc:
                    self.dialog("链接无效", str(exc))
                    return
                window.destroy()
                self.work("正在采集指定仓库…", lambda: self.service.run("import", text=value))

        text.bind("<<Paste>>", lambda _: window.after(120, submit), add=True)
        ttk.Button(frame, text="导入 / 查询", style="Accent.TButton", command=submit).pack(anchor="e", pady=(14, 0))
        apply_theme(self, self.theme_name)
        text.focus_set()

    def recovery_dialog(self):
        row = self.selected()
        if not row:
            return
        window = tk.Toplevel(self)
        window.title("任务与恢复 · " + row["name"])
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill="both", expand=True)
        for kind, title in (("analysis", "初始分析"), ("tutorial", "HTML 教程"), ("legacy", "0.1.0 旧版教程")):
            job = self.service.store.one("SELECT * FROM ai_jobs WHERE repo_id=? AND kind=? ORDER BY id DESC LIMIT 1", (row["id"], kind))
            line = ttk.Frame(frame)
            line.pack(fill="x", pady=8)
            ttk.Label(line, text=f"{title}：{job['status'] if job else '尚未生成'}", width=36).pack(side="left")
            if job:
                def restore(kind=kind):
                    window.destroy()
                    self.work("正在恢复原结果，不新建请求…", lambda: self.service.run("recover", repo_id=row["id"], kind=kind))
                ttk.Button(line, text="恢复 / 重新导出", command=restore).pack(side="right")
                if kind == "legacy" and job["status"] == "completed":
                    ttk.Button(line, text="阅读旧稿", command=lambda job=job: self.show_legacy(job)).pack(side="right")
        apply_theme(self, self.theme_name)

    def show_legacy(self, job):
        window = tk.Toplevel(self)
        window.title("0.1.0 旧版教程")
        window.geometry("850x650")
        reader = self.reader(window)
        result = json.loads(job["result"])
        self.show_text(reader, "\n\n".join(str(result.get(key, "")) for key in ("summary", "relevance", "tutorial", "limitations")))
        apply_theme(self, self.theme_name)

    def build_weekly(self):
        bar = ttk.Frame(self.weekly)
        bar.pack(fill="x", pady=(0, 14))
        self.weeks = ttk.Combobox(bar, state="readonly", width=14)
        self.weeks.pack(side="left")
        self.weeks.bind("<<ComboboxSelected>>", lambda _: self.refresh_week())
        ttk.Button(bar, text="生成本周精选", style="Accent.TButton", command=lambda: self.work("正在筛选本周项目…", lambda: self.service.run("digest"))).pack(side="left", padx=10)
        ttk.Button(bar, text="发送邮件", command=self.send_mail).pack(side="left")
        ttk.Button(bar, text="导出 / 打开周报", command=self.export).pack(side="left", padx=10)
        self.mail_status = ttk.Label(self.weekly)
        self.mail_status.pack(fill="x", pady=(0, 10))
        self.report = self.reader(self.weekly)

    def send_mail(self):
        week = self.weeks.get()
        if not week:
            return
        row = self.service.store.one("SELECT * FROM digests WHERE week=?", (week,))
        retry = row["mail_state"] in {"unknown", "sending"}
        if retry and not self.dialog("确认重发", "上次邮件可能已发送，请先检查收件箱。仍要重新发送吗？", confirm=True):
            return
        self.work("正在发送周报邮件…", lambda: self.service.run("email", week=week, retry=retry))

    def export(self):
        if self.weeks.get():
            page = export_digest(self.paths, self.service.store, self.weeks.get())
            webbrowser.open(page.as_uri())
            self.status.set(f"已导出 HTML 与 Markdown：{page.parent}")

    def build_settings(self):
        ttk.Label(self.settings, text="初始分析帮助筛选；深入教程只在主动生成时调用。密钥留空保留原值。", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.forms = {}
        self.secrets = {}
        ttk.Style(self).configure("Settings.TNotebook.Tab", padding=(9, 9))
        book = ttk.Notebook(self.settings, style="Settings.TNotebook")
        book.pack(fill="both", expand=True)
        specs = {
            "研究画像": [("profile", "description", "研究背景与阅读偏好"), ("profile", "research_terms", "研究关键词（每行一个）"), ("profile", "hot_terms", "热点关键词（每行一个）")],
            "发现与筛选": [("discovery", "min_stars", "常规最低 Star"), ("discovery", "new_min_stars", "新项目最低 Star"), ("digest", "max_projects", "每周最多项目数"), ("digest", "hot_slots", "其中热点最多名额"), ("digest", "min_score", "最低推荐分"), ("digest", "cooldown_days", "重复推荐冷却天数")],
            "检索来源": [("discovery", "research_queries", "研究查询（每行一条 GitHub 语法）"), ("discovery", "hot_queries", "热点查询（每行一条）")],
            "定时检查": [("schedule", "enabled", "启用自动检查"), ("schedule", "timezone", "时区"), ("schedule", "daily_hour", "每日采集小时（0–23）"), ("schedule", "weekly_day", "周报星期（0=周一，4=周五）"), ("schedule", "weekly_hour", "周报小时（0–23）")],
            "初始分析": [("ai", "enabled", "启用模型 API"), ("ai", "credential_source", "凭据来源"), ("ai", "auto_analyze", "打开项目时自动做首次短分析"), ("ai", "model", "初始分析模型 ID"), ("ai", "service_tier", "服务等级"), ("ai", "max_calls_per_week", "每周最多初始分析请求"), ("ai", "max_output_tokens", "初始分析输出 Token 上限"), ("ai", "readme_chars", "初始分析 README 字符上限"), ("ai", "timeout_seconds", "等待超时（秒）")],
            "深入教程": [("tutorial", "model", "教程模型 ID（可独立选低成本模型）"), ("tutorial", "service_tier", "教程服务等级"), ("tutorial", "max_calls_per_week", "每周最多教程请求"), ("tutorial", "max_output_tokens", "教程输出 Token 上限"), ("tutorial", "readme_chars", "教程 README 字符上限"), ("tutorial", "timeout_seconds", "教程等待超时（秒）")],
            "项目研究": [("research", "model", "研究模型 ID（留空沿用初始分析模型）"),
                     ("research", "image_model", "截图解读模型 ID（需明确配置）"),
                     ("research", "image_credential_source", "图片凭据来源"),
                     ("research", "service_tier", "研究服务等级"),
                     ("research", "max_calls", "每题最多模型调用（含图片）"),
                     ("research", "max_tools", "每题最多工具动作"),
                     ("research", "max_images", "每题最多 PNG 截图"),
                     ("research", "max_calls_per_week", "每周最多研究请求（含图片）"),
                     ("research", "max_output_tokens", "每次输出 Token 上限"),
                     ("research", "max_input_chars", "每次输入字符上限"),
                     ("research", "timeout_seconds", "本题绝对时限（秒）"),
                     ("research", "history_days", "README / Star 观测回看天数"),
                     ("research", "max_cost_cny", "每题估算费用上限（人民币）"),
                     ("research", "input_cny_per_million", "研究输入费率（人民币 / 百万 Token）"),
                     ("research", "output_cny_per_million", "研究输出费率（人民币 / 百万 Token）"),
                     ("research", "image_input_cny_per_million", "图片模型输入费率（人民币 / 百万 Token）"),
                     ("research", "image_output_cny_per_million", "图片模型输出费率（人民币 / 百万 Token）"),
                     ("research", "interests", "关注主题（每行一个，可留空）"),
                     ("research", "exclude_terms", "降低优先级的词（每行一个，可留空）")],
            "提示词": [("ai", "prompt", "初始分析提示词"), ("tutorial", "prompt", "深入教程提示词")],
            "邮件推送": [("email", "enabled", "启用每周邮件"), ("email", "host", "SMTP 服务器"), ("email", "port", "SMTP 端口"), ("email", "security", "加密方式 ssl / starttls"), ("email", "username", "SMTP 登录用户名"), ("email", "sender", "发件邮箱"), ("email", "recipient", "收件邮箱")],
        }
        for title, fields in specs.items():
            container = ttk.Frame(book)
            book.add(container, text=title)
            canvas = tk.Canvas(container, highlightthickness=0)
            scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            canvas.pack(fill="both", expand=True)
            page = ttk.Frame(canvas, padding=18)
            window_id = canvas.create_window((0, 0), window=page, anchor="nw")
            page.bind("<Configure>", lambda _, canvas=canvas: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>", lambda event, canvas=canvas, window_id=window_id: canvas.itemconfigure(window_id, width=event.width))
            page.columnconfigure(1, weight=1)
            index = 0
            for section, key, label in fields:
                value = self.config_data[section][key]
                ttk.Label(page, text=label).grid(row=index, column=0, sticky="nw", padx=(0, 20), pady=8)
                if isinstance(value, bool):
                    variable = tk.BooleanVar(value=value)
                    widget = ttk.Checkbutton(page, variable=variable)
                elif isinstance(value, list) or key in {"description", "prompt"}:
                    variable = None
                    widget = tk.Text(page, height=10 if key == "prompt" else 5 if section == "profile" else 7, width=55, wrap="word", font=("Microsoft YaHei UI", 10))
                    widget.insert("1.0", "\n".join(value) if isinstance(value, list) else value)
                else:
                    variable = tk.StringVar(value=str(value))
                    choices = {"credential_source": ["local", "msgx", "autogpu"],
                               "image_credential_source": ["local", "msgx", "autogpu"],
                               "service_tier": ["default", "flex"]}
                    widget = ttk.Combobox(page, textvariable=variable, state="readonly", values=choices[key]) if key in choices else ttk.Entry(page, textvariable=variable, width=55)
                widget.grid(row=index, column=1, sticky="ew", pady=8)
                self.forms[(section, key)] = (variable, widget, type(value))
                index += 1
            for kind, label in ({"初始分析": [("openai", "本项目 OpenAI API Key（可选）")], "邮件推送": [("smtp", "SMTP 密码 / 授权码")], "检索来源": [("github", "GitHub Token（可选，提高限额）")]}.get(title, [])):
                ttk.Label(page, text=label).grid(row=index, column=0, sticky="w", pady=8)
                value = tk.StringVar()
                ttk.Entry(page, textvariable=value, show="•").grid(row=index, column=1, sticky="ew", pady=8)
                self.secrets[kind] = value
                index += 1
            if title == "定时检查":
                ttk.Label(page, text="窗口打开时自动检查。关闭窗口后需安装 Windows 计划任务。\n安装命令见 README：tools/install_schedule.ps1；关机期间无法采集，登录后补当前周期。", wraplength=800).grid(row=index, column=0, columnspan=2, sticky="w", pady=24)
            if title == "初始分析":
                ttk.Label(page, text="凭据来源：local = 本项目／环境变量；msgx = 消息萃取已存 OpenAI；autogpu = AutoGPU 已存 OpenAI。\n仅在请求时读取所选凭据，不复制密钥。Flex 较慢但成本更低，不自动改用更贵等级。\n自动短分析在打开项目或准备周报时触发，受独立周次数上限约束。", wraplength=800).grid(row=index, column=0, columnspan=2, sticky="w", pady=20)
            if title == "深入教程":
                ttk.Label(page, text="教程只由你主动生成，每次生成创建新请求；查看已有教程不调用 API。\n默认较低成本 GPT-6 Luna + Flex，较大输出预算用于概念、实践、配置和 PR 路线。\n次数与 Token 限制不是金额预算；生成步骤尚未经真实运行。", wraplength=800).grid(row=index, column=0, columnspan=2, sticky="w", pady=20)
            if title == "项目研究":
                ttk.Label(page, text="研究只由你主动提交；使用本地缓存快照，不自动采集 GitHub。\n文本沿用初始分析凭据；图片凭据可单独选择。每题都需明确允许读图。\n费率 0 代表未知，不会新增收费请求；金额仅为本地估算，上限同时受次数、工具与时限约束。\n恢复只取回原响应；后续新请求须明确继续，继续不重置原时限或预算。\n历史问题保留 7 天；收藏只保留答案与来源位置。关注词与反馈仅影响后续本地排序。", wraplength=800).grid(row=index, column=0, columnspan=2, sticky="w", pady=20)
        ttk.Button(self.settings, text="保存设置", style="Accent.TButton", command=self.save_settings).pack(anchor="e", pady=(12, 0))

    def save_settings(self):
        if self.busy:
            self.dialog("任务运行中", "请等待当前任务结束后保存设置。")
            return
        try:
            config = copy.deepcopy(self.config_data)
            for (section, key), (variable, widget, kind) in self.forms.items():
                value = variable.get() if variable is not None else widget.get("1.0", "end").strip()
                config[section][key] = [x.strip() for x in value.splitlines() if x.strip()] if kind is list else kind(value)
            from .config import validate
            validate(config)
            for key, variable in self.secrets.items():
                if variable.get().strip():
                    self.paths.set_secret(key, variable.get().strip())
                    variable.set("")
            self.paths.save(config)
            self.config_data = config
            apply_theme(self, config["appearance"]["theme"])
            self.status.set("设置已保存，密钥不写入 YAML。下一次任务读取新设置。")
            self.refresh()
        except Exception as exc:
            self.dialog("保存失败", str(exc) if isinstance(exc, ValueError) else type(exc).__name__)

    def refresh_projects(self):
        if self.state_editor is not None:
            self.state_editor.destroy()
            self.state_editor = None
        previous = self.projects.selection()
        self.projects.delete(*self.projects.get_children())
        term = self.search.get().lower()
        rows = self.service.store.rows("""SELECT * FROM repos ORDER BY
            CASE WHEN study_state='focus' THEN 0 WHEN study_state IN ('saved','studying') THEN 1 WHEN feedback='dismissed' THEN 3 ELSE 2 END,
            CASE WHEN bucket='research' THEN 0 ELSE 1 END, score DESC,name""")
        for row in rows:
            if term and term not in (row["name"] + row["metadata"]).lower():
                continue
            label = STUDY_STATES[row["study_state"]]
            if row["feedback"] == "dismissed":
                label += " · 旧忽略"
            self.projects.insert("", "end", iid=str(row["id"]), values=(row["name"], row["score"], label, "↗ 打开"))
        children = self.projects.get_children()
        if children:
            target = previous[0] if previous and previous[0] in children else children[0]
            self.projects.selection_set(target)
            self.select_project()
        else:
            self.show_text(self.detail, "# 让值得看的项目浮出水面\n\n点击「立即采集」，或「粘贴仓库链接」导入你发现的项目。\n\n先通过初始分析判断用途和价值，值得深入时主动生成可视化教程。\n\n点击每行研究状态可选择待研究、收藏、已研究、重点或正在研究。")

    def refresh_week(self):
        week = self.weeks.get()
        if week:
            row = self.service.store.one("SELECT * FROM digests WHERE week=?", (week,))
            self.show_text(self.report, digest_text(self.service.store, week))
            names = {"pending": "待发送", "sent": "SMTP 已接受", "failed": "未发出", "unknown": "结果未知", "sending": "正在发送"}
            self.mail_status.configure(text=f"邮件：{names.get(row['mail_state'], row['mail_state'])}  {row['mail_detail']}")
        else:
            self.show_text(self.report, "# 本周还没有精选\n\n先采集，再生成本周精选。默认每周五 19:00 自动准备周报。\n\n每次生成都会保留项目来源、入选理由和阅读路线；配置 API 后补充中文教程。")

    def refresh(self):
        self.refresh_projects()
        weeks = [r["week"] for r in self.service.store.rows("SELECT week FROM digests ORDER BY week DESC")]
        selected = self.weeks.get()
        self.weeks["values"] = weeks
        if weeks:
            self.weeks.set(selected if selected in weeks else weeks[0])
        self.refresh_week()
        count = self.service.store.one("SELECT count(*) n FROM repos")["n"]
        scan = self.service.store.one("SELECT * FROM scans ORDER BY id DESC LIMIT 1")
        config = self.paths.load()
        self.counter.configure(text=f"已发现 {count} 个项目   /   已有 {len(weeks)} 份周报   /   每周最多 {config['digest']['max_projects']} 项   /   "
                               f"最近采集：{scan['started'][:16] + ' · ' + scan['status'] if scan else '尚未采集'}")
        jobs = self.service.store.rows("SELECT id,repo_id,created,status,model,kind,actual_model,actual_tier,input_tokens,output_tokens,error FROM ai_jobs ORDER BY id DESC LIMIT 30")
        events = self.service.store.rows("SELECT * FROM events ORDER BY id DESC LIMIT 60")
        text = "# AI 请求与实际用量\n\n未返回用量显示未知，不按免费计算。每周上限统计所有已开始的请求。\n\n"
        for job in jobs:
            text += f"任务 {job['id']} · {job['kind']} · {job['status']} · {job['actual_model'] or job['model']} / {job['actual_tier'] or '档位未返回'} · 输入 {job['input_tokens'] if job['input_tokens'] is not None else '未知'} / 输出 {job['output_tokens'] if job['output_tokens'] is not None else '未知'}\n{job['error'] or ''}\n"
        steps = self.service.store.rows("SELECT id,job_id,kind,state,actual_model,actual_tier,input_tokens,output_tokens,"
                                        "cost,reserve FROM research_steps ORDER BY id DESC LIMIT 60")
        text += "\n# 项目研究请求与估算费用\n\n用量未知不按免费计算。预留费用是本地估算；文本与图片共用本题上限。\n\n"
        for step in steps:
            incoming = step["input_tokens"] if step["input_tokens"] is not None else "未知"
            outgoing = step["output_tokens"] if step["output_tokens"] is not None else "未知"
            cost = f"¥{step['cost']:.6f}" if step["cost"] is not None else "未知"
            text += (f"研究 {step['job_id'][:8]} / 步骤 {step['id']} · {step['kind']} · {step['state']} · "
                     f"{step['actual_model'] or '模型未返回'} / {step['actual_tier'] or '档位未返回'} · "
                     f"输入 {incoming} / 输出 {outgoing} · 按用量估算 {cost} / 预留 ¥{step['reserve']:.6f}\n")
        text += "\n# 运行记录\n\n" + "\n".join(f"{e['created'][:19]}  [{e['level']}] {e['message']}" for e in events)
        self.show_text(self.log_text, text)
        self.research.refresh()

    def work(self, label, callback, quiet=False):
        if self.busy:
            if not quiet:
                self.status.set("已有任务正在运行，请等待完成。")
            return False
        self.busy = True
        self.status.set(label)

        def run():
            try:
                result = callback()
                self.results.put((True, result, quiet))
            except Exception as exc:
                text = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                self.results.put((False, text, quiet))

        threading.Thread(target=run, daemon=False).start()  # 网络操作不占用 Tk 主线程。
        self.research.update_buttons()
        return True

    def poll(self):
        try:
            ok, result, quiet = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.status.set(result.get("message", "已完成") if isinstance(result, dict) else result)
            self.refresh()
            if ok and isinstance(result, dict):
                self.research.accept_result(result)
                repo_id = result.get("repo_id")
                if repo_id is not None and self.projects.exists(str(repo_id)):
                    self.projects.selection_set(str(repo_id))
                    self.projects.see(str(repo_id))
                    self.select_project()
                if result.get("path"):
                    webbrowser.open(Path(result["path"]).as_uri())
            if not ok and not quiet:
                self.dialog("任务未完成", result)
        self.research.poll()
        self.after(200, self.poll)

    def scheduled(self):
        if not self.busy:
            self.work("检查定时任务…", lambda: self.service.run("tick"), quiet=True)
        self.after(60000, self.scheduled)

    def close(self):
        if self.busy:
            self.dialog("任务运行中", "当前任务尚未结束，请稍候关闭，避免中断生成或邮件发送。")
        else:
            self.destroy()
