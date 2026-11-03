from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta


def hits(text, terms):
    return [term for term in terms if re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", text)]


def rank(row, config, now, baseline=None):
    repo = json.loads(row["metadata"])
    text = " ".join([repo["full_name"], repo.get("description") or "", " ".join(repo.get("topics", []))]).lower()
    research = hits(text, config["profile"]["research_terms"])
    hot = hits(text, config["profile"]["hot_terms"])
    # 检索命中与画像词命中分开；不能只凭采集来源就认定适合研究。
    bucket = "research" if research else "hot"
    reasons = []
    if repo.get("archived") or repo.get("fork") or row["feedback"] == "dismissed":
        return 0, bucket, ["已归档、分叉或已忽略"]
    if any(x in repo["full_name"].lower().split("/")[-1] for x in ("awesome-", "-awesome", "roadmap", "interview")):
        return 0, bucket, ["资料合集／面试清单不进入首版推荐"]
    if not research and not hot:
        return 0, bucket, ["未匹配研究画像或热点关键词"]
    updated = datetime.fromisoformat(repo["pushed_at"])
    age = max(0, (now - updated).days)
    if age > config["discovery"]["active_days"]:
        return 0, bucket, ["近期未活跃"]
    matched = research or hot
    score = 34 + min(12, len(matched) * 4)
    reasons.append("研究匹配：" + "、".join(matched[:4]) if research else "热点匹配：" + "、".join(matched[:4]))
    score += min(12, max(0, math.log10(max(repo["stargazers_count"], 1)) * 3))
    score += 12 if age <= 30 else 7 if age <= 90 else 2
    reasons.append(f"最近推送距今 {age} 天；Star {repo['stargazers_count']:,}（热度不代表质量）")
    if repo.get("license"):
        score += 4
    if len(row["readme"].strip()) >= 300:
        score += 10
        reasons.append("有可读 README，支持进一步核对使用条件")
    if baseline:
        days = (now.date() - datetime.fromisoformat(baseline["day"]).date()).days
        delta = repo["stargazers_count"] - baseline["stars"]
        if days > 0:
            score += min(10, max(0, delta / days) / 10)
            reasons.append(f"本地观测 {days} 天 Star 净变化 {delta:+,}；不代表全站趋势排名")
    else:
        reasons.append("尚无跨日 Star 基线，增速未知")
    return round(min(score, 100), 1), bucket, reasons


def choose(rows, config, now, recent_ids):
    cutoff = (now - timedelta(days=7)).isoformat()
    eligible = [r for r in rows if r["score"] >= config["digest"]["min_score"] and r["seen_at"] >= cutoff
                and r["id"] not in recent_ids and len(r["readme"].strip()) >= 300 and r["feedback"] != "dismissed"
                and r.get("study_state") != "studied"]
    priority = {"focus": 3, "studying": 2, "saved": 1}
    eligible.sort(key=lambda r: (priority.get(r.get("study_state"), int(r["feedback"] == "saved")), r["score"]), reverse=True)
    maximum = config["digest"]["max_projects"]
    hot_limit = config["digest"]["hot_slots"]
    selected, owners = [], set()
    research_count = sum(r["bucket"] == "research" for r in eligible)
    research_limit = maximum - min(hot_limit, sum(r["bucket"] == "hot" for r in eligible))
    for bucket, limit in (("research", research_limit), ("hot", min(hot_limit, maximum - min(research_limit, research_count)))):
        count = 0
        for row in eligible:
            owner = row["name"].split("/")[0].lower()
            if count < limit and row["bucket"] == bucket and owner not in owners:
                selected.append(row)
                owners.add(owner)
                count += 1
    return selected  # 保持热点配额；不足时宁缺毋滥。
