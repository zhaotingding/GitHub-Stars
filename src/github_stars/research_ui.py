"""项目研究界面；网络工作统一交给 App.work，查看与停止只读取本地任务。"""
from __future__ import annotations

import time
import tkinter as tk
import uuid
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk

from .research_search import safe_url

STATES = {
    "running": "研究中", "done": "已完成", "empty": "没有匹配资料", "failed": "未完成",
    "limited": "达到限制", "paused": "可取回原结果", "blocked": "提交结果未知",
    "continuable": "等待明确继续", "cancelled": "已停止", "archived": "已收藏 · 原任务已到期",
}
KINDS = {"repository": "项目资料", "readme_version": "README 历史", "image_interpretation": "附件解读"}


class ResearchPanel(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs, padding=16)
        self.app = app
        self.active_id = None
        self.job = None
        self.image_paths = []
        self.last_poll = 0.
        self._updating_history = False
        self._build()

    def _build(self):
        ttk.Label(self, text="围绕本地项目元数据、README 与 Star 观测提问。Agent 可在本题范围内补查；不会实时搜索 GitHub。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.question = tk.Text(self, height=3, wrap="word", font=("Microsoft YaHei UI", 11), relief="flat")
        self.question.pack(fill="x")
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(8, 4))
        self.mode = tk.StringVar(value="标准问答")
        ttk.Combobox(controls, textvariable=self.mode, state="readonly", width=13,
                     values=["标准问答", "受限 Agent"]).pack(side="left")
        self.scope = tk.StringVar(value="全部本地缓存")
        ttk.Combobox(controls, textvariable=self.scope, state="readonly", width=17,
                     values=["全部本地缓存", "雷达当前项目"]).pack(side="left", padx=8)
        self.scope_name = tk.StringVar()
        ttk.Label(controls, textvariable=self.scope_name, width=28, style="Muted.TLabel").pack(side="left", padx=4)
        self.ask_button = ttk.Button(controls, text="开始研究", style="Accent.TButton", command=self.start)
        self.ask_button.pack(side="right")
        attachments = ttk.Frame(self)
        attachments.pack(fill="x", pady=(0, 8))
        self.allow_images = tk.BooleanVar(value=False)
        ttk.Checkbutton(attachments, text="仅本题允许读图", variable=self.allow_images).pack(side="left")
        ttk.Button(attachments, text="选择 PNG 截图", command=self.attach).pack(side="left", padx=6)
        ttk.Button(attachments, text="移除附件", command=self.clear_attachments).pack(side="left")
        self.attachment_text = tk.StringVar(value="无附件；图片解读另计调用与估算费用")
        ttk.Label(attachments, textvariable=self.attachment_text, style="Muted.TLabel").pack(side="left", padx=10)

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True)
        history_frame = ttk.Frame(pane, width=255)
        current = ttk.Frame(pane)
        pane.add(history_frame, weight=1)
        pane.add(current, weight=4)
        self.history_tabs = ttk.Notebook(history_frame)
        self.history_tabs.pack(fill="both", expand=True, padx=(0, 10))
        self.history = self._history_tree("最近问题 · 7 天")
        self.bookmarks = self._history_tree("收藏")
        ttk.Label(history_frame, text="收藏保留答案与来源位置。\n原文及过程随任务到期清理。",
                  style="Muted.TLabel", wraplength=240).pack(anchor="w", pady=(8, 0))

        self.state_text = tk.StringVar(value="尚未开始研究")
        ttk.Label(current, textvariable=self.state_text, wraplength=850).pack(fill="x", pady=(0, 8))
        actions = ttk.Frame(current)
        actions.pack(fill="x", pady=(0, 8))
        self.resume_button = ttk.Button(actions, text="取回原结果", command=lambda: self.advance("research_resume"))
        self.continue_button = ttk.Button(actions, text="明确继续", command=lambda: self.advance("research_continue"))
        self.cancel_button = ttk.Button(actions, text="停止后续步骤", command=self.cancel)
        self.bookmark_button = ttk.Button(actions, text="收藏回答", command=self.bookmark)
        for button in (self.resume_button, self.continue_button, self.cancel_button, self.bookmark_button):
            button.pack(side="left", padx=(0, 5))
        feedback = ttk.Frame(current)
        feedback.pack(fill="x", pady=(0, 8))
        ttk.Label(feedback, text="这份回答：").pack(side="left")
        self.feedback_buttons = []
        for label, rating in (("有用", "useful"), ("不相关", "irrelevant"), ("清除反馈", "clear")):
            button = ttk.Button(feedback, text=label, command=lambda rating=rating: self.feedback(rating))
            button.pack(side="left", padx=(0, 5))
            self.feedback_buttons.append(button)
        self.feedback_text = tk.StringVar()
        ttk.Label(feedback, textvariable=self.feedback_text, style="Muted.TLabel").pack(side="left", padx=4)

        self.readers = ttk.Notebook(current)
        self.readers.pack(fill="both", expand=True)
        answer_page, self.source_page, organization_page, trace_page = [ttk.Frame(self.readers) for _ in range(4)]
        for page, label in ((answer_page, "回答与引用"), (self.source_page, "来源原文"),
                            (organization_page, "资料组织"), (trace_page, "步骤记录")):
            self.readers.add(page, text=label)
        self.answer = self.app.reader(answer_page)
        self.organization = self.app.reader(organization_page)
        self.trace = self.app.reader(trace_page)
        source_pane = ttk.Panedwindow(self.source_page, orient="horizontal")
        source_pane.pack(fill="both", expand=True)
        source_list, source_details = ttk.Frame(source_pane), ttk.Frame(source_pane)
        source_pane.add(source_list, weight=1)
        source_pane.add(source_details, weight=3)
        self.sources = ttk.Treeview(source_list, columns=("label", "name", "kind"), show="headings", height=2,
                                    selectmode="browse")
        for key, label, width in (("label", "引用", 55), ("name", "项目 / 附件", 150), ("kind", "资料类型", 90)):
            self.sources.heading(key, text=label)
            self.sources.column(key, width=width, minwidth=50, stretch=key == "name")
        source_bar = ttk.Scrollbar(source_list, command=self.sources.yview)
        self.sources.configure(yscrollcommand=source_bar.set)
        source_bar.pack(side="right", fill="y")
        self.sources.pack(fill="both", expand=True)
        self.sources.bind("<<TreeviewSelect>>", lambda _: self.select_source())
        self.source_open = ttk.Button(source_details, text="打开所选来源", command=self.open_source)
        self.source_open.pack(anchor="e", pady=5)
        self.source_text = self.app.reader(source_details)
        self.app.show_text(self.answer, "# 用已有资料研究项目\n\n例如：哪些项目适合显存有限的视觉检测实验？\n\n标准问答先检索再回答；受限 Agent 可补查、阅读历史、查看偏好和解读获准附件。\n\n每条结论可点击引用，核对来源节选、版本与采集时间。")
        self.app.show_text(self.organization, "尚无资料组织结果。")
        self.app.show_text(self.trace, "尚无执行记录。这里只展示工具动作与结果摘要。")
        self.app.show_text(self.source_text, "选择回答中的引用或上方来源。")
        self.update_buttons()

    def _history_tree(self, title):
        frame = ttk.Frame(self.history_tabs)
        self.history_tabs.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=("question", "state"), show="headings", selectmode="browse")
        tree.heading("question", text="问题")
        tree.heading("state", text="状态")
        tree.column("question", width=190, minwidth=100)
        tree.column("state", width=110, minwidth=80)
        scrollbar = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", lambda _, tree=tree: self.select_history(tree))
        return tree

    def attach(self):
        selected = filedialog.askopenfilenames(parent=self.app, title="选择本题 PNG 截图",
                                               filetypes=[("PNG 截图", "*.png")])
        if selected:
            paths = list(dict.fromkeys(self.image_paths + list(selected)))
            if not self.check_image_count(paths):
                return
            self.image_paths = paths
            self.attachment_text.set("、".join(Path(path).name for path in paths))

    def check_image_count(self, paths):
        configured = self.app.config_data["research"]["max_images"]
        if self.mode.get() != "受限 Agent" and len(paths) > 1:
            self.app.dialog("标准问答附件数量超限", "标准问答每题最多一张 PNG；双图请切换「受限 Agent」，并检查研究设置中的图片数量上限。")
            return False
        if len(paths) > configured:
            self.app.dialog("附件数量超限", f"研究设置中每题最多 {configured} 张 PNG，请调整上限或移除附件。")
            return False
        return True

    def clear_attachments(self):
        self.image_paths = []
        self.attachment_text.set("无附件；图片解读另计调用与估算费用")

    def start(self):
        if self.app.busy:
            self.app.status.set("已有任务正在运行，请等待完成。")
            return
        question = self.question.get("1.0", "end").strip()
        if not 2 <= len(question) <= 1000:
            self.app.dialog("请填写问题", "问题需要 2～1000 字。")
            return
        repo_ids = None
        if self.scope.get() == "雷达当前项目":
            row = self.app.selected()
            if not row:
                self.app.dialog("未选择项目", "先在项目雷达中选择一个已缓存项目。")
                return
            repo_ids = [row["id"]]
        if not self.check_image_count(self.image_paths):
            return
        if self.image_paths and not self.allow_images.get():
            self.app.dialog("本题尚未允许读图", "勾选「仅本题允许读图」后提交，或移除附件。当前未读取或上传图片。")
            return
        identity = uuid.uuid4().hex
        request = dict(question=question, mode="agent" if self.mode.get() == "受限 Agent" else "standard",
                       repo_ids=repo_ids, allow_images=self.allow_images.get(), image_paths=list(self.image_paths),
                       job_id=identity)
        self.active_id, self.job = identity, None
        self.state_text.set("正在创建研究任务，冻结本题资料范围…")
        self.app.show_text(self.answer, "正在准备本题研究…")
        self.sources.delete(*self.sources.get_children())
        self.app.show_text(self.source_text, "正在检索本题来源。")
        self.app.show_text(self.organization, "正在整理本题资料。")
        self.app.show_text(self.trace, "正在准备本题执行记录。")
        self.source_open.configure(state="disabled")
        self.app.work("正在研究本地项目资料…", lambda: self.app.service.run("research", **request))
        # 新问题必须重新授权；后台使用上面捕获的本题许可和附件。
        self.allow_images.set(False)
        self.clear_attachments()
        self.update_buttons()

    def advance(self, action):
        job = self.job
        allowed = "can_resume" if action == "research_resume" else "can_continue"
        if not job or not job.get(allowed) or self.app.busy:
            return
        identity = job["id"]
        self.app.work("正在取回原步骤，不创建新请求…" if action == "research_resume" else "正在继续原研究任务…",
                      lambda: self.app.service.run(action, job_id=identity))
        self.update_buttons()

    def local_action(self, action, **kwargs):
        if not self.active_id:
            return
        try:
            job = self.app.service.run(action, job_id=self.active_id, **kwargs)
            self.display(job)
            self.refresh_history()
        except (ValueError, RuntimeError) as exc:
            self.app.dialog("研究操作未完成", str(exc))

    def cancel(self):
        self.local_action("research_cancel")

    def bookmark(self):
        if self.job:
            self.local_action("research_bookmark", saved=not self.job.get("saved", False))

    def feedback(self, rating):
        self.local_action("research_feedback", rating=rating)

    def select_history(self, tree):
        if self._updating_history or not tree.selection():
            return
        self.active_id = tree.selection()[0]
        self.refresh_active()

    def refresh_history(self):
        self._updating_history = True
        try:
            rows = self.app.service.store.rows(
                "SELECT id,question,state FROM research_jobs WHERE expires>? ORDER BY created DESC LIMIT 100", (time.time(),))
            saved = self.app.service.store.rows(
                "SELECT id,question,'saved' state FROM research_bookmarks ORDER BY created DESC LIMIT 100")
            for tree, records in ((self.history, rows), (self.bookmarks, saved)):
                desired = [row["id"] for row in records]
                for item in tree.get_children():
                    if item not in desired:
                        tree.delete(item)
                for position, row in enumerate(records):
                    values = (row["question"].replace("\n", " "), STATES.get(row["state"], "已收藏"))
                    if tree.exists(row["id"]):
                        tree.item(row["id"], values=values)
                        tree.move(row["id"], "", position)
                    else:
                        tree.insert("", position, iid=row["id"], values=values)
            if self.active_id is None and rows:
                self.active_id = rows[0]["id"]
        finally:
            self._updating_history = False

    def refresh(self):
        row = self.app.selected()
        self.scope_name.set("当前：" + row["name"] if row else "雷达尚未选择项目")
        self.refresh_history()
        self.refresh_active()
        self.update_buttons()

    def refresh_active(self):
        if self.active_id:
            try:
                self.display(self.app.service.run("research_status", job_id=self.active_id))
            except ValueError:
                if not self.app.busy:
                    self.state_text.set("原任务不存在或已到期；可在收藏中查看保留的答案。")
        self.update_buttons()

    def poll(self):
        # 状态接口只访问短本地事务，不争用网络任务的 worker.lock。
        if self.active_id and self.app.busy and time.monotonic() - self.last_poll >= .75:
            self.last_poll = time.monotonic()
            self.refresh_active()
        self.update_buttons()

    def accept_result(self, result):
        if result.get("research_job"):
            self.display(result["research_job"])
            self.refresh_history()

    def update_buttons(self):
        job, idle = self.job or {}, not self.app.busy
        self.ask_button.configure(state="normal" if idle else "disabled")
        self.resume_button.configure(state="normal" if idle and job.get("can_resume") else "disabled")
        self.continue_button.configure(state="normal" if idle and job.get("can_continue") else "disabled")
        stopping = job.get("state") in {"running", "paused", "continuable", "blocked"}
        self.cancel_button.configure(state="normal" if stopping else "disabled")
        self.bookmark_button.configure(text="取消收藏" if job.get("saved") else "收藏回答",
                                       state="normal" if job.get("state") in {"done", "archived"} else "disabled")
        for button in self.feedback_buttons:
            button.configure(state="normal" if job.get("state") == "done" else "disabled")

    def display(self, job):
        if job.get("state") == "deleted":
            self.active_id, self.job = None, None
            self.state_text.set("收藏已移除，原任务已到期。")
            self.app.show_text(self.answer, "收藏已移除。")
            self.sources.delete(*self.sources.get_children())
            self.app.show_text(self.source_text, "原任务资料已到期。")
            self.app.show_text(self.organization, "原任务资料已到期。")
            self.app.show_text(self.trace, "原任务记录已到期。")
            self.source_open.configure(state="disabled")
            self.feedback_text.set("")
            self.update_buttons()
            return
        if self.job == job:
            self.update_buttons()
            return
        self.active_id, self.job = job["id"], job
        state = STATES.get(job["state"], job["state"])
        mode = "受限 Agent" if job.get("mode") == "agent" else "标准问答" if job.get("mode") else "收藏"
        question = job["question"][:100] + ("…" if len(job["question"]) > 100 else "")
        error = job.get("error", "")
        self.state_text.set(f"{state} · {mode} · {job.get('calls', 0)} 次调用 · 累计预留估算 ¥{job.get('reserved_cny', 0):.4f}\n"
                            f"{question}\n{error[:180]}")
        self.feedback_text.set({"useful": "已标记有用", "irrelevant": "已标记不相关"}.get(job.get("feedback"), ""))
        self._render_answer(job)
        previous = self.sources.selection()
        self.sources.delete(*self.sources.get_children())
        for source in job.get("sources", []):
            label = source["label"]
            self.sources.insert("", "end", iid=label, values=(label, source.get("name", ""),
                                 KINDS.get(source.get("kind"), source.get("kind", ""))))
        labels = self.sources.get_children()
        if labels:
            self.sources.selection_set(previous[0] if previous and previous[0] in labels else labels[0])
            self.select_source()
        else:
            self.app.show_text(self.source_text, "本题尚无来源。")
            self.source_open.configure(state="disabled")
        self.app.show_text(self.organization, self._organization_text(job.get("organization", {})))
        trace = "# 工具动作与结果摘要\n\n" + "\n\n".join(
            f"{index}. {item.get('action', '')}\n{item.get('detail', '')}"
            for index, item in enumerate(job.get("trace", []), 1))
        self.app.show_text(self.trace, trace if job.get("trace") else trace + "尚无执行记录。")
        self.update_buttons()

    def _render_answer(self, job):
        widget = self.answer
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for tag in widget.tag_names():
            if tag.startswith("cite:"):
                widget.tag_delete(tag)
        widget.insert("end", "研究回答\n\n", "title")
        widget.insert("end", job["question"] + "\n\n")
        claims = job.get("result", {}).get("claims", [])
        labels = {source["label"] for source in job.get("sources", [])}
        for claim in claims:
            widget.insert("end", claim["text"] + "\n")
            for label in claim.get("sources", []):
                tag = "cite:" + label
                widget.insert("end", f"[{label}] ", tag)
                widget.tag_configure(tag, underline=True)
                if label in labels:
                    widget.tag_bind(tag, "<Button-1>", lambda _, label=label: self.show_source(label))
            widget.insert("end", "\n\n")
        if not claims:
            widget.insert("end", job.get("error") or "任务进行中，回答完成后显示逐条引用。")
        limitations = job.get("result", {}).get("limitations", [])
        if limitations:
            widget.insert("end", "\n资料局限\n", "subtitle")
            for limitation in limitations:
                widget.insert("end", "• " + limitation + "\n")
        widget.configure(state="disabled")

    def show_source(self, label):
        if self.sources.exists(label):
            self.readers.select(self.source_page)
            self.sources.selection_set(label)
            self.sources.see(label)
            self.select_source()

    def selected_source(self):
        selected = self.sources.selection()
        return next((source for source in (self.job or {}).get("sources", [])
                     if selected and source["label"] == selected[0]), None)

    def select_source(self):
        source = self.selected_source()
        if not source:
            return
        text = (f"# [{source['label']}] {source.get('name', '')}\n\n"
                f"来源：{source.get('url') or '本题附件，无远程链接'}\n"
                f"版本 / 指纹：{source.get('sha') or '未提供'}\n"
                f"采集时间：{source.get('captured') or '未提供'}\n"
                f"资料类型：{KINDS.get(source.get('kind'), source.get('kind', ''))}\n\n"
                + (source.get("text") or "收藏保留来源位置；原文已随任务到期清理，请打开来源重新核对。"))
        if source.get("truncated"):
            text += "\n\n本来源为截断节选。"
        self.app.show_text(self.source_text, text)
        self.source_open.configure(state="normal" if safe_url(source.get("url", "")) else "disabled")

    def open_source(self):
        source = self.selected_source()
        url = safe_url(source.get("url", "")) if source else ""
        if url:
            webbrowser.open(url)

    @staticmethod
    def _organization_text(organization):
        lines = ["# 资料组织", "", organization.get("note", "尚无组织结果。")]
        if organization.get("truncated"):
            lines += ["", "本次范围或检索结果包含采样 / 截断，未覆盖全部资料。"]
        for topic in organization.get("topics", []):
            lines += ["", "### " + topic["title"], "、".join(topic["sources"])]
        duplicates = organization.get("duplicates", [])
        if duplicates:
            lines += ["", "### 重复节选", "\n".join("、".join(labels) for labels in duplicates)]
        timeline = organization.get("timeline", [])
        if timeline:
            lines += ["", "### Star 本地观测"]
            for row in timeline:
                change = row.get("change_since_previous")
                lines.append(f"{row['day']} · {row['name']} · {row['stars']} Star · "
                             + ("首次观测，无增量基线" if change is None else f"比上次 {change:+d}"))
        return "\n".join(lines)
