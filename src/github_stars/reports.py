from __future__ import annotations

import html
import json


def project_text(row, tutorial=None):
    repo = json.loads(row["metadata"])
    reasons = json.loads(row["reasons"])
    parts = [f"## {row['name']}", f"项目地址：https://github.com/{row['name']}",
             f"原始简介：{repo.get('description') or '作者未填写简介'}",
             f"推荐分：{row['score']} / 100 · {'研究方向' if row['bucket'] == 'research' else 'AI 热点'}",
             "为什么进入候选：\n" + "\n".join(f"- {reason}" for reason in reasons),
             f"语言：{repo.get('language') or '未声明'}；许可证：{(repo.get('license') or {}).get('spdx_id', '未声明，使用前需核对')}"]
    if tutorial:
        for title, key in (("一分钟理解", "summary"), ("与你的研究有什么关系", "relevance"),
                           ("入门教程（AI 根据资料生成，未实际执行）", "tutorial"), ("限制与待核实", "limitations")):
            parts.append(f"### {title}\n{tutorial[key]}")
        parts.append(f"生成依据：README 快照 {tutorial.get('_sha', '未知')}，采集于 {tutorial.get('_captured', '未知')}")
    else:
        parts.append("### 快速阅读路线（未调用 AI）\n1. 阅读 README 的介绍、示例和安装章节，确认具体解决什么问题。\n"
                     "2. 核对许可证、最近提交、依赖和算力要求。\n3. 优先尝试官方最小示例，再考虑接入研究；本程序未执行仓库代码。\n"
                     "配置 OpenAI 后可生成中文解读、具体步骤、预期结果及排障教程。")
    if row.get("readme_url"):
        parts.append(f"来源：{row['readme_url']}\nREADME 采集时间：{row.get('readme_at') or '未知'}")
    return "\n\n".join(parts)


def digest_text(store, week):
    digest = store.one("SELECT * FROM digests WHERE week=?", (week,))
    if not digest:
        raise ValueError("尚无此周周报")
    rows = store.rows("SELECT * FROM selections WHERE week=? ORDER BY position", (week,))
    parts = [f"# GitHub Stars++ · {week} 周报", f"生成于 {digest['created']}", digest["note"],
             "每天观察，每周只读几项。以下是个性化候选，不是全站排名，也不是项目质量认证。"]
    for item in rows:
        job = store.one("SELECT result FROM ai_jobs WHERE repo_id=? AND status='completed' ORDER BY id DESC LIMIT 1", (item["repo_id"],))
        parts.append(project_text(json.loads(item["snapshot"]), json.loads(job["result"]) if job else None))
    if not rows:
        parts.append("本周没有达到阈值且未推荐过的项目。继续观察，不为填满数量降低门槛。")
    return "\n\n---\n\n".join(parts)


def html_document(text, title="GitHub Stars++"):
    # 所有仓库文本与模型输出均转义，导出的 HTML 不加载脚本或远程图片。
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>{html.escape(title)}</title><style>body{{margin:40px auto;padding:0 24px;max-width:900px;"
            "font:17px/1.8 system-ui;color:#19302a;background:#f5f7f3}pre{white-space:pre-wrap;overflow-wrap:anywhere;"
            "font:inherit;background:white;padding:32px;border-radius:16px;border:1px solid #dde6df}</style>"
            f"<pre>{html.escape(text)}</pre></html>")


def export_digest(paths, store, week):
    folder = paths.data / "reports"
    folder.mkdir(exist_ok=True)
    text = digest_text(store, week)
    markdown = folder / f"{week}.md"
    page = folder / f"{week}.html"
    markdown.write_text(text, encoding="utf-8")
    page.write_text(html_document(text), encoding="utf-8")
    return page
