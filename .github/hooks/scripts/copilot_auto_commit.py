import json
import re
import subprocess
import sys
from pathlib import Path


DIRECT_WRITE_TOOLS = {
    "apply_patch",
    "create_file",
    "editfiles",
    "replace_string_in_file",
    "vscode_renamesymbol",
    "renamesymbol",
}

PATH_LIKE_KEYS = {
    "file",
    "filepath",
    "filepaths",
    "files",
    "path",
    "paths",
    "oldpath",
    "newpath",
    "old_path",
    "new_path",
    "target",
    "targets",
    "includepattern",
}

PROMPT_SCOPE_RULES = [
    (("智能插件", "ai assistant", "mcp", "ai"), "智能插件"),
    (("enter_room_tip", "入群欢迎", "欢迎语", "群欢迎"), "enter_room_tip"),
    (("invite_to_toom", "关键词进群", "进群规则"), "invite_to_toom"),
    (("watch_wechat_processes", "getwxpids", "微信进程"), "watch_wechat_processes"),
    (("用户管理", "昵称", "微信号", "用户1"), "用户管理"),
    (("copilot", "hook", "钩子", "commit", "提交消息", "提交标题", "审批", "自动接受编辑", ".vscode"), "工作流"),
    (("settings", "settings.json", "工作区设置"), "工作区"),
]

FILE_SCOPE_RULES = [
    ((".vscode/settings.json",), "工作区"),
    ((".github/hooks/", ".github/copilot-instructions.md", ".gitignore"), "仓库"),
    (("plugins/enter_room_tip.py",), "enter_room_tip"),
    (("plugins/invite_to_toom.py",), "invite_to_toom"),
    (("plugins/watch_wechat_processes.py",), "watch_wechat_processes"),
    (("ai_assistant.py",), "智能插件"),
    (("server.py",), "服务端"),
    (("static/js/", "frontend/"), "前端"),
    (("static/css/",), "界面"),
]


def read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read().strip()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def print_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


def get_repo_root(payload: dict) -> Path:
    cwd = str(payload.get("cwd") or "").strip()
    if cwd:
        return Path(cwd)
    return Path(__file__).resolve().parents[3]


def get_state_dir(repo_root: Path) -> Path:
    git_dir = repo_root / ".git"
    state_dir = git_dir / "copilot-hooks" if git_dir.exists() else repo_root / ".github" / "hooks" / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def get_state_file(repo_root: Path, payload: dict) -> Path:
    session_id = str(payload.get("sessionId") or "default").strip() or "default"
    safe_session_id = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
    return get_state_dir(repo_root) / f"{safe_session_id}.json"


def load_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {"prompt": "", "files": []}
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {"prompt": "", "files": []}
    if not isinstance(payload, dict):
        return {"prompt": "", "files": []}
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    return {
        "prompt": str(payload.get("prompt") or "").strip(),
        "files": [str(item).strip() for item in files if str(item).strip()],
    }


def save_state(state_file: Path, state: dict) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_state(state_file: Path) -> None:
    try:
        if state_file.exists():
            state_file.unlink()
    except OSError:
        pass


def is_edit_tool(tool_name: str) -> bool:
    normalized = tool_name.strip().lower()
    if not normalized:
        return False
    if normalized in DIRECT_WRITE_TOOLS:
        return True
    if any(token in normalized for token in ("edit", "patch", "rename", "replace")):
        return True
    if normalized.startswith("create") and "file" in normalized:
        return True
    if normalized.startswith("delete") and "file" in normalized:
        return True
    return False


def normalize_repo_relative_path(repo_root: Path, raw_value: str) -> str | None:
    text = str(raw_value or "").strip().strip('"').strip("'")
    if not text or "://" in text:
        return None

    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = repo_root / candidate

    try:
        resolved_root = repo_root.resolve()
        resolved_candidate = candidate.resolve(strict=False)
        relative_path = resolved_candidate.relative_to(resolved_root)
    except Exception:
        return None

    if not relative_path.parts or relative_path.parts[0] == ".git":
        return None
    return relative_path.as_posix()


