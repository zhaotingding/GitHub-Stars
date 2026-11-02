from __future__ import annotations

import base64
import time
from datetime import timedelta

import httpx


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, token="", client=None):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "GitHub-Stars/0.1.0",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = client or httpx.Client(base_url="https://api.github.com", headers=headers,
                                            timeout=30, follow_redirects=True)

    def close(self):
        self.client.close()

    def get(self, path, params=None):
        for attempt in range(3):
            try:
                response = self.client.get(path, params=params)
            except httpx.TransportError:
                if attempt == 2:
                    raise GitHubError("GitHub 网络连接失败，请检查网络／代理；已保留已有数据") from None
                time.sleep(2 ** attempt)
                continue
            if response.status_code in (403, 429):
                reset = response.headers.get("x-ratelimit-reset", "未知")
                retry = response.headers.get("retry-after", "未知")
                raise GitHubError(f"GitHub 请求受限（HTTP {response.status_code}）；reset={reset}，retry-after={retry}；稍后重试或配置 Token")
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                raise GitHubError(f"GitHub HTTP {response.status_code}；检查 Token、检索语句或仓库是否仍存在")
            try:
                return response.json()
            except ValueError:
                raise GitHubError("GitHub 返回内容不是有效 JSON") from None

    def search(self, query, count, sort="stars"):
        result = self.get("/search/repositories", {"q": query, "sort": sort, "order": "desc", "per_page": count})
        if result.get("incomplete_results"):
            raise GitHubError("GitHub 搜索超时，返回的是不完整结果；本次不标记为完整采集")
        return result["items"]

    def readme(self, name):
        doc = self.get(f"/repos/{name}/readme")
        if doc.get("encoding") != "base64" or doc.get("size", 0) > 1_000_000:
            raise GitHubError("README 太大或编码不支持，保留元数据供手动阅读")
        content = base64.b64decode(doc["content"]).decode("utf-8", errors="replace")
        return content[:100000], doc["sha"], doc["html_url"]  # 有界缓存，发送模型时再截短。


def queries(config, now):
    settings = config["discovery"]
    active = (now.date() - timedelta(days=settings["active_days"])).isoformat()
    recent = (now.date() - timedelta(days=45)).isoformat()
    for bucket, key in (("research", "research_queries"), ("hot", "hot_queries")):
        for term in settings[key]:
            yield bucket, f"{term} stars:>={settings['min_stars']} pushed:>={active} archived:false fork:false", "stars"
    yield "hot", f"topic:artificial-intelligence stars:>={settings['new_min_stars']} created:>={recent} archived:false fork:false", "stars"
    # 最后一条补充高星检索难以覆盖的新项目；仍不是 GitHub 全站排行榜。
