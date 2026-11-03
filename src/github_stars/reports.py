from __future__ import annotations

import html
import json


def project_text(row, analysis=None):
    repo = json.loads(row["metadata"])
    reasons = json.loads(row["reasons"])
    parts = [f"## {row['name']}", f"项目地址：https://github.com/{row['name']}",
             f"原始简介：{repo.get('description') or '作者未填写简介'}",
             ]
    if analysis:
        for title, key in (("这个项目做什么", "summary"), ("哪些地方值得你用", "relevance"),
                           ("如何开始使用", "usage"), ("相关项目与选择", "related_projects"), ("限制与待核实", "limitations")):
            parts.append(f"### {title}\n{analysis.get(key, '旧版材料未包含此节')}")
        parts.append(f"分析依据：README 快照 {analysis.get('_sha', '未知')}，采集于 {analysis.get('_captured', '未知')}")
    else:
        parts.append("### 初始分析待生成\n启用 AI 后，点击“初始分析”了解用途、值得使用的地方、入门方法和相关项目。\n"
                     "觉得值得深入时，再主动生成独立的可视化 HTML 教程。教程模型、预算和提示词可单独配置。")
    parts.extend([f"### 采集信息\n语言：{repo.get('language') or '未声明'}；许可证：{(repo.get('license') or {}).get('spdx_id', '未声明，使用前核对')}",
                  f"匹配分：{row['score']} / 100 · {'研究方向' if row['bucket'] == 'research' else 'AI 热点'}\n" + "\n".join(reasons)])
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
        job = store.one("SELECT result FROM ai_jobs WHERE repo_id=? AND kind='analysis' AND status='completed' ORDER BY id DESC LIMIT 1", (item["repo_id"],))
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
