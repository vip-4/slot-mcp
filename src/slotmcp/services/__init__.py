"""外部服务客户端：邮件通知、定时任务巡检、PlayCanvas 三维项目。

设计约定
--------
* **零第三方依赖**：只用标准库 `urllib`，与项目其余部分一致。
* **凭证只从环境变量或本地配置文件读取**，绝不写进仓库（`deploy/services.local.json` 已 gitignore）。
* **失败可降级**：任何外部调用失败都返回结构化结果 `(ok, data, error)`，
  调用方据此决定是否告警，而不是让部署流程直接崩溃。
"""

from .agentmail import AgentMailClient
from .cronjob import CronJobClient
from .http import request_json
from .playcanvas import PlayCanvasClient

__all__ = [
    "AgentMailClient",
    "CronJobClient",
    "PlayCanvasClient",
    "request_json",
]
