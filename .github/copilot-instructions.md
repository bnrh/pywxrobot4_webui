# Project Guidelines

## Repository Context
- This repository is a Python-based wxrobot web UI project with backend files at the repo root and frontend assets under frontend/ and static/.
- Prefer minimal, targeted changes that fit the existing Python, JavaScript, and CSS style already used in the repository.

## Git Auto-Commit Workflow
- After finishing a user-requested code change in this repository, automatically perform a Git commit unless the user explicitly says not to commit.
- Prefer the workspace hooks under .github/hooks for automatic staging and automatic commit attempts at the end of the session, and fall back to manual Git commands only when hooks cannot complete the action.
- Before committing, run the narrowest validation that fits the change. Examples:
  - For Python backend changes, prefer focused checks such as python -m py_compile on the touched files.
  - For frontend or styling changes, prefer focused lint/error checks if available.
- Stage only files that belong to the current task. Do not stage unrelated user changes already present in the working tree.
- Create one commit per completed user request, not one commit per small intermediate edit.
- Every commit message must use Simplified Chinese. When using a conventional-style format, keep the type or scope concise and write the description in Simplified Chinese, such as:
  - 修复(智能插件)：调整配置表格布局
  - 优化(插件配置)：改进入群欢迎编辑界面
  - 重构(服务端)：统一 AI 提供商配置选择逻辑
- If validation fails, do not commit. Report the failure and stop at the validation result.
- Do not amend, rebase, reset, or force-push unless the user explicitly asks for it.

## Commit Scope Rules
- Include only files you changed for the current task.
- If the repository is dirty with unrelated changes, leave them untouched and out of the commit.
- If you are unsure whether a file belongs in the commit, ask before committing.

## Communication
- After committing, report the commit message and a short summary of what was changed.
- If no file was changed, do not create an empty commit.