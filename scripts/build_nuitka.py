"""Nuitka Windows standalone build for wxrobot_webui."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "wxrobot_webui"
OUT_DIR = ROOT / "dist"
DIST_DIR = OUT_DIR / f"{APP_NAME}.dist"
MAIN_DIST = OUT_DIR / "main.dist"


def resolve_executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(name)
    return path


def run(command: list[str], *, cwd: Path | None = None) -> None:
    if not command:
        raise ValueError("command must not be empty")
    workdir = str(cwd or ROOT)
    argv = list(command)
    # Absolute python/exe paths are used as-is; bare names need PATH resolution.
    if Path(argv[0]).name == argv[0]:
        argv[0] = resolve_executable(argv[0])
    print("+", " ".join(argv), flush=True)
    # Windows cannot CreateProcess .cmd/.bat without a shell.
    if sys.platform == "win32" and argv[0].lower().endswith((".cmd", ".bat")):
        subprocess.run(subprocess.list2cmdline(argv), cwd=workdir, check=True, shell=True)
        return
    subprocess.run(argv, cwd=workdir, check=True)


def which_or_exit(name: str, hint: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"[ERROR] {name} not found. {hint}")
    return path


def build_frontend() -> None:
    print("\n===== [1/4] Build frontend =====", flush=True)
    which_or_exit("npm", "Install Node.js and ensure npm is on PATH.")
    if not (ROOT / "node_modules").exists():
        run(["npm", "install"])
    run(["npm", "run", "build"])
    if not (ROOT / "static" / "dist").is_dir():
        raise SystemExit("[ERROR] static/dist missing after Vite build.")


def install_python_deps() -> None:
    print("\n===== [2/4] Install Python deps and Nuitka =====", flush=True)
    py = sys.executable
    run([py, "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
    run([py, "-m", "pip", "install", "-r", "requirements.txt"])
    run([py, "-m", "pip", "install", "-U", "nuitka", "ordered-set", "zstandard"])


def compile_with_nuitka() -> None:
    print("\n===== [3/4] Nuitka compile (standalone) =====", flush=True)
    for path in (OUT_DIR / f"{APP_NAME}.build", DIST_DIR, MAIN_DIST):
        if path.exists():
            shutil.rmtree(path)

    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--remove-output",
        f"--output-dir={OUT_DIR}",
        f"--output-filename={APP_NAME}.exe",
        "--windows-console-mode=force",
        "--include-package=core",
        "--include-package=server",
        "--include-package=runtime",
        "--include-package=messaging",
        "--include-package=manager",
        "--include-package=routes",
        "--include-package=ai_assistant",
        "--include-package=plugins",
        "--include-package=utils",
        "--include-package=uvicorn",
        "--include-package=fastapi",
        "--include-package=starlette",
        "--include-package=pydantic",
        "--include-package=pydantic_core",
        "--include-package=anyio",
        "--include-package=httpx",
        "--include-package=httpcore",
        "--include-package=multipart",
        "--include-package=loguru",
        "--include-package=PIL",
        "--include-package=numpy",
        "--include-package=zxingcpp",
        "--include-package-data=PIL",
        "--include-package-data=zxingcpp",
        "--include-data-dir=frontend=frontend",
        "--include-data-dir=static=static",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=tests",
        "--nofollow-import-to=_pytest",
        "--nofollow-import-to=py",
        "--nofollow-import-to=node_modules",
        "--company-name=wxrobot",
        "--product-name=wxrobot_webui",
        "--file-description=wxrobot WebUI Plugin Server",
        "main.py",
    ]
    run(command)

    if MAIN_DIST.exists():
        if DIST_DIR.exists():
            shutil.rmtree(DIST_DIR)
        MAIN_DIST.rename(DIST_DIR)

    exe_path = DIST_DIR / f"{APP_NAME}.exe"
    if not exe_path.is_file():
        listing = ", ".join(p.name for p in OUT_DIR.iterdir()) if OUT_DIR.exists() else "(empty)"
        raise SystemExit(f"[ERROR] Missing {exe_path}. dist contents: {listing}")


def main() -> int:
    which_or_exit("python", "Install Python 3.11+ and ensure it is on PATH.")
    if sys.platform != "win32":
        raise SystemExit("[ERROR] This build script only supports Windows.")

    try:
        build_frontend()
        install_python_deps()
        compile_with_nuitka()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"[ERROR] Command failed with exit code {exc.returncode}") from exc

    exe_path = DIST_DIR / f"{APP_NAME}.exe"
    print("\n===== [4/4] Done =====", flush=True)
    print(f"Executable: {exe_path}", flush=True)
    print("Copy the whole dist folder to the target machine. No Python install needed.", flush=True)
    print("SQLite / uploads / logs are written next to the exe.", flush=True)
    print("For remote access, set host to 0.0.0.0 in system settings.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
