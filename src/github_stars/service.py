from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import ai, mailer
from .github import GitHub, GitHubError, parse_repositories, queries
from .ranking import choose, rank
from .reports import export_digest
from .store import STUDY_STATES, Store, exclusive
from .tutorial_html import export_tutorial


class Service:
    def __init__(self, paths, github_factory=None, clock=None):
        self.paths = paths
        self.store = Store(paths.data / "stars.sqlite3")
        self.github_factory = github_factory or GitHub
        self.clock = clock

    def now(self, config):
        return self.clock() if self.clock else datetime.now(ZoneInfo(config["schedule"]["timezone"]))

    def run(self, action, **kwargs):
        with exclusive(self.paths.data / "worker.lock"):
            config = self.paths.load()  # 每次工作重新读取，修改设置无需重启计划任务。
            now = self.now(config)
            # 拿到互斥锁说明没有其他业务执行者；上次仍在途的状态来自中断。
            self.store.execute("UPDATE ai_jobs SET status='unknown',error='进程中断，禁止自动重新提交' WHERE status='submitting'")
            self.store.execute("UPDATE digests SET mail_state='unknown',mail_detail='进程中断，请检查收件箱' WHERE mail_state='sending'")
            self.store.execute("UPDATE scans SET status='interrupted',detail='进程中断，稍后重新采集' WHERE status='running'")
            try:
                if action == "scan":
                    return self.scan(config, now)
                if action == "digest":
                    return self.digest(config, now)
                if action == "import":
                    return self.import_repositories(config, now, kwargs["text"])
                if action == "study_state":
                    state = kwargs["state"]
                    if state not in STUDY_STATES:
                        raise ValueError("请选择有效研究状态")
                    self.store.execute("UPDATE repos SET study_state=?,feedback=? WHERE id=?",
                                       (state, "saved" if state in {"saved", "focus"} else "new", kwargs["repo_id"]))
                    return f"已标记为{STUDY_STATES[state]}"
                if action in {"analysis", "tutorial"}:
                    row = self.store.one("SELECT * FROM repos WHERE id=?", (kwargs["repo_id"],))
                    if not row:
                        raise ValueError("项目不存在")
                    row = self.ensure_readme(row, now)
                    result = ai.generate(self.paths, self.store, config, row, now, retry=kwargs.get("retry", False), kind=action)
                    return self.generated_result(row, result, config)
                if action == "recover":
                    row = self.store.one("SELECT * FROM repos WHERE id=?", (kwargs["repo_id"],))
                    result = ai.recover(self.paths, self.store, kwargs["repo_id"], now, kind=kwargs.get("kind", "tutorial"))
                    return self.generated_result(row, result, config)
                if action == "open_tutorial":
                    row = self.store.one("SELECT * FROM repos WHERE id=?", (kwargs["repo_id"],))
                    job = self.store.one("SELECT result FROM ai_jobs WHERE repo_id=? AND kind='tutorial' AND status='completed' ORDER BY id DESC LIMIT 1", (kwargs["repo_id"],))
                    if not job:
                        raise ValueError("该项目尚未生成 HTML 教程")
                    return self.generated_result(row, json.loads(job["result"]), config)
                if action == "email":
                    return mailer.send_digest(self.paths, self.store, config, kwargs["week"], now, retry=kwargs.get("retry", False))
                if action == "tick":
                    return self.tick(config, now)
                raise ValueError("未知操作")
            except Exception as exc:
                # 仅存储受控业务错误；第三方异常只记录类型，避免 URL／认证信息泄露。
                safe = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                self.store.event(now, "ERROR", f"{action}：{safe}")
                raise

    def generated_result(self, row, result, config):
        if result.get("_kind") != "tutorial":
            return {"message": "旧版教程已恢复，可在任务窗口阅读" if result.get("_kind") == "legacy" else "初始分析已保存", "repo_id": row["id"]}
        job = self.store.one("SELECT evidence FROM ai_jobs WHERE id=?", (result["_job_id"],))
        evidence = json.loads(job["evidence"])
        source = {**row, "readme_url": evidence["readme_url"], "readme_sha": result["_sha"], "readme_at": result["_captured"]}
        page = export_tutorial(self.paths, source, result, result["_job_id"], config["appearance"]["theme"])
        return {"message": "HTML 教程已就绪", "path": str(page), "repo_id": row["id"]}

    def ensure_readme(self, row, now):
        if len(row["readme"].strip()) >= 300:
            return row
        client = self.github_factory(self.paths.secret("github"))
        try:
            content, sha, url = client.readme(row["name"])
            self.store.execute("UPDATE repos SET readme=?,readme_sha=?,readme_url=?,readme_at=? WHERE id=?",
                               (content, sha, url, now.isoformat(), row["id"]))
        finally:
            client.close()
        return self.store.one("SELECT * FROM repos WHERE id=?", (row["id"],))

    def import_repositories(self, config, now, text):
        names = parse_repositories(text)
        client = self.github_factory(self.paths.secret("github"))
        imported, problems = [], []
        try:
            for name in names:
                try:
                    repo = client.repository(name)
                    self.store.upsert(repo, "hot", now)
                    self.store.execute("UPDATE repos SET manual=1 WHERE id=?", (repo["id"],))
                    imported.append(repo["id"])
                    try:
                        content, sha, url = client.readme(repo["full_name"])
                        self.store.execute("UPDATE repos SET readme=?,readme_sha=?,readme_url=?,readme_at=? WHERE id=?",
                                           (content, sha, url, now.isoformat(), repo["id"]))
                    except GitHubError as exc:
                        problems.append(f"{name} README：{exc}")
                except GitHubError as exc:
                    problems.append(f"{name}：{exc}")
        finally:
            client.close()
        self.rescore(config, now)
        message = f"已导入／刷新 {len(imported)} 个仓库（不受高星门槛限制）"
        if problems:
            message += "；" + "；".join(problems)
        self.store.event(now, "WARNING" if problems else "INFO", message)
        return {"message": message, "repo_id": imported[0] if imported else None}

    def rescore(self, config, now):
        for row in self.store.rows("SELECT * FROM repos"):
            baseline = self.store.one("SELECT * FROM snapshots WHERE repo_id=? AND day<? AND day>=? ORDER BY day LIMIT 1",
                                      (row["id"], now.date().isoformat(), (now.date() - timedelta(days=7)).isoformat()))
            score, bucket, reasons = rank(row, config, now, baseline)
            self.store.execute("UPDATE repos SET score=?,bucket=?,reasons=? WHERE id=?",
                               (score, bucket, json.dumps(reasons, ensure_ascii=False), row["id"]))

    def scan(self, config, now):
        scan_id = self.store.execute("INSERT INTO scans(started,status) VALUES (?,'running')", (now.isoformat(),))
        client = self.github_factory(self.paths.secret("github"))
        seen, failures, readme_failures = set(), [], []
        self.store.set_state("last_scan_attempt", now.isoformat())
        try:
            for bucket, query, sort in queries(config, now):
                try:
                    for repo in client.search(query, config["discovery"]["per_query"], sort):
                        self.store.upsert(repo, bucket, now)
                        seen.add(repo["id"])
                except GitHubError as exc:
                    failures.append(str(exc))
                    if "受限" in str(exc):
                        break
            self.rescore(config, now)
            candidates = self.store.rows("SELECT * FROM repos WHERE score>=? AND seen_at=? ORDER BY score DESC",
                                         (config["digest"]["min_score"] - 10, now.isoformat()))
            # 给热点留出读取名额，避免全部预算被高分研究仓库占满。
            quota = max(1, config["discovery"]["readme_limit"] // 3)
            hot = [r for r in candidates if r["bucket"] == "hot"][:quota]
            first = [r for r in candidates if r["bucket"] == "research"][:config["discovery"]["readme_limit"] - len(hot)] + hot
            first_ids = {r["id"] for r in first}
            candidates = first + [r for r in candidates if r["id"] not in first_ids]
            fetched = 0
            for row in candidates:
                if fetched >= config["discovery"]["readme_limit"]:
                    break
                if row["readme_at"] and row["readme_at"] >= (now - timedelta(days=7)).isoformat():
                    continue
                fetched += 1
                try:
                    content, sha, url = client.readme(row["name"])
                    self.store.execute("UPDATE repos SET readme=?,readme_sha=?,readme_url=?,readme_at=? WHERE id=?",
                                       (content, sha, url, now.isoformat(), row["id"]))
                except GitHubError as exc:
                    readme_failures.append(f"{row['name']}：{exc}")
                    if "受限" in str(exc):
                        failures.append(str(exc))
                        break
            self.rescore(config, now)
            status = "partial" if failures else "completed"
            detail = "；".join(failures + readme_failures) or "查询完成；每个查询为有限采样，不是全站穷举"
            self.store.execute("UPDATE scans SET status=?,count=?,detail=? WHERE id=?", (status, len(seen), detail, scan_id))
            if not failures:
                self.store.set_state("last_scan_day", now.date().isoformat())
            self.store.event(now, "WARNING" if failures else "INFO", f"采集 {status}：{len(seen)} 个项目；{detail}")
            return f"{'部分完成' if failures else '采集完成'}：{len(seen)} 个项目，读取 {fetched} 份 README" + (f"；{detail}" if failures else "")
        except Exception:
            self.store.execute("UPDATE scans SET status='failed',detail='采集异常，详见运行记录' WHERE id=?", (scan_id,))
            raise
        finally:
            client.close()

    def digest(self, config, now):
        week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        if self.store.one("SELECT week FROM digests WHERE week=?", (week,)):
            export_digest(self.paths, self.store, week)
            return week  # 同周复用，避免重复推荐与重复生成费用。
        self.rescore(config, now)
        recent = self.store.rows("SELECT s.repo_id FROM selections s JOIN digests d USING(week) WHERE d.created>=?",
                                 ((now - timedelta(days=config["digest"]["cooldown_days"])).isoformat(),))
        rows = choose(self.store.rows("SELECT * FROM repos ORDER BY score DESC"), config, now, {r["repo_id"] for r in recent})
        latest = self.store.one("SELECT * FROM scans ORDER BY id DESC LIMIT 1")
        if not latest:
            raise ValueError("请先完成一次采集，再生成周报")
        if latest["status"] != "completed":
            raise ValueError("最近采集未完整成功，请重试采集后再生成周报；已有候选仍可阅读")
        if latest["started"] < (now - timedelta(days=7)).isoformat():
            raise ValueError("采集数据已超过七天，请先刷新")
        note = f"本周精选 {len(rows)} 项；最多 {config['digest']['max_projects']} 项；近 {config['digest']['cooldown_days']} 天推荐过的项目已排除。"
        with self.store.connect() as db:
            db.execute("INSERT INTO digests(week,created,note) VALUES (?,?,?)", (week, now.isoformat(), note))
            for index, row in enumerate(rows):
                db.execute("INSERT INTO selections VALUES (?,?,?,?)", (week, row["id"], index, json.dumps(row, ensure_ascii=False)))
        export_digest(self.paths, self.store, week)
        self.store.event(now, "INFO", f"已生成 {week} 周报，{len(rows)} 个项目")
        return week

    def tick(self, config, now):
        schedule = config["schedule"]
        if not schedule["enabled"]:
            return "自动调度已关闭"
        results = []
        last_attempt = self.store.state("last_scan_attempt")
        ready = not last_attempt or now - datetime.fromisoformat(last_attempt) >= timedelta(hours=1)
        if now.hour >= schedule["daily_hour"] and self.store.state("last_scan_day") != now.date().isoformat() and ready:
            results.append(self.scan(config, now))
        due = now.weekday() > schedule["weekly_day"] or (now.weekday() == schedule["weekly_day"] and now.hour >= schedule["weekly_hour"])
        if due:
            week = self.digest(config, now)
            if config["ai"]["enabled"] and config["ai"]["auto_analyze"]:
                for selected in self.store.rows("SELECT repo_id FROM selections WHERE week=? ORDER BY position", (week,)):
                    row = self.store.one("SELECT * FROM repos WHERE id=?", (selected["repo_id"],))
                    if not self.store.one("SELECT id FROM ai_jobs WHERE repo_id=? AND kind='analysis'", (row["id"],)):
                        try:
                            ai.generate(self.paths, self.store, config, row, now, kind="analysis")
                        except (RuntimeError, ValueError) as exc:
                            self.store.event(now, "WARNING", f"自动初始分析：{exc}")
                export_digest(self.paths, self.store, week)
            # 没有入选项目时静默，只在应用内记录，不发送空周报。
            if self.store.one("SELECT repo_id FROM selections WHERE week=?", (week,)) and config["email"]["enabled"]:
                delivery = self.store.one("SELECT * FROM digests WHERE week=?", (week,))
                retry_due = not delivery["mail_attempt"] or now - datetime.fromisoformat(delivery["mail_attempt"]) >= timedelta(hours=6)
                if delivery["mail_state"] in {"pending", "failed"} and retry_due:
                    results.append(mailer.send_digest(self.paths, self.store, config, week, now))
            results.append(f"周报已就绪：{week}")
        return "；".join(results) or "当前没有到期任务"
