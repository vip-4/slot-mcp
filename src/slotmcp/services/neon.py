"""Neon Postgres 客户端：通过 HTTP SQL 端点执行语句（零驱动、零第三方依赖）。

Neon 的无服务器驱动协议：
    POST https://<pooler-host>/sql
    Headers: Neon-Connection-String: <postgres://...>
    Body:    {"query": "select 1"}

本站是纯静态站，运行时不访问数据库；数据库只用于**构建期与运维期**：
部署审计、RTP 回归记录、社区统计快照（快照以静态 JSON 注入页面，保证站点仍零运行时依赖）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .http import request_json

SCHEMA_STATEMENTS: List[str] = [
    """
    create table if not exists slot_deploy_log (
        id bigserial primary key,
        site_url text not null,
        checks jsonb not null default '[]'::jsonb,
        ok boolean not null,
        detail text not null default '',
        created_at timestamptz not null default now()
    )
    """,
    """
    create table if not exists slot_rtp_runs (
        id bigserial primary key,
        game_id text not null,
        spins integer not null check (spins > 0),
        rtp numeric(8,5) not null,
        hit_rate numeric(8,5) not null,
        source text not null default 'python',
        created_at timestamptz not null default now()
    )
    """,
    """
    create table if not exists slot_scores (
        id bigserial primary key,
        game_id text not null check (char_length(game_id) <= 40),
        player text not null check (char_length(player) between 1 and 16),
        best_multiplier numeric(12,2) not null check (best_multiplier >= 0 and best_multiplier <= 100000),
        created_at timestamptz not null default now()
    )
    """,
    "create index if not exists idx_slot_scores_best on slot_scores (game_id, best_multiplier desc)",
    "create index if not exists idx_slot_rtp_game on slot_rtp_runs (game_id, created_at desc)",
]


class NeonClient:
    def __init__(
        self,
        connection_string: str,
        timeout: float = 30.0,
        base_url: Optional[str] = None,
    ) -> None:
        self.connection_string = connection_string
        self.timeout = timeout
        self.base_url = base_url or self._sql_url(connection_string)

    @staticmethod
    def _sql_url(connection_string: str) -> str:
        host = connection_string.split("@")[-1].split("/")[0]
        return f"https://{host}/sql"

    def sql(self, query: str) -> Tuple[bool, Any, str]:
        """执行一条语句，返回 `(ok, rows, error)`。"""
        ok, status, payload = request_json(
            self.base_url,
            method="POST",
            headers={
                "Neon-Connection-String": self.connection_string,
                "Neon-Raw-Text": "true",
            },
            body={"query": query},
            timeout=self.timeout,
            retries=1,
        )
        if not ok:
            return False, None, f"HTTP {status}: {payload}"
        if isinstance(payload, dict) and payload.get("message") and "rows" not in payload:
            return False, None, str(payload.get("message"))[:200]
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        return True, rows, ""

    def execute(self, query: str) -> Tuple[bool, str]:
        ok, _, err = self.sql(query)
        return ok, err

    def ensure_schema(self, statements: Optional[List[str]] = None) -> List[Tuple[str, bool, str]]:
        results = []
        for stmt in statements or SCHEMA_STATEMENTS:
            ok, err = self.execute(stmt)
            label = " ".join(stmt.split())[:48]
            results.append((label, ok, err))
        return results

    def insert(self, table: str, row: Dict[str, Any]) -> Tuple[bool, str]:
        cols = ", ".join(row.keys())
        vals = ", ".join(self._literal(v) for v in row.values())
        return self.execute(f"insert into {table} ({cols}) values ({vals})")

    def select(self, query: str) -> Tuple[bool, List[Dict[str, Any]], str]:
        return self.sql(query)

    @staticmethod
    def _literal(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).replace("'", "''")
        return f"'{text}'"
