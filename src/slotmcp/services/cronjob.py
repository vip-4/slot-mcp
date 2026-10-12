"""cron-job.org 客户端：站点可用性巡检任务（支持按标题幂等 upsert）。

API 形态（已实测，注意创建用 PUT 而非 POST）：
    GET    https://api.cron-job.org/jobs
    PUT    https://api.cron-job.org/jobs          body: {"job": {...}}   -> {"jobId": ...}
    PATCH  https://api.cron-job.org/jobs/{id}     body: {"job": {...}}
    DELETE https://api.cron-job.org/jobs/{id}

schedule 结构：
    {"timezone": "UTC", "hours": [-1], "mdays": [-1], "minutes": [0, 30],
     "months": [-1], "wdays": [-1], "expiresAt": 0}
    -1 表示「任意」。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .http import request_json

BASE_URL = "https://api.cron-job.org"


def every_n_minutes(n: int, timezone: str = "UTC") -> Dict[str, Any]:
    """把「每 n 分钟」翻译成 cron-job.org 的 schedule（-1 表示任意）。"""
    if n <= 0:
        raise ValueError("间隔分钟数必须为正")
    if n < 60:
        if 60 % n != 0:
            raise ValueError("小于 60 分钟时必须是 60 的约数（1/2/3/5/10/15/20/30）")
        minutes = list(range(0, 60, n))
        hours = [-1]
    elif n < 1440:
        if 1440 % n != 0:
            raise ValueError("小时级间隔必须能整除 24 小时")
        minutes = [0]
        hours = list(range(0, 24, n // 60))
    else:
        minutes = [0]
        hours = [0]
    return {
        "timezone": timezone,
        "hours": hours,
        "mdays": [-1],
        "minutes": minutes,
        "months": [-1],
        "wdays": [-1],
        "expiresAt": 0,
    }


class CronJobClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def list_jobs(self) -> Tuple[bool, int, Any]:
        ok, status, payload = request_json(
            f"{self.base_url}/jobs", headers=self._headers(), timeout=self.timeout
        )
        if not ok:
            return ok, status, payload
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
        return True, status, jobs

    def find_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        ok, _, jobs = self.list_jobs()
        if not ok or not isinstance(jobs, list):
            return None
        for job in jobs:
            if job.get("title") == title:
                return job
        return None

    def create_job(self, job: Dict[str, Any]) -> Tuple[bool, int, Any]:
        # 实测：创建用 PUT /jobs（POST 会返回 404）
        return request_json(
            f"{self.base_url}/jobs",
            method="PUT",
            headers=self._headers(),
            body={"job": job},
            timeout=self.timeout,
        )

    def delete_job(self, job_id: int) -> Tuple[bool, int, Any]:
        return request_json(
            f"{self.base_url}/jobs/{job_id}", method="DELETE", headers=self._headers(), timeout=self.timeout
        )

    def update_job(self, job_id: int, patch: Dict[str, Any]) -> Tuple[bool, int, Any]:
        return request_json(
            f"{self.base_url}/jobs/{job_id}",
            method="PATCH",
            headers=self._headers(),
            body={"job": patch},
            timeout=self.timeout,
        )

    def upsert(
        self,
        *,
        title: str,
        url: str,
        schedule: Dict[str, Any],
        enabled: bool = True,
        save_responses: bool = True,
        request_method: int = 0,
        request_timeout: int = 30,
    ) -> Dict[str, Any]:
        """按标题幂等创建或更新，返回结构化结果。"""
        job = {
            "title": title,
            "url": url,
            "enabled": enabled,
            "saveResponses": save_responses,
            "schedule": schedule,
            "requestMethod": request_method,
            "requestTimeout": request_timeout,
        }
        existing = self.find_by_title(title)
        if existing is None:
            ok, status, payload = self.create_job(job)
            job_id = (payload or {}).get("jobId") if isinstance(payload, dict) else None
            return {"state": "created" if ok else "failed", "jobId": job_id, "status": status, "detail": payload if not ok else ""}
        patch = {k: v for k, v in job.items() if k != "title"}
        ok, status, payload = self.update_job(existing["jobId"], patch)
        return {
            "state": "updated" if ok else "failed",
            "jobId": existing["jobId"],
            "status": status,
            "detail": payload if not ok else "",
        }
