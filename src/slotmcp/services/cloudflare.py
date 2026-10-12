"""Cloudflare Pages 客户端：直传（Direct Upload）部署静态站。

    POST /accounts/{id}/pages/projects                         创建项目
    GET  /accounts/{id}/pages/projects/{name}                   读取项目
    POST /accounts/{id}/pages/projects/{name}/deployments       直传部署（multipart 表单）

直传不需要 Git 集成，也不需要 wrangler：把 `static/` 全部文件一次打包上传即可，
产物地址为 `https://<project>.pages.dev`。

R2 说明：本环境到 `*.r2.cloudflarestorage.com` 的 TLS 握手失败（Python 与 WinHTTP 均失败），
且给出的 cfat token 不带 R2 权限（`/r2/buckets` 返回 403），因此托管走 Pages、
R2 仅作为可选的对象存储镜像（不可用时自动跳过，不影响部署）。
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .http import request_json, request_raw

BASE_URL = "https://api.cloudflare.com/client/v4"


def collect_files(root: Path) -> Dict[str, bytes]:
    """收集目录下所有文件，返回 `{相对路径(posix): 字节内容}`。"""
    files: Dict[str, bytes] = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            files[rel] = path.read_bytes()
    return files


def build_manifest(files: Iterable[str]) -> Dict[str, str]:
    """`/相对路径 -> 内容哈希`，哈希同时作为 multipart 字段名。"""
    return {"/" + f: hashlib.sha1(f.encode("utf-8")).hexdigest() for f in files}


def _content_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return (
        guessed
        or {
            ".webmanifest": "application/manifest+json",
            ".txt": "text/plain; charset=utf-8",
        }.get(os.path.splitext(path)[1], "application/octet-stream")
    )


def build_multipart(files: Dict[str, bytes], manifest: Dict[str, str]) -> Tuple[str, bytes]:
    """构造直传用的 multipart/form-data：`manifest` + 每个文件以哈希为字段名。"""
    boundary = f"----slotmcp{uuid.uuid4().hex}"
    chunks: List[bytes] = []

    def field(name: str, filename: Optional[str], content_type: str, payload: bytes) -> None:
        head = f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\""
        if filename:
            head += f"; filename=\"{filename}\""
        head += f"\r\nContent-Type: {content_type}\r\n\r\n"
        chunks.append(head.encode("utf-8"))
        chunks.append(payload)
        chunks.append(b"\r\n")

    field("manifest", "manifest.json", "application/json", json.dumps(manifest).encode("utf-8"))
    by_hash = {v: k for k, v in manifest.items()}
    for digest, route in by_hash.items():
        rel = route.lstrip("/")
        field(digest, rel, _content_type(rel), files[rel])
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


class CloudflareClient:
    def __init__(
        self,
        token: str,
        account_id: str,
        timeout: float = 120.0,
        base_url: str = BASE_URL,
    ) -> None:
        self.token = token
        self.account_id = account_id
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "User-Agent": "slot-mcp/1.0"}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/accounts/{self.account_id}{path}"

    def _call(
        self,
        path: str,
        method: str = "GET",
        body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, int, Any]:
        ok, status, payload = request_json(
            self._url(path),
            method=method,
            headers=self._headers(),
            body=body,
            timeout=self.timeout,
        )
        if ok and isinstance(payload, dict) and payload.get("success") is False:
            return False, status, payload.get("errors") or payload
        return ok, status, payload

    def list_projects(self) -> Tuple[bool, int, List[Dict[str, Any]]]:
        ok, status, payload = self._call("/pages/projects")
        if not ok or not isinstance(payload, dict):
            return ok, status, []
        return True, status, payload.get("result") or []

    def get_project(self, name: str) -> Optional[Dict[str, Any]]:
        ok, status, payload = self._call(f"/pages/projects/{name}")
        if ok and isinstance(payload, dict):
            return payload.get("result")
        return None

    def create_project(self, name: str, production_branch: str = "main") -> Tuple[bool, int, Any]:
        return self._call(
            "/pages/projects",
            method="POST",
            body={"name": name, "production_branch": production_branch},
        )

    def ensure_project(self, name: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """存在则直接返回，不存在则创建；返回 `(project, 'exists'|'created'|'failed:<原因>')`。"""
        existing = self.get_project(name)
        if existing:
            return existing, "exists"
        ok, status, payload = self.create_project(name)
        if ok and isinstance(payload, dict):
            return payload.get("result"), "created"
        return None, f"failed:{status} {json.dumps(payload, ensure_ascii=False)[:200]}"

    def deploy(self, name: str, files: Dict[str, bytes]) -> Tuple[bool, int, Any]:
        manifest = build_manifest(files.keys())
        content_type, body = build_multipart(files, manifest)
        headers = dict(self._headers())
        headers["Content-Type"] = content_type
        return request_raw(
            self._url(f"/pages/projects/{name}/deployments"),
            method="POST",
            headers=headers,
            data=body,
            timeout=self.timeout,
        )

    def latest_deployment(self, name: str) -> Optional[Dict[str, Any]]:
        ok, status, payload = self._call(f"/pages/projects/{name}/deployments?per_page=1")
        if ok and isinstance(payload, dict):
            rows = payload.get("result") or []
            return rows[0] if rows else None
        return None

    @staticmethod
    def project_url(project: Dict[str, Any]) -> str:
        subdomain = project.get("subdomain")
        if subdomain:
            return f"https://{subdomain}"
        return f"https://{project.get('name', '')}.pages.dev"
