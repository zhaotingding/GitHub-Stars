from __future__ import annotations

import copy
import json
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import __version__
from .reports import digest_text, export_digest, project_text
from .service import Service

BG, CARD, INK, MUTED, GREEN = "#f3f6f2", "#ffffff", "#172f29", "#64786f", "#21634e"


class App(tk.Tk):
    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self.service = Service(paths)
        self.config_data = paths.load()
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
        self.counter = tk.Label(self, bg=BG, fg=MUTED, anchor="w", font=("Microsoft YaHei UI", 11))
        self.counter.pack(fill="x", padx=30, pady=(0, 14))
        self.tabs = ttk.Notebook(self)
        self.radar = ttk.Frame(self.tabs, padding=16)
        self.weekly = ttk.Frame(self.tabs, padding=16)
        self.settings = ttk.Frame(self.tabs, padding=16)
        self.logs = ttk.Frame(self.tabs, padding=16)
        for widget, name in ((self.radar, "项目雷达"), (self.weekly, "每周精选"), (self.settings, "偏好与连接"), (self.logs, "运行与用量")):
            self.tabs.add(widget, text=name)
        self.status = tk.StringVar(value="准备就绪。首次使用请采集项目，再查看入选理由。")
        ttk.Label(self, textvariable=self.status, wraplength=1200).pack(side="bottom", fill="x", padx=28, pady=12)
        self.tabs.pack(fill="both", expand=True, padx=24)
        self.build_radar()
        self.build_weekly()
        self.build_settings()
        self.log_text = self.reader(self.logs)
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
        self.search = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.search, width=26).pack(side="right")
        ttk.Label(toolbar, text="搜索项目  ").pack(side="right")
        self.search.trace_add("write", lambda *_: self.refresh_projects())
        pane = ttk.Panedwindow(self.radar, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=2)
        pane.add(right, weight=3)
        self.projects = ttk.Treeview(left, columns=("name", "score", "kind"), show="headings", selectmode="browse")
        for key, label, width in (("name", "项目", 240), ("score", "匹配分", 70), ("kind", "方向 / 状态", 110)):
            self.projects.heading(key, text=label)
            self.projects.column(key, width=width, minwidth=60)
        scroll = ttk.Scrollbar(left, command=self.projects.yview)
        self.projects.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.projects.pack(fill="both", expand=True, padx=(0, 12))
        self.projects.bind("<<TreeviewSelect>>", lambda _: self.select_project())
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(0, 10))
        for label, callback in (("打开 GitHub", self.open_repo), ("收藏", lambda: self.feedback("saved")),
                                ("忽略", lambda: self.feedback("dismissed")), ("恢复", lambda: self.feedback("new")),
                                ("生成教程", self.tutorial), ("恢复结果", self.recover)):
            ttk.Button(actions, text=label, command=callback).pack(side="left", padx=2)
        self.detail = self.reader(right)

    def selected(self):
        selected = self.projects.selection()
        return self.service.store.one("SELECT * FROM repos WHERE id=?", (int(selected[0]),)) if selected else None

    def select_project(self):
        row = self.selected()
        if row:
            job = self.service.store.one("SELECT * FROM ai_jobs WHERE repo_id=? ORDER BY id DESC LIMIT 1", (row["id"],))
            tutorial = json.loads(job["result"]) if job and job["status"] == "completed" else None
            text = project_text(row, tutorial)
            if job and job["status"] != "completed":
                text += f"\n\n教程任务状态：{job['status']}\n{job['error'] or ''}"
            self.show_text(self.detail, text)

    def open_repo(self):
        row = self.selected()
        if row:
            webbrowser.open(f"https://github.com/{row['name']}")

    def feedback(self, value):
        row = self.selected()
        if row:
            self.service.store.execute("UPDATE repos SET feedback=? WHERE id=?", (value, row["id"]))
            self.refresh_projects()

    def tutorial(self):
        row = self.selected()
        if not row:
            return
        job = self.service.store.one("SELECT * FROM ai_jobs WHERE repo_id=? ORDER BY id DESC LIMIT 1", (row["id"],))
        retry = bool(job and job["status"] != "completed")
        if retry and not messagebox.askyesno("重新提交会再次消耗 API 用量", "上次任务未成功完成，可能已产生费用。确定要新建一次请求吗？"):
            return
        self.work("正在根据 README 生成教程…", lambda: self.service.run("tutorial", repo_id=row["id"], retry=retry))

    def recover(self):
        row = self.selected()
        if row:
            self.work("正在恢复原请求结果（不新建生成请求）…", lambda: self.service.run("recover", repo_id=row["id"]))

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
        if retry and not messagebox.askyesno("确认重发", "上次邮件可能已发送，请先检查收件箱。仍要重新发送吗？"):
            return
        self.work("正在发送周报邮件…", lambda: self.service.run("email", week=week, retry=retry))

    def export(self):
        if self.weeks.get():
            page = export_digest(self.paths, self.service.store, self.weeks.get())
            webbrowser.open(page.as_uri())
            self.status.set(f"已导出 HTML 与 Markdown：{page.parent}")

    def build_settings(self):
        ttk.Label(self.settings, text="密钥存入 Windows 凭据库；留空保留原值。设置保存后生效。", foreground=MUTED).pack(anchor="w", pady=(0, 10))
        self.forms = {}
        self.secrets = {}
        book = ttk.Notebook(self.settings)
        book.pack(fill="both", expand=True)
        specs = {
            "研究画像": [("profile", "description", "研究背景与阅读偏好"), ("profile", "research_terms", "研究关键词（每行一个）"), ("profile", "hot_terms", "热点关键词（每行一个）")],
            "发现与筛选": [("discovery", "min_stars", "常规最低 Star"), ("discovery", "new_min_stars", "新项目最低 Star"), ("digest", "max_projects", "每周最多项目数"), ("digest", "hot_slots", "其中热点最多名额"), ("digest", "min_score", "最低推荐分"), ("digest", "cooldown_days", "重复推荐冷却天数")],
            "检索来源": [("discovery", "research_queries", "研究查询（每行一条 GitHub 语法）"), ("discovery", "hot_queries", "热点查询（每行一条）")],
            "定时检查": [("schedule", "enabled", "启用自动检查"), ("schedule", "timezone", "时区"), ("schedule", "daily_hour", "每日采集小时（0–23）"), ("schedule", "weekly_day", "周报星期（0=周一，4=周五）"), ("schedule", "weekly_hour", "周报小时（0–23）")],
            "OpenAI 教程": [("ai", "enabled", "启用 AI（含每周自动教程，会产生费用）"), ("ai", "model", "OpenAI 模型 ID"), ("ai", "max_calls_per_week", "每周最多请求次数"), ("ai", "max_output_tokens", "每次最大输出 Token")],
            "邮件推送": [("email", "enabled", "启用每周邮件"), ("email", "host", "SMTP 服务器"), ("email", "port", "SMTP 端口"), ("email", "security", "加密方式 ssl / starttls"), ("email", "username", "SMTP 登录用户名"), ("email", "sender", "发件邮箱"), ("email", "recipient", "收件邮箱")],
        }
        for title, fields in specs.items():
            page = ttk.Frame(book, padding=20)
            book.add(page, text=title)
            page.columnconfigure(1, weight=1)
            index = 0
            for section, key, label in fields:
                value = self.config_data[section][key]
                ttk.Label(page, text=label).grid(row=index, column=0, sticky="nw", padx=(0, 20), pady=8)
                if isinstance(value, bool):
                    variable = tk.BooleanVar(value=value)
                    widget = ttk.Checkbutton(page, variable=variable)
                elif isinstance(value, list) or key == "description":
                    variable = None
                    widget = tk.Text(page, height=5 if section == "profile" else 7, width=55, wrap="word", font=("Microsoft YaHei UI", 10))
                    widget.insert("1.0", "\n".join(value) if isinstance(value, list) else value)
                else:
                    variable = tk.StringVar(value=str(value))
                    widget = ttk.Entry(page, textvariable=variable, width=55)
                widget.grid(row=index, column=1, sticky="ew", pady=8)
                self.forms[(section, key)] = (variable, widget, type(value))
                index += 1
            for kind, label in ({"OpenAI 教程": [("openai", "OpenAI API Key")], "邮件推送": [("smtp", "SMTP 密码 / 授权码")], "检索来源": [("github", "GitHub Token（可选，提高限额）")]}.get(title, [])):
                ttk.Label(page, text=label).grid(row=index, column=0, sticky="w", pady=8)
                value = tk.StringVar()
                ttk.Entry(page, textvariable=value, show="•").grid(row=index, column=1, sticky="ew", pady=8)
                self.secrets[kind] = value
                index += 1
            if title == "定时检查":
                ttk.Label(page, text="窗口打开时自动检查。关闭窗口后需安装 Windows 计划任务。\n安装命令见 README：tools/install_schedule.ps1；关机期间无法采集，登录后补当前周期。", wraplength=800).grid(row=index, column=0, columnspan=2, sticky="w", pady=24)
            if title == "OpenAI 教程":
                ttk.Label(page, text="仅连接官方 OpenAI Responses API。首次默认关闭。\n模型由你选择；次数上限不是金额预算，实际价格取决于模型。\n请求断线或结果未知时不自动重复提交。", wraplength=800).grid(row=index, column=0, columnspan=2, sticky="w", pady=24)
        ttk.Button(self.settings, text="保存设置", style="Accent.TButton", command=self.save_settings).pack(anchor="e", pady=(12, 0))

    def save_settings(self):
        if self.busy:
            messagebox.showinfo("任务运行中", "请等待当前任务结束后保存设置。")
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
            self.status.set("设置已保存，密钥不写入 YAML。下一次任务读取新设置。")
            self.refresh()
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc) if isinstance(exc, ValueError) else type(exc).__name__)

    def refresh_projects(self):
        previous = self.projects.selection()
        self.projects.delete(*self.projects.get_children())
        term = self.search.get().lower()
        rows = self.service.store.rows("""SELECT * FROM repos ORDER BY
            CASE WHEN feedback='saved' THEN 0 WHEN feedback='dismissed' THEN 2 ELSE 1 END,
            CASE WHEN bucket='research' THEN 0 ELSE 1 END, score DESC,name""")
        for row in rows:
            if term and term not in (row["name"] + row["metadata"]).lower():
                continue
            label = {"saved": "已收藏", "dismissed": "已忽略", "new": "研究" if row["bucket"] == "research" else "热点"}[row["feedback"]]
            self.projects.insert("", "end", iid=str(row["id"]), values=(row["name"], row["score"], label))
        children = self.projects.get_children()
        if children:
            target = previous[0] if previous and previous[0] in children else children[0]
            self.projects.selection_set(target)
            self.select_project()
        else:
            self.show_text(self.detail, "# 让值得看的项目浮出水面\n\n点击「立即采集」开始。\n\n默认关注深度伪造、计算机视觉、自监督、强化学习，以及少量 AI Agent 与 MCP 热点。\n\n每周最多 3 项，不够就少推。无需 OpenAI 密钥也能采集和阅读。")

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
        jobs = self.service.store.rows("SELECT id,repo_id,created,status,model,input_tokens,output_tokens,error FROM ai_jobs ORDER BY id DESC LIMIT 30")
        events = self.service.store.rows("SELECT * FROM events ORDER BY id DESC LIMIT 60")
        text = "# AI 请求与实际用量\n\n未返回用量显示未知，不按免费计算。每周上限统计所有已开始的请求。\n\n"
        for job in jobs:
            text += f"任务 {job['id']} · {job['status']} · {job['model']} · 输入 {job['input_tokens'] if job['input_tokens'] is not None else '未知'} / 输出 {job['output_tokens'] if job['output_tokens'] is not None else '未知'}\n{job['error'] or ''}\n"
        text += "\n# 运行记录\n\n" + "\n".join(f"{e['created'][:19]}  [{e['level']}] {e['message']}" for e in events)
        self.show_text(self.log_text, text)

    def work(self, label, callback, quiet=False):
        if self.busy:
            if not quiet:
                self.status.set("已有任务正在运行，请等待完成。")
            return
        self.busy = True
        self.status.set(label)

        def run():
            try:
                result = callback()
                self.results.put((True, result if isinstance(result, str) else "教程已保存，可在项目详情阅读", quiet))
            except Exception as exc:
                text = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                self.results.put((False, text, quiet))

        threading.Thread(target=run, daemon=False).start()  # 网络操作不占用 Tk 主线程。

    def poll(self):
        try:
            ok, result, quiet = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.status.set(result)
            self.refresh()
            if not ok and not quiet:
                messagebox.showerror("任务未完成", result)
        self.after(200, self.poll)

    def scheduled(self):
        if not self.busy:
            self.work("检查定时任务…", lambda: self.service.run("tick"), quiet=True)
        self.after(60000, self.scheduled)

    def close(self):
        if self.busy:
            messagebox.showinfo("任务运行中", "当前任务尚未结束，请稍候关闭，避免中断生成或邮件发送。")
        else:
            self.destroy()
