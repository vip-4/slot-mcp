"""极简 JSON HTTP 客户端（标准库实现，带重试与结构化错误）。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

DEFAULT_TIMEOUT = 15.0


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
    backoff: float = 0.6,
) -> Tuple[bool, int, Any]:
    """返回 `(ok, status, payload_or_error)`。

    * 2xx：`ok=True`，`payload` 为解析后的 JSON（解析失败则返回原始文本）
    * 4xx：直接返回 `ok=False`（重试无意义）
    * 5xx / 网络错误：指数退避重试 `retries` 次后返回 `ok=False`
    """
    data: Optional[bytes] = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    hdrs.setdefault("Accept", "application/json")

    last_error = "未知错误"
    last_status = 0
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "ignore")
                try:
                    payload = json.loads(raw) if raw.strip() else {}
                except ValueError:
                    payload = raw
                return True, resp.status, payload
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            detail = exc.read().decode("utf-8", "ignore").strip()
            last_error = f"HTTP {exc.code}: {detail[:300] or exc.reason}"
            if exc.code < 500:  # 4xx 重试无意义
                return False, exc.code, last_error
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_status = 0
            last_error = f"网络错误: {exc}"
        if attempt < retries:
            time.sleep(backoff * (2**attempt))
    return False, last_status, last_error


def head_ok(url: str, timeout: float = 10.0) -> Tuple[bool, int, float]:
    """健康检查：返回 `(是否 2xx/3xx, 状态码, 耗时秒)`。"""
    started = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "slot-mcp-healthcheck/1.0"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(2048)
            return 200 <= resp.status < 400, resp.status, round(time.time() - started, 3)
    except urllib.error.HTTPError as exc:
        return False, exc.code, round(time.time() - started, 3)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, 0, round(time.time() - started, 3)