def extract_apply_patch_paths(repo_root: Path, tool_input: object) -> list[str]:
    text = ""
    if isinstance(tool_input, str):
        text = tool_input
    elif isinstance(tool_input, dict):
        text = str(tool_input.get("input") or tool_input.get("patch") or "")
    if not text:
        return []

    results: list[str] = []
    for match in re.finditer(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", text, flags=re.MULTILINE):
        normalized = normalize_repo_relative_path(repo_root, match.group(1).strip())
        if normalized and normalized not in results:
            results.append(normalized)
    return results


def collect_path_values(repo_root: Path, value: object, parent_key: str = "") -> list[str]:
    results: list[str] = []
    normalized_key = parent_key.strip().lower()

    if isinstance(value, dict):
        for key, nested_value in value.items():
            results.extend(collect_path_values(repo_root, nested_value, str(key)))
        return results

    if isinstance(value, list):
        for item in value:
            results.extend(collect_path_values(repo_root, item, parent_key))
        return results

    if isinstance(value, str) and normalized_key in PATH_LIKE_KEYS:
        normalized = normalize_repo_relative_path(repo_root, value)
        if normalized:
            results.append(normalized)
    return results


def extract_changed_files(repo_root: Path, payload: dict) -> list[str]:
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if not is_edit_tool(tool_name):
        return []

    collected = []
    if str(tool_name).strip().lower() == "apply_patch":
        collected.extend(extract_apply_patch_paths(repo_root, tool_input))
    collected.extend(collect_path_values(repo_root, tool_input))

    unique_files: list[str] = []
    for item in collected:
        if item not in unique_files:
            unique_files.append(item)
    return unique_files


def run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def stage_files(repo_root: Path, files: list[str]) -> tuple[bool, str]:
    if not files:
        return True, ""
    result = run_git(repo_root, ["add", "-A", "--", *files])
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "git add 执行失败").strip()


