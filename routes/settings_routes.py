"""系统设置与日志查询 API 路由。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time

from fastapi import FastAPI, HTTPException
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


def _find_robot_process_by_exe(exe_path: str) -> list[int]:
    """查找指定可执行文件名的进程 PID（排除当前进程）。"""
    if not exe_path:
        return []

    exe_name = os.path.basename(exe_path).lower()
    current_pid = os.getpid()
    pids: list[int] = []

    try:
        if os.name == "nt":
            escaped_name = exe_name.replace("'", "''")
            ps_script = (
                "Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.Name -and $_.Name.ToLower() -eq '{escaped_name}' }} | "
                "Select-Object -ExpandProperty ProcessId"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for token in result.stdout.split():
                if token.strip().isdigit():
                    pid = int(token.strip())
                    if pid != current_pid:
                        pids.append(pid)
        else:
            exe_basename = os.path.basename(exe_path)
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if exe_basename in line:
                    parts = line.split()
                    if len(parts) > 1:
                        try:
                            pid = int(parts[1])
                            if pid != current_pid:
                                pids.append(pid)
                        except ValueError:
                            pass
    except Exception:
        logger.exception("查找机器人进程失败")

    return pids


def _is_admin() -> bool:
    """检查当前进程是否以管理员权限运行。"""
    if os.name != "nt":
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _kill_processes(pids: list[int]) -> list[int]:
    """终止指定 PID 的进程列表，返回已成功终止的 PID。

    当 webui 自身无管理员权限而目标进程是提权进程时，
    通过 PowerShell 的 Start-Process -Verb RunAs 提权调用 taskkill。
    """
    killed: list[int] = []
    if not pids:
        return killed

    if os.name == "nt":
        if _is_admin():
            # 已有管理员权限，直接 taskkill
            for pid in pids:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    killed.append(pid)
                    logger.info(f"已终止进程 PID: {pid}")
                except Exception:
                    logger.exception(f"终止进程 PID {pid} 失败")
        else:
            # 无管理员权限，用 PowerShell 提权调用 taskkill（会弹一次 UAC）
            pid_args = " ".join(f"/PID {p}" for p in pids)
            try:
                ps_cmd = (
                    f"Start-Process -FilePath taskkill "
                    f"-ArgumentList '/F {pid_args}' -Verb RunAs -Wait"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                    capture_output=True,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode == 0:
                    killed = list(pids)
                    logger.info(f"已通过提权方式终止进程 PID: {pids}")
                else:
                    logger.warning(
                        f"提权终止进程可能失败，returncode={result.returncode}, "
                        f"stdout={result.stdout}, stderr={result.stderr}"
                    )
            except Exception:
                logger.exception(f"提权终止进程失败: {pids}")
    else:
        import signal
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append(pid)
                logger.info(f"已终止进程 PID: {pid}")
            except Exception:
                logger.exception(f"终止进程 PID {pid} 失败")
    return killed


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
                "pywxrobot_dir": item.pywxrobot_dir,
                "robot_type": item.robot_type,
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

    @app.post("/api/robot/restart")
    async def restart_robot() -> dict:
        settings = PluginServiceSettings.from_storage()
        robot_dir = settings.pywxrobot_dir.strip()
        robot_type = settings.robot_type

        if not robot_dir:
            raise HTTPException(status_code=400, detail="未配置 pywxrobot 目录，请先在系统设置中填写并保存。")

        if not os.path.isdir(robot_dir):
            raise HTTPException(status_code=400, detail=f"pywxrobot 目录不存在: {robot_dir}")

        exe_name = "pywxrobot_mcp.exe" if robot_type == "pywxrobot_mcp" else "pywxrobot.exe"
        entry_exe = os.path.join(robot_dir, exe_name)
        if not os.path.isfile(entry_exe):
            raise HTTPException(status_code=400, detail=f"未找到机器人入口文件: {entry_exe}")

        # 查找并终止正在运行的机器人进程（通过进程名查找）
        pids = _find_robot_process_by_exe(entry_exe)
        killed_pids = _kill_processes(pids)
        if killed_pids:
            logger.info(f"已终止 {len(killed_pids)} 个旧机器人进程: {killed_pids}")
            await asyncio.sleep(1)

        # 启动新的机器人进程
        # exe 可能需要管理员权限，使用 ShellExecuteW 以 runas 方式启动
        logger.info(f"正在启动机器人({robot_type})，命令: {entry_exe}, 工作目录: {robot_dir}")
        try:
            if os.name == "nt":
                import ctypes

                # ShellExecuteW(hwnd, verb, file, params, dir, show_cmd)
                # 返回值 > 32 表示成功；<= 32 表示错误码
                result = ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    entry_exe,
                    "",
                    robot_dir,
                    1,  # SW_SHOWNORMAL
                )
                if result <= 32:
                    error_map = {
                        0: "内存不足",
                        2: "文件未找到",
                        3: "路径未找到",
                        5: "拒绝访问",
                        8: "无法启动",
                        26: "共享冲突",
                        27: "文件名关联不完整",
                        28: "DDE 超时",
                        29: "DDE 失败",
                        30: "DDE 忙碌",
                        31: "DLL 缺失",
                        32: "DLL 找不到",
                    }
                    err_msg = error_map.get(int(result), f"ShellExecute 错误码: {result}")
                    raise OSError(f"启动机器人失败: {err_msg}")
                logger.info(f"机器人({robot_type})进程已启动")
            else:
                proc = subprocess.Popen(
                    [entry_exe],
                    cwd=robot_dir,
                    start_new_session=True,
                )
                logger.info(f"机器人({robot_type})进程已启动，PID: {proc.pid}")
        except Exception:
            logger.exception("启动机器人进程失败")
            raise HTTPException(status_code=500, detail="启动机器人进程失败，请检查日志。")

        return {
            "message": f"机器人({robot_type})已重启",
            "killed_pids": killed_pids,
        }

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
