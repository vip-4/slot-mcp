"""命令行工具：RTP 回归验证等。"""

from __future__ import annotations

__all__ = ["verify_rtp_main"]


def verify_rtp_main(argv: list | None = None) -> int:
    """延迟导入，避免 `python -m slotmcp.tools.verify_rtp` 触发 runpy 的重名警告。"""
    from .verify_rtp import main

    return main(argv)