def list_staged_files(repo_root: Path, files: list[str]) -> list[str]:
    if not files:
        return []
    result = run_git(repo_root, ["diff", "--cached", "--name-only", "--", *files])
    if result.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def contains_any(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    return any(keyword for keyword in keywords if keyword and keyword in text)


def infer_action(prompt: str, files: list[str]) -> str:
    prompt_text = prompt.strip().lower()
    normalized_files = [item.replace("\\", "/").lower() for item in files]
    file_text = "\n".join(normalized_files)

    if contains_any(prompt_text, ("修复", "解决", "错误", "异常", "失败", "bug")):
        return "修复"
    if contains_any(prompt_text, ("重构", "改造", "重新设计", "重写")):
        return "重构"
    if ".github/" in file_text or ".vscode/" in file_text or contains_any(prompt_text, ("配置", "settings", "hook", "钩子", "审批", "自动接受", "commit")):
        return "配置"
    if contains_any(prompt_text, ("优化", "调整", "改进", "细化", "美观")):
        return "优化"
    if contains_any(prompt_text, ("新增", "增加", "添加", "补上", "支持")):
        return "新增"
    return "更新"


def infer_scope(prompt: str, files: list[str]) -> str:
    prompt_text = prompt.strip().lower()
    normalized_files = [item.replace("\\", "/") for item in files]
    lowered_files = [item.lower() for item in normalized_files]
    file_text = "\n".join(lowered_files)

    if ".vscode/settings.json" in lowered_files and any(path.startswith(".github/") for path in lowered_files):
        return "工作流"

    for keywords, scope in PROMPT_SCOPE_RULES:
        if contains_any(prompt_text, keywords):
            return scope

    for path_markers, scope in FILE_SCOPE_RULES:
        if any(marker.lower() in file_text for marker in path_markers):
            return scope

    if all(item.endswith(".css") for item in lowered_files if item):
        return "界面"
    if any(item.endswith(".js") for item in lowered_files):
        return "前端"
    if any(item.endswith(".py") for item in lowered_files):
        return "后端"
    return "项目"


def build_summary_from_prompt(prompt: str, files: list[str]) -> str:
    prompt_text = prompt.strip().lower()
    normalized_files = [item.replace("\\", "/").lower() for item in files]
    file_text = "\n".join(normalized_files)
    summary_parts: list[str] = []
    has_workspace_settings_request = ".vscode/settings.json" in normalized_files or contains_any(
        prompt_text,
        ("自动接受编辑", "auto accept", "autoaccept", "审批", "approval", "settings.json", "工作区设置"),
    )
    has_commit_title_request = contains_any(prompt_text, ("提交标题", "提交消息", "commit message", "中文提交"))

    if has_workspace_settings_request and has_commit_title_request:
        return "补充工作区设置并细化中文提交标题"

    if has_workspace_settings_request:
        summary_parts.append("启用编辑自动接受并减少审批提示")
    if has_commit_title_request:
        summary_parts.append("细化中文提交标题生成")
    elif ".github/hooks/" in file_text or contains_any(prompt_text, ("hook", "钩子", "自动提交")):
        summary_parts.append("更新自动提交钩子")
    if ".github/copilot-instructions.md" in normalized_files or contains_any(prompt_text, ("copilot instruction", "仓库指令", "custom instructions")):
        summary_parts.append("同步 Copilot 仓库指令")
    if ".gitignore" in normalized_files or contains_any(prompt_text, ("gitignore", ".gitignore", "忽略")):
        summary_parts.append("调整仓库忽略规则")

    if contains_any(prompt_text, ("enter_room_tip", "入群欢迎", "欢迎语", "群欢迎")):
        summary_parts.append("调整入群欢迎配置")
    if contains_any(prompt_text, ("invite_to_toom", "关键词进群", "进群规则")):
        summary_parts.append("调整进群规则配置")
    if contains_any(prompt_text, ("watch_wechat_processes", "getwxpids", "微信进程")):
        summary_parts.append("切换微信进程接口逻辑")
    if contains_any(prompt_text, ("用户管理", "昵称", "微信号", "用户1")):
        summary_parts.append("精简用户信息展示")
    if contains_any(prompt_text, ("智能插件", "ai assistant", "mcp", "deepseek", "minimax", "智谱")):
        summary_parts.append("完善智能插件能力")

    unique_parts = list(dict.fromkeys(summary_parts))
    if unique_parts:
        return "并".join(unique_parts[:2])

    if all(item.endswith(".css") for item in normalized_files if item):
        return "调整页面样式"
    if any(item.endswith(".css") for item in normalized_files) and any(item.endswith(".js") for item in normalized_files):
        return "调整前端交互与样式"
    if any(item.endswith(".js") for item in normalized_files) and any(item.endswith(".py") for item in normalized_files):
        return "同步前后端功能逻辑"
    if any(item.endswith(".js") for item in normalized_files):
        return "更新前端交互逻辑"
    if any(item.endswith(".py") for item in normalized_files):
        return "更新后端功能逻辑"
    if any(item.endswith(".md") or item.endswith(".json") for item in normalized_files):
        return "更新仓库配置与说明"
    return "更新项目代码"


def build_commit_message(prompt: str, files: list[str]) -> str:
    normalized_files = [item.replace("\\", "/") for item in files]
    action = infer_action(prompt, normalized_files)
    scope = infer_scope(prompt, normalized_files)
    summary = build_summary_from_prompt(prompt, normalized_files)
    return f"{action}({scope})：{summary}"


def handle_user_prompt_submit(repo_root: Path, payload: dict) -> dict:
    state_file = get_state_file(repo_root, payload)
    state = load_state(state_file)
    state["prompt"] = str(payload.get("prompt") or "").strip()
    save_state(state_file, state)
    return {}


def handle_post_tool_use(repo_root: Path, payload: dict) -> dict:
    changed_files = extract_changed_files(repo_root, payload)
    if not changed_files:
        return {}

    state_file = get_state_file(repo_root, payload)
    state = load_state(state_file)
    merged_files = list(dict.fromkeys([*state.get("files", []), *changed_files]))
    state["files"] = merged_files
    save_state(state_file, state)

    staged, error_message = stage_files(repo_root, changed_files)
    if staged:
        return {}
    return {"systemMessage": f"自动暂存失败：{error_message}"}


def handle_stop(repo_root: Path, payload: dict) -> dict:
    if payload.get("stop_hook_active") is True:
        return {}

    state_file = get_state_file(repo_root, payload)
    state = load_state(state_file)
    tracked_files = [item for item in state.get("files", []) if item]
    if not tracked_files:
        cleanup_state(state_file)
        return {}

    staged, error_message = stage_files(repo_root, tracked_files)
    if not staged:
        cleanup_state(state_file)
        return {"systemMessage": f"自动提交前暂存失败：{error_message}"}

    staged_files = list_staged_files(repo_root, tracked_files)
    if not staged_files:
        cleanup_state(state_file)
        return {}

    commit_message = build_commit_message(state.get("prompt", ""), staged_files)
    result = run_git(repo_root, ["commit", "--only", "-m", commit_message, "--", *staged_files])
    cleanup_state(state_file)

    if result.returncode == 0:
        return {"systemMessage": f"已自动提交：{commit_message}"}

    error_text = (result.stderr or result.stdout or "git commit 执行失败").strip()
    return {"systemMessage": f"自动提交失败：{error_text}"}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = read_stdin_json()
    repo_root = get_repo_root(payload)

    try:
        if mode == "UserPromptSubmit":
            output = handle_user_prompt_submit(repo_root, payload)
        elif mode == "PostToolUse":
            output = handle_post_tool_use(repo_root, payload)
        elif mode == "Stop":
            output = handle_stop(repo_root, payload)
        else:
            output = {}
    except Exception as exc:
        output = {"systemMessage": f"Copilot 自动提交钩子执行失败：{exc}"}

    print_json(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())