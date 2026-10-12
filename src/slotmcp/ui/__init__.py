"""Web UI 层：标准库 HTTP 服务 + REST API。"""

from .http_api import SlotHTTPServer, UiState, main

__all__ = ["SlotHTTPServer", "UiState", "main"]
