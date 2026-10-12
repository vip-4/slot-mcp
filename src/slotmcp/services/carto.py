"""CARTO 客户端（空间数据 / SQL 查询）。

CARTO Cloud（本例为 `gcp-us-east1` 区域）的 SQL 接口为：

    POST https://gcp-us-east1.api.carto.com/v3/sql/{connection}/query   （Bearer 鉴权）

实测：本次提供的令牌对应账号 `ac_lv1128s9` 状态为 **Account suspended**（HTTP 401），
因此客户端把「账号被停用 / 路由不存在」都降级为结构化说明，不抛异常——
运维流水线可以照常跑完并如实报告。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .http import request_json

DEFAULT_HOST = "https://gcp-us-east1.api.carto.com"


class CartoClient:
    def __init__(
        self,
        token: str,
        host: str = DEFAULT_HOST,
        connection: str = "carto_dw",
        timeout: float = 20.0,
    ) -> None:
        self.token = token
        self.host = host.rstrip("/")
        self.connection = connection
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "slot-mcp/1.0",
        }

    def sql(self, query: str) -> Tuple[bool, List[Dict[str, Any]], str]:
        """执行 SQL，返回 `(ok, rows, 说明)`。"""
        ok, status, payload = request_json(
            f"{self.host}/v3/sql/{self.connection}/query",
            method="POST",
            headers=self._headers(),
            body={"q": query},
            timeout=self.timeout,
        )
        if not ok:
            return False, [], f"HTTP {status}: {str(payload)[:200]}"
        if isinstance(payload, dict) and payload.get("error"):
            return False, [], str(payload.get("error"))
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        return True, list(rows or []), ""

    def status(self) -> Dict[str, Any]:
        """探活：返回 `{ok, detail}`。账号停用时给出明确原因。"""
        ok, rows, detail = self.sql("SELECT 1 AS ok")
        if ok:
            return {"ok": True, "detail": f"可用（{len(rows)} 行）"}
        lowered = detail.lower()
        if "suspended" in lowered:
            return {"ok": False, "detail": "账号已停用（Account suspended），需恢复后才能查询"}
        if "401" in detail or "403" in detail:
            return {"ok": False, "detail": f"鉴权失败: {detail}"}
        if "404" in detail:
            return {"ok": False, "detail": f"接口路由不存在（区域或版本不匹配）: {detail}"}
        return {"ok": False, "detail": detail or "未知错误"}
