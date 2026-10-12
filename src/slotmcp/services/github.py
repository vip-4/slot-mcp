"""GitHub 客户端：创建仓库 + 开启 Pages。

    GET  /user                                  鉴权与账号名
    POST /user/repos                            创建仓库
    GET  /repos/{owner}/{repo}/pages            读取 Pages 状态
    POST /repos/{owner}/{repo}/pages            开启 Pages（branch + path）
    GET  /repos/{owner}/{repo}/pages/builds     构建状态

仓库内容推送由 `git` 完成（tools/deploy_pages.py 调用），本模块只负责 API 侧。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from .http import request_json

BASE_URL = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str, timeout: float = 30.0, base_url: str = BASE_URL) -> None:
        self.token = token
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "slot-mcp/1.0",
        }

    def _call(
        self,
        path: str,
        method: str = "GET",
        body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, int, Any]:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        return request_json(
            url, method=method, headers=self._headers(), body=body, timeout=self.timeout
        )

    def whoami(self) -> Tuple[bool, int, Any]:
        return self._call("/user")

    def login(self) -> str:
        ok, _, payload = self.whoami()
        return payload.get("login", "") if ok and isinstance(payload, dict) else ""

    def get_repo(self, full_name: str) -> Optional[Dict[str, Any]]:
        ok, status, payload = self._call(f"/repos/{full_name}")
        if ok and isinstance(payload, dict):
            return payload
        if status == 404:
            return None
        return None

    def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        homepage: str = "",
    ) -> Tuple[bool, int, Any]:
        body: Dict[str, Any] = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": False,
            "has_issues": True,
        }
        if homepage:
            body["homepage"] = homepage
        return self._call("/user/repos", method="POST", body=body)

    def ensure_repo(self, name: str, **kwargs: Any) -> Tuple[Optional[Dict[str, Any]], str]:
        owner = self.login()
        if not owner:
            return None, "failed:无法读取账号（Token 无效或缺少权限）"
        full = f"{owner}/{name}"
        existing = self.get_repo(full)
        if existing:
            return existing, "exists"
        ok, status, payload = self.create_repo(name, **kwargs)
        if ok and isinstance(payload, dict):
            return payload, "created"
        return None, f"failed:{status} {json.dumps(payload, ensure_ascii=False)[:200]}"

    def get_pages(self, full_name: str) -> Tuple[bool, int, Any]:
        return self._call(f"/repos/{full_name}/pages")

    def enable_pages(self, full_name: str, branch: str = "main", path: str = "/") -> Tuple[bool, int, Any]:
        return self._call(
            f"/repos/{full_name}/pages",
            method="POST",
            body={"build_type": "legacy", "source": {"branch": branch, "path": path}},
        )

    def latest_build(self, full_name: str) -> Tuple[bool, int, Any]:
        return self._call(f"/repos/{full_name}/pages/builds?per_page=1")

    @staticmethod
    def pages_url(owner: str, repo: str) -> str:
        return f"https://{owner.lower()}.github.io/{repo}/"
