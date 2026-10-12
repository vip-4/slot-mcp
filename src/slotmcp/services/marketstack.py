"""marketstack 客户端（经 APILayer 网关）。

实测可用形态（注意：直连 `api.marketstack.com` 用 `access_key` 会 401，
走 APILayer 网关需要在请求头带 `apikey`）：

    GET https://api.apilayer.net/marketstack/v2/eod?symbols=AAPL&limit=1
        headers: {"apikey": "<APILayer key>"}

自由额度只够查询有限标的（如 AAPL）。本项目把它作为**外部数据源可用性监测**的样本，
不把金融数据写入站点内容（与机台主题无关，混入会稀释 SEO/GEO 焦点）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .http import request_json

DEFAULT_BASE = "https://api.apilayer.net/marketstack"


class MarketstackClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"apikey": self.api_key, "Accept": "application/json", "User-Agent": "slot-mcp/1.0"}

    def _url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/marketstack"):
            return f"{base}{path}"
        return f"{base}/marketstack{path}"

    def eod(self, symbols: str, limit: int = 1) -> Tuple[bool, List[Dict[str, Any]], str]:
        ok, status, payload = request_json(
            self._url(f"/v2/eod?symbols={symbols}&limit={limit}"),
            headers=self._headers(),
            timeout=self.timeout,
        )
        if not ok:
            return False, [], f"HTTP {status}: {str(payload)[:200]}"
        if isinstance(payload, dict) and payload.get("error"):
            err = payload["error"]
            return False, [], str(err.get("message") if isinstance(err, dict) else err)
        rows = (payload or {}).get("data") if isinstance(payload, dict) else None
        return True, list(rows or []), ""

    def status(self, symbols: str = "AAPL") -> Dict[str, Any]:
        ok, rows, detail = self.eod(symbols, limit=1)
        if not ok:
            return {"ok": False, "detail": detail, "symbol": symbols}
        row = rows[0] if rows else {}
        return {
            "ok": True,
            "symbol": symbols,
            "close": row.get("close"),
            "date": (row.get("date") or "")[:10],
            "detail": "可用",
        }
