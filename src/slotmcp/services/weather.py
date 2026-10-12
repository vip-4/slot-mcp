"""Pirate Weather 客户端（经 apiable.io 网关）。

预期形态：`GET https://pirate-weather.apiable.io/forecast/{key}/{lat},{lon}`。

实测：该网关对本环境所有路径都返回 **门户 HTML**（`text/html`）而不是 JSON，
即天气接口在当前网关下不可直接调用。客户端按「网关返回非 JSON」降级并给出原因，
避免把 HTML 当成天气数据解析。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from .http import request_json

DEFAULT_BASE = "https://pirate-weather.apiable.io"


class PirateWeatherClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"Accept": "application/json", "User-Agent": "slot-mcp/1.0"}

    def forecast(self, lat: float, lon: float, units: str = "si") -> Tuple[bool, Dict[str, Any], str]:
        url = f"{self.base_url}/forecast/{self.api_key}/{lat},{lon}?units={units}"
        ok, status, payload = request_json(url, headers=self._headers(), timeout=self.timeout)
        if not ok:
            return False, {}, f"HTTP {status}: {str(payload)[:200]}"
        if isinstance(payload, str):
            # 网关把请求当成页面访问（返回门户 HTML），说明该接口未开通或路径已变
            hint = "网关返回门户页面（非 JSON），weather 接口在当前网关不可调用"
            return False, {}, hint
        if not isinstance(payload, dict):
            return False, {}, f"返回类型异常: {type(payload).__name__}"
        return True, payload, ""

    def summarize(self, lat: float, lon: float) -> Dict[str, Any]:
        ok, data, detail = self.forecast(lat, lon)
        if not ok:
            return {"ok": False, "detail": detail, "lat": lat, "lon": lon}
        current = data.get("currently") or {}
        return {
            "ok": True,
            "lat": lat,
            "lon": lon,
            "summary": current.get("summary", ""),
            "temperature": current.get("temperature"),
            "detail": "",
        }
