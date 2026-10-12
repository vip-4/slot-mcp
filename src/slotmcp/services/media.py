"""图片素材客户端：Pexels / Pixabay。

用途：为每款机台抓取主题配图（页面主图 + Open Graph 图 + 列表缩略图），
输出可追溯的素材清单 `deploy/media.json` 与署名文件 `static/assets/img/CREDITS.md`。

要点
----
* Pexels 的 CDN 支持 imgix 参数，可直接请求裁剪尺寸：
  `?auto=compress&cs=tinysrgb&fit=crop&w=1200&h=630`，避免本地再处理（保持零依赖）。
* 两个服务都要求带浏览器 UA，否则 Cloudflare 返回 1010。
* 任一服务失败自动回退到另一个；都失败则保留程序生成的 PNG 占位图。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

PEXELS_LICENSE = "Pexels License（可免费商用，无需署名但建议署名）"
PIXABAY_LICENSE = "Pixabay Content License（可免费商用）"

# 每款机台的检索词与中文替代文本（alt 直接影响图片可访问性与 SEO）
THEME_QUERIES: Dict[str, Dict[str, str]] = {
    "lucky_fruits": {
        "pexels": "fruit slot machine cherries",
        "pixabay": "fruit cherries",
        "alt": "幸运水果机台主题图：鲜艳的樱桃与水果特写",
    },
    "candy_carnival": {
        "pexels": "colorful candy sweets",
        "pixabay": "candy sweets",
        "alt": "糖果狂欢机台主题图：彩色糖果与甜点",
    },
    "dragon_palace": {
        "pexels": "chinese lantern palace temple",
        "pixabay": "chinese dragon lantern",
        "alt": "龙宫探宝机台主题图：东方宫殿灯笼与龙纹装饰",
    },
    "pharaoh_tomb": {
        "pexels": "egypt pyramid pharaoh tomb",
        "pixabay": "egypt pharaoh pyramid",
        "alt": "法老之墓机台主题图：古埃及金字塔与法老雕像",
    },
    "star_expedition": {
        "pexels": "galaxy stars spaceship night sky",
        "pixabay": "galaxy stars space",
        "alt": "星际远征机台主题图：星系与深空星云",
    },
    "fortune_koi": {
        "pexels": "koi fish pond lotus water",
        "pixabay": "koi pond lotus",
        "alt": "锦鲤纳福机台主题图：锦鲤池塘与莲花",
    },
}

HERO_SIZE = (960, 540)
OG_SIZE = (1200, 630)
THUMB_SIZE = (480, 270)


def _get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 25.0) -> Tuple[bool, int, Any]:
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            try:
                return True, resp.status, json.loads(raw)
            except ValueError:
                return True, resp.status, raw
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore").strip()
        return False, exc.code, f"HTTP {exc.code}: {detail[:200]}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, 0, f"网络错误: {exc}"


def download(url: str, dest: Path, timeout: float = 60.0) -> Tuple[bool, int]:
    """下载二进制到指定路径，返回 `(成功, 字节数)`。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return False, 0
    if not data:
        return False, 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True, len(data)


