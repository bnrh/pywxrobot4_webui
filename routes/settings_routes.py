"""系统设置与日志查询 API 路由。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time

from fastapi import FastAPI
from loguru import logger

from server.builders import AppBuilders
from server.app_config import LOG_DIR
from server.schemas import SystemSettingsUpdateRequest
from core.config import PROJECT_ROOT
from core.config import PluginServiceSettings
from server.log_reader import build_log_payload as build_service_log_payload
from runtime.sync import sync_runtime_with_config
from server.context import AppContext

# 重启后短暂绕过静态文件缓存的时间窗口（秒）
_cache_bust_until = 0.0
_CACHE_BUST_FILE = PROJECT_ROOT / ".cache_bust_until"
_CACHE_BUST_DURATION = 90


def is_cache_bust_active() -> bool:
    return time.time() < _cache_bust_until


def load_cache_bust_state() -> None:
    global _cache_bust_until
    try:
        if _CACHE_BUST_FILE.is_file():
            raw = _CACHE_BUST_FILE.read_text(encoding="utf-8").strip()
            _cache_bust_until = float(raw) if raw else 0.0
            _CACHE_BUST_FILE.unlink(missing_ok=True)
    except Exception:
        _cache_bust_until = 0.0


load_cache_bust_state()


def register_settings_routes(app: FastAPI, ctx: AppContext) -> None:
    @app.get("/api/settings")
    async def get_settings() -> dict:
        return ctx.builders.build_settings_payload()

    @app.post("/api/settings")
    async def update_settings(item: SystemSettingsUpdateRequest) -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        secret_updates = AppBuilders.merge_secret_settings_updates(
            configured_settings,
            {
                "api_token": item.api_token,
                "callback_secret": item.callback_secret,
            },
        )
        next_settings = configured_settings.model_copy(
            update={
                "host": item.host,
                "port": item.port,
                "callback_path": item.callback_path,
                "wxrobot_api_base_url": item.api_base_url,
                "request_timeout": item.request_timeout,
                "worker_count": item.worker_count,
                "queue_size": item.queue_size,
                "queue_enqueue_wait_seconds": item.queue_enqueue_wait_seconds,
                "heartbeat_interval_seconds": item.heartbeat_interval_seconds,
                "api_token": secret_updates["api_token"],
                "callback_secret": secret_updates["callback_secret"],
            }
        )
        next_settings.save_to_storage()
        reload_state = await sync_runtime_with_config(ctx.runtime, next_settings)
        return ctx.with_mutation_payload(reload_state)

    @app.post("/api/system/restart")
    async def restart_system() -> dict:
        global _cache_bust_until
        _cache_bust_until = time.time() + _CACHE_BUST_DURATION
        try:
            _CACHE_BUST_FILE.write_text(str(_cache_bust_until), encoding="utf-8")
        except Exception:
            logger.exception("写入 cache bust 标记失败")

        async def _restart_after_delay():
            await asyncio.sleep(1.5)
            logger.info("正在重启服务进程...")
            cmd = [sys.executable, "main.py"]
            cwd = str(PROJECT_ROOT)
            logger.info(f"重启命令: {' '.join(cmd)}, 工作目录: {cwd}")
            try:
                if os.name == "nt":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    proc = subprocess.Popen(
                        cmd,
                        cwd=cwd,
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    )
                    logger.info(f"新进程已启动，PID: {proc.pid}")
                else:
                    proc = subprocess.Popen(
                        cmd,
                        cwd=cwd,
                        start_new_session=True,
                    )
                    logger.info(f"新进程已启动，PID: {proc.pid}")
            except Exception:
                logger.exception("启动新进程失败")
            logger.info("退出当前进程...")
            os._exit(0)

        asyncio.create_task(_restart_after_delay())
        return {"message": "服务正在重启..."}

    @app.get("/api/logs")
    async def get_logs(
        file_name: str | None = None,
        limit: int = 200,
        time_range: str = "all",
        level: str = "",
        module_query: str = "",
        keyword: str = "",
    ) -> dict:
        return build_service_log_payload(
            LOG_DIR,
            file_name=file_name,
            limit=limit,
            time_range=time_range,
            level=level,
            module_query=module_query,
            keyword=keyword,
        )

    @app.get("/api/plugin-logs")
    async def get_plugin_logs(module_name: str | None = None, level: str = "", keyword: str = "", limit: int = 200) -> dict:
        return ctx.builders.build_plugin_log_payload(module_name, level, keyword, limit)
