"""Supabase REST 客户端（PostgREST，publishable/anon key）。

用途：站点上线后，前端可用 publishable key 直连 REST 做「社区统计与排行榜」——
这不需要自建后端，静态站仍是静态站。本项目当前把它作为**可选增强**：

* 项目处于 `ACTIVE` 时：`--stats` 读取聚合数据、前端可写入成绩；
* 项目暂停（本项目实测为 `INACTIVE`，REST 域名无法解析）时：自动降级为
  「用 Neon 快照 + 构建期注入」，页面照常可用。

接口形态：
    GET  {base}/rest/v1/{table}?select=...      headers: apikey / Authorization
    POST {base}/rest/v1/{table}                 headers: + Prefer: return=representation
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .http import request_json

MANAGEMENT_BASE = "https://api.supabase.com/v1"


class SupabaseClient:
    def __init__(self, project_url: str, key: str, timeout: float = 15.0) -> None:
        self.project_url = project_url.rstrip("/")
        self.key = key
        self.timeout = timeout

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}"}
        headers.update(extra or {})
        return headers

    def ping(self) -> Tuple[bool, str]:
        ok, status, payload = request_json(
            f"{self.project_url}/rest/v1/", headers=self._headers(), timeout=self.timeout, retries=0
        )
        if ok:
            return True, "REST 可用"
        if status == 0:
            return False, "REST 不可达（项目可能已暂停：DNS 解析失败）"
        return False, f"HTTP {status}: {str(payload)[:120]}"

    def select(self, table: str, query: str = "select=*") -> Tuple[bool, Any, str]:
        url = f"{self.project_url}/rest/v1/{table}?{query}"
        ok, status, payload = request_json(url, headers=self._headers(), timeout=self.timeout, retries=0)
        return (ok, payload, "") if ok else (False, None, f"HTTP {status}: {str(payload)[:150]}")

    def insert(self, table: str, row: Dict[str, Any]) -> Tuple[bool, Any, str]:
        ok, status, payload = request_json(
            f"{self.project_url}/rest/v1/{table}",
            method="POST",
            headers=self._headers({"Prefer": "return=representation"}),
            body=row,
            timeout=self.timeout,
            retries=0,
        )
        return (ok, payload, "") if ok else (False, None, f"HTTP {status}: {str(payload)[:150]}")


def project_status(ref: str, access_token: str) -> Tuple[bool, Any, str]:
    """查询项目状态（Management API）。`status` 为 `ACTIVE_HEALTHY` / `INACTIVE` 等。"""
    ok, status, payload = request_json(
        f"{MANAGEMENT_BASE}/projects/{ref}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20.0,
        retries=0,
    )
    return (ok, payload, "") if ok else (False, None, f"HTTP {status}: {str(payload)[:150]}")
