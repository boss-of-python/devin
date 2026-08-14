"""Single-file binary packaging via PyInstaller or Nuitka (STEP_50).

Usage:
    python build_executable.py --backend pyinstaller
    python build_executable.py --backend nuitka --onefile
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "echo-breach"
ENTRY = os.path.join(ROOT, "main.py")
ASSETS = os.path.join(ROOT, "assets")
SEPARATOR = ";" if os.name == "nt" else ":"

HIDDEN_IMPORTS = ("panda3d.core", "panda3d.direct", "direct.showbase.ShowBase", "scipy.spatial")


def pyinstaller_command(onefile: bool, console: bool) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        APP_NAME,
        "--noconfirm",
        "--clean",
        "--onefile" if onefile else "--onedir",
        "--collect-all",
        "ursina",
        "--collect-all",
        "panda3d",
        "--add-data",
        f"{ASSETS}{SEPARATOR}assets",
    ]
    if not console:
        cmd.append("--windowed")
    for module in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", module]
    cmd.append(ENTRY)
    return cmd


def nuitka_command(onefile: bool, console: bool) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        f"--output-filename={APP_NAME}",
        f"--output-dir={os.path.join(ROOT, 'dist')}",
        "--include-package=ursina",
        "--include-package=panda3d",
        f"--include-data-dir={ASSETS}=assets",
    ]
    if onefile:
        cmd.append("--onefile")
    if not console:
        cmd.append("--disable-console")
    cmd.append(ENTRY)
    return cmd


def ensure_backend(backend: str) -> None:
    module = "PyInstaller" if backend == "pyinstaller" else "nuitka"
    try:
        __import__(module)
    except ImportError:
        raise SystemExit(
            f"{module} is not installed. Install it first: pip install {module.lower()}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Package ECHO-BREACH into a distributable binary.")
    parser.add_argument("--backend", choices=("pyinstaller", "nuitka"), default="pyinstaller")
    parser.add_argument("--onefile", action="store_true", default=True)
    parser.add_argument("--onedir", dest="onefile", action="store_false")
    parser.add_argument("--console", action="store_true", help="keep a console window for logs")
    parser.add_argument("--dry-run", action="store_true", help="print the command without running it")
    args = parser.parse_args(argv)

    if not args.dry_run:
        ensure_backend(args.backend)

    builder = pyinstaller_command if args.backend == "pyinstaller" else nuitka_command
    cmd = builder(args.onefile, args.console)
    print(" ".join(cmd))
    if args.dry_run:
        return 0

    for stale in ("build", "dist", f"{APP_NAME}.spec"):
        path = os.path.join(ROOT, stale)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)

    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