class PexelsClient:
    BASE = "https://api.pexels.com/v1"

    def __init__(self, api_key: str, base_url: str = BASE, timeout: float = 25.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def search(self, query: str, per_page: int = 8, orientation: str = "landscape") -> Tuple[bool, int, Any]:
        url = (
            f"{self.base_url}/search?query={urllib.parse.quote(query)}"
            f"&per_page={per_page}&orientation={orientation}"
        )
        ok, status, payload = _get_json(url, {"Authorization": self.api_key}, self.timeout)
        if not ok:
            return ok, status, payload
        photos = payload.get("photos", []) if isinstance(payload, dict) else []
        return True, status, [self.normalize(p) for p in photos]

    @staticmethod
    def normalize(photo: Dict[str, Any]) -> Dict[str, Any]:
        src = photo.get("src", {})
        original = src.get("original") or src.get("large2x") or src.get("large") or ""
        return {
            "provider": "pexels",
            "id": str(photo.get("id", "")),
            "page_url": photo.get("url", ""),
            "author": photo.get("photographer", ""),
            "author_url": photo.get("photographer_url", ""),
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "avg_color": photo.get("avg_color", ""),
            "raw": original,
            "license": PEXELS_LICENSE,
        }

    @staticmethod
    def crop(url: str, width: int, height: int) -> str:
        return f"{url}?auto=compress&cs=tinysrgb&fit=crop&w={width}&h={height}"


class PixabayClient:
    BASE = "https://pixabay.com/api/"

    def __init__(self, api_key: str, base_url: str = BASE, timeout: float = 25.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def search(self, query: str, per_page: int = 10, image_type: str = "photo") -> Tuple[bool, int, Any]:
        # Pixabay 的 per_page 合法区间为 3–200
        per_page = max(3, min(200, per_page))
        url = (
            f"{self.base_url}?key={urllib.parse.quote(self.api_key)}"
            f"&q={urllib.parse.quote(query)}&image_type={image_type}&per_page={per_page}&safesearch=true"
        )
        ok, status, payload = _get_json(url, timeout=self.timeout)
        if not ok:
            return ok, status, payload
        hits = payload.get("hits", []) if isinstance(payload, dict) else []
        return True, status, [self.normalize(h) for h in hits]

    @staticmethod
    def normalize(hit: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": "pixabay",
            "id": str(hit.get("id", "")),
            "page_url": hit.get("pageURL", ""),
            "author": hit.get("user", ""),
            "author_url": f"https://pixabay.com/users/{hit.get('user_id', '')}" if hit.get("user_id") else "",
            "width": hit.get("imageWidth", 0),
            "height": hit.get("imageHeight", 0),
            "avg_color": hit.get("avg_color", "") or "",
            "raw": hit.get("largeImageURL") or hit.get("webformatURL") or "",
            "tags": hit.get("tags", ""),
            "license": PIXABAY_LICENSE,
        }

    @staticmethod
    def crop(url: str, width: int, height: int) -> str:
        # Pixabay CDN 不支持 imgix 裁剪，直接返回原尺寸
        return url


def fetch_theme_image(
    game_id: str,
    *,
    pexels: Optional[PexelsClient],
    pixabay: Optional[PixabayClient],
    out_dir: Path,
    variants: Tuple[Tuple[str, Tuple[int, int]], ...] = (("hero", HERO_SIZE), ("og", OG_SIZE)),
) -> Optional[Dict[str, Any]]:
    """为单个机台抓取主题图并落盘，返回素材条目；失败返回 None。"""
    theme = THEME_QUERIES.get(game_id)
    if not theme:
        return None

    candidates: List[Tuple[Any, Dict[str, Any]]] = []
    for client, query, provider in (
        (pexels, theme.get("pexels", ""), "pexels"),
        (pixabay, theme.get("pixabay", ""), "pixabay"),
    ):
        if not client or not query:
            continue
        ok, _, results = client.search(query, per_page=8)
        if ok:
            for item in results:
                candidates.append((client, item))
        if candidates:
            break

    if not candidates:
        return None

    client, item = candidates[0]
    entry: Dict[str, Any] = {
        "game": game_id,
        "alt": theme.get("alt", ""),
        "provider": item["provider"],
        "page_url": item["page_url"],
        "author": item["author"],
        "author_url": item["author_url"],
        "license": item["license"],
        "files": {},
    }
    for name, (width, height) in variants:
        url = client.crop(item["raw"], width, height)
        dest = out_dir / f"{game_id}-{name}.jpg"
        ok, size = download(url, dest)
        if not ok:
            continue
        entry["files"][name] = {
            "path": str(dest.name),
            "width": width,
            "height": height,
            "bytes": size,
            "source": url,
        }
    return entry if entry["files"] else None
