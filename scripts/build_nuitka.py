"""Nuitka Windows standalone build for wxrobot_webui.

Uses an isolated venv so unused site-packages (PySide6, IPython, ...)
are not available for Nuitka to follow via optional imports in numpy/PIL.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "wxrobot_webui"
OUT_DIR = ROOT / "dist"
DIST_DIR = OUT_DIR / f"{APP_NAME}.dist"
MAIN_DIST = OUT_DIR / "main.dist"
BUILD_VENV = ROOT / ".venv-build"

# Optional imports that bloated standalone dist when present in the global env.
NOFOLLOW_IMPORTS = (
    "PySide2",
    "PySide6",
    "PyQt5",
    "PyQt6",
    "shiboken2",
    "shiboken6",
    "qtpy",
    "qtconsole",
    "IPython",
    "ipykernel",
    "ipywidgets",
    "jupyter",
    "jupyter_client",
    "jupyter_core",
    "matplotlib",
    "matplotlib_inline",
    "tkinter",
    "PySide6-Addons",
    "PySide6_Addons",
    "PySide6-Essentials",
    "PySide6_Essentials",
)

RUNTIME_REQUIREMENTS = (
    "fastapi>=0.115.0,<1.0",
    "uvicorn>=0.30.0,<1.0",
    "loguru>=0.7.0,<1.0",
    "pydantic>=2.7.0,<3.0",
    "python-multipart>=0.0.9,<1.0",
    "httpx>=0.27.0,<1.0",
    "numpy>=1.26.0,<3.0",
    "Pillow>=10.0.0,<12.0",
    "zxing-cpp>=2.2.0,<3.0",
    "nuitka",
    "ordered-set",
    "zstandard",
)


def resolve_executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(name)
    return path


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    if not command:
        raise ValueError("command must not be empty")
    workdir = str(cwd or ROOT)
    argv = list(command)
    if Path(argv[0]).name == argv[0]:
        argv[0] = resolve_executable(argv[0])
    print("+", " ".join(argv), flush=True)
    if sys.platform == "win32" and argv[0].lower().endswith((".cmd", ".bat")):
        subprocess.run(subprocess.list2cmdline(argv), cwd=workdir, check=True, shell=True, env=env)
        return
    subprocess.run(argv, cwd=workdir, check=True, env=env)


def which_or_exit(name: str, hint: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"[ERROR] {name} not found. {hint}")
    return path


def venv_python() -> Path:
    if sys.platform == "win32":
        return BUILD_VENV / "Scripts" / "python.exe"
    return BUILD_VENV / "bin" / "python"


def ensure_build_venv() -> Path:
    """Create/use an isolated env so global GUI/jupyter packages are not followed."""
    py = venv_python()
    if not py.is_file():
        print(f"Creating isolated build venv: {BUILD_VENV}", flush=True)
        builder = venv.EnvBuilder(with_pip=True, clear=False)
        builder.create(BUILD_VENV)
    return py


def build_frontend() -> None:
    print("\n===== [1/4] Build frontend =====", flush=True)
    which_or_exit("npm", "Install Node.js and ensure npm is on PATH.")
    if not (ROOT / "node_modules").exists():
        run(["npm", "install"])
    run(["npm", "run", "build"])
    if not (ROOT / "static" / "dist").is_dir():
        raise SystemExit("[ERROR] static/dist missing after Vite build.")


def install_python_deps(py: Path) -> None:
    print("\n===== [2/4] Install runtime deps into build venv =====", flush=True)
    run([str(py), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
    run([str(py), "-m", "pip", "install", "-U", *RUNTIME_REQUIREMENTS])


def compile_with_nuitka(py: Path) -> None:
    print("\n===== [3/4] Nuitka compile (standalone, isolated venv) =====", flush=True)
    for path in (OUT_DIR / f"{APP_NAME}.build", DIST_DIR, MAIN_DIST):
        if path.exists():
            shutil.rmtree(path)

    command = [
        str(py),
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--remove-output",
        "--enable-plugin=anti-bloat",
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
        "--include-module=zxingcpp",
        "--include-package-data=PIL",
        "--include-data-dir=frontend=frontend",
        "--include-data-dir=static=static",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=tests",
        "--nofollow-import-to=_pytest",
        "--nofollow-import-to=py",
        "--nofollow-import-to=node_modules",
    ]
    for name in NOFOLLOW_IMPORTS:
        command.append(f"--nofollow-import-to={name}")
    command.append("main.py")
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
        py = ensure_build_venv()
        install_python_deps(py)
        compile_with_nuitka(py)
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
