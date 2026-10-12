"""PlayCanvas 客户端：读取三维项目清单，并把机台配置导出为场景描述。

已实测（token 作用域有限，按需降级）：
    GET https://playcanvas.com/api/projects/{id}          -> 403（缺 project 作用域）
    GET https://playcanvas.com/api/projects/{id}/scenes   -> 200 {"result": [...]}
    GET https://playcanvas.com/api/projects/{id}/assets   -> 200 {"result": [...]}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .http import request_json

BASE_URL = "https://playcanvas.com/api"


class PlayCanvasClient:
    def __init__(self, token: str, base_url: str = BASE_URL, timeout: float = 20.0) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def project(self, project_id: int) -> Tuple[bool, int, Any]:
        return request_json(
            f"{self.base_url}/projects/{project_id}", headers=self._headers(), timeout=self.timeout
        )

    def list_scenes(self, project_id: int) -> Tuple[bool, int, Any]:
        ok, status, payload = request_json(
            f"{self.base_url}/projects/{project_id}/scenes", headers=self._headers(), timeout=self.timeout
        )
        if not ok:
            return ok, status, payload
        return True, status, payload.get("result", []) if isinstance(payload, dict) else payload

    def list_assets(self, project_id: int) -> Tuple[bool, int, Any]:
        ok, status, payload = request_json(
            f"{self.base_url}/projects/{project_id}/assets", headers=self._headers(), timeout=self.timeout
        )
        if not ok:
            return ok, status, payload
        return True, status, payload.get("result", []) if isinstance(payload, dict) else payload

    def summary(self, project_id: int) -> Dict[str, Any]:
        """汇总项目状态；权限不足时降级但不抛异常。"""
        out: Dict[str, Any] = {"project": str(project_id), "scenes": 0, "assets": 0, "error": ""}
        ok, _, data = self.list_scenes(project_id)
        if ok and isinstance(data, list):
            out["scenes"] = len(data)
            out["scene_names"] = [s.get("name", "") for s in data]
        else:
            out["error"] = f"场景读取失败: {data}"
            return out
        ok, _, data = self.list_assets(project_id)
        if ok and isinstance(data, list):
            out["assets"] = len(data)
            kinds: Dict[str, int] = {}
            for a in data:
                kinds[a.get("type", "unknown")] = kinds.get(a.get("type", "unknown"), 0) + 1
            out["asset_types"] = kinds
        else:
            out["error"] = f"{out['error']}；资产读取失败: {data}".strip("；")
        return out


def build_scene_descriptor(
    *,
    project_id: int,
    games: List[Dict[str, Any]],
    scene_name: str = "Main Scene",
) -> Dict[str, Any]:
    """由机台配置生成 PlayCanvas/Blender 侧可消费的场景描述（同一份 CONFIG 驱动）。"""
    machines = []
    for cfg in games:
        symbols = []
        for sid, sym in (cfg.get("symbols") or {}).items():
            symbols.append(
                {
                    "id": sid,
                    "name": sym.get("name", sid),
                    "kind": sym.get("kind", "standard"),
                    "color": sym.get("color", "#ffffff"),
                    "glyph": sym.get("glyph", "?"),
                }
            )
        machines.append(
            {
                "id": cfg.get("id"),
                "name": cfg.get("name"),
                "reels": cfg.get("reels"),
                "rows": cfg.get("rows"),
                "pay_mode": cfg.get("pay_mode"),
                "theme": cfg.get("theme", {}),
                "symbols": symbols,
                "features": sorted((cfg.get("features") or {}).keys()),
            }
        )
    return {
        "schema": "slotmcp.scene/1",
        "project_id": project_id,
        "scene": scene_name,
        "animation": {
            "spin_ms": 420,
            "cascade_ms": 340,
            "hold_win_ms": 620,
            "stop_stagger_ms": 90,
            "easing": "easeOutCubic",
        },
        "machines": machines,
    }


def write_scene_descriptor(descriptor: Dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(descriptor, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
