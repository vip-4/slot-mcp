"""Metaso（秘塔 AI 搜索）客户端：GEO 收录与 AI 摘要监测。

静态站做完 SEO/GEO 之后需要一条闭环：定期问一次「AI 搜索能不能找到我的站点、
摘要怎么描述它」，把结果写进巡检报告。

接口（实测）：`POST https://metaso.cn/api/v1/search`，`Authorization: Bearer <key>`，
body 形如 `{"q": ..., "scope": "webpage", "size": 5, "includeSummary": true}`。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .http import request_json

BASE_URL = "https://metaso.cn/api/v1"


class MetasoClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: float = 25.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def search(
        self,
        query: str,
        *,
        scope: str = "webpage",
        size: int = 5,
        include_summary: bool = True,
    ) -> Tuple[bool, int, Any]:
        body = {
            "q": query,
            "scope": scope,
            "size": size,
            "includeSummary": include_summary,
        }
        return request_json(
            f"{self.base_url}/search",
            method="POST",
            headers=self._headers(),
            body=body,
            timeout=self.timeout,
        )

    def site_report(self, site_url: str, query: str) -> Dict[str, Any]:
        """返回结构化 GEO 监测结果：是否被收录、命中条目、AI 摘要。"""
        out: Dict[str, Any] = {
            "query": query,
            "indexed": False,
            "hits": [],
            "summary": "",
            "error": "",
            "matched": 0,
        }
        ok, status, payload = self.search(query)
        if not ok:
            out["error"] = f"HTTP {status}: {payload}"
            return out
        if not isinstance(payload, dict):
            out["error"] = f"响应格式异常: {str(payload)[:120]}"
            return out

        host = site_url.replace("https://", "").replace("http://", "").strip("/")
        webpages: List[Dict[str, Any]] = payload.get("webpages", []) or []
        out["total"] = len(webpages)
        for item in webpages:
            link = item.get("link", "")
            hit = {
                "title": item.get("title", ""),
                "link": link,
                "snippet": (item.get("snippet", "") or "")[:160],
                "own": host in link,
            }
            out["hits"].append(hit)
            if hit["own"]:
                out["indexed"] = True
        out["matched"] = sum(1 for h in out["hits"] if h["own"])
        summary = payload.get("summary")
        if isinstance(summary, str):
            out["summary"] = summary[:400]
        elif isinstance(summary, dict):
            out["summary"] = str(summary.get("text", ""))[:400]
        return out
