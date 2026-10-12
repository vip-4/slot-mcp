"""AgentMail 客户端：部署报告 / 健康告警邮件。

API 形态（已实测）：
    GET  https://api.agentmail.to/inboxes
    POST https://api.agentmail.to/inboxes/{inbox_id}/messages/send
         body: {"to": [...], "subject": "...", "text": "...", "html": "..."}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .http import request_json

BASE_URL = "https://api.agentmail.to"


class AgentMailClient:
    def __init__(self, api_key: str, inbox: str, base_url: str = BASE_URL, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.inbox = inbox
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def list_inboxes(self) -> Tuple[bool, int, Any]:
        return request_json(f"{self.base_url}/inboxes", headers=self._headers(), timeout=self.timeout)

    def send(
        self,
        to: Sequence[str],
        subject: str,
        text: str,
        html: Optional[str] = None,
        inbox: Optional[str] = None,
    ) -> Tuple[bool, int, Any]:
        target = inbox or self.inbox
        payload: Dict[str, Any] = {
            "to": list(to),
            "subject": subject,
            "text": text,
        }
        if html:
            payload["html"] = html
        return request_json(
            f"{self.base_url}/inboxes/{target}/messages/send",
            method="POST",
            headers=self._headers(),
            body=payload,
            timeout=self.timeout,
        )

    @staticmethod
    def render_report(
        *,
        site_url: str,
        pages: int,
        games: List[str],
        checks: List[Dict[str, Any]],
        cron: List[Dict[str, Any]],
        playcanvas: Dict[str, Any],
        geo: Optional[Dict[str, Any]] = None,
    ) -> str:
        """把部署结果渲染为纯文本报告（邮件正文与控制台共用）。"""
        lines = [
            "SLOT 静态站部署报告",
            "=" * 46,
            f"站点地址: {site_url}",
            f"页面数量: {pages}",
            f"机台数量: {len(games)}（{'、'.join(games)}）",
            "",
            "【健康检查】",
        ]
        if not checks:
            lines.append("  （未执行）")
        for c in checks:
            flag = "OK " if c.get("ok") else "NG "
            lines.append(f"  [{flag}] {c['url']} -> {c['status']} ({c['seconds']}s)")
        lines += ["", "【定时任务】"]
        if not cron:
            lines.append("  （未执行）")
        for j in cron:
            state = j.get("state", "")
            lines.append(f"  [{state}] {j.get('title','')} -> {j.get('url','')} ({j.get('schedule','')})")
        lines += ["", "【PlayCanvas 三维项目】"]
        if not playcanvas:
            lines.append("  （未执行）")
        else:
            lines.append(f"  项目: {playcanvas.get('project', '')}")
            lines.append(f"  场景: {playcanvas.get('scenes', 0)} 个，资产: {playcanvas.get('assets', 0)} 个")
            if playcanvas.get("error"):
                lines.append(f"  提示: {playcanvas['error']}")
        if geo:
            lines += [
                "",
                "【GEO 监测（Metaso AI 搜索）】",
                f"  检索词: {geo.get('query', '')}",
                f"  本站是否被收录: {'是' if geo.get('indexed') else '否'}（命中 {geo.get('matched', 0)}/{geo.get('total', 0)} 条）",
            ]
            if geo.get("summary"):
                lines.append(f"  AI 摘要: {geo['summary']}")
            for hit in (geo.get("hits") or [])[:3]:
                mark = "*" if hit.get("own") else " "
                lines.append(f"   [{mark}] {hit.get('title','')[:40]} - {hit.get('link','')}")
            if geo.get("error"):
                lines.append(f"  提示: {geo['error']}")
        lines += ["", "-- 本邮件由 slotmcp 部署流水线自动发送"]
        return "\n".join(lines)
