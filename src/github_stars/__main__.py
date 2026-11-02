from __future__ import annotations

import argparse
import importlib
import json
import os
import site
import sys
from pathlib import Path

from . import __version__
from .config import Paths
from .service import Service


def environment():
    prefix = Path(sys.prefix).resolve()
    modules = {name: str(Path(importlib.import_module(name).__file__).resolve())
               for name in ("httpx", "yaml", "openai", "keyring", "pydantic")}
    valid = (prefix / "conda-meta").is_dir() and prefix.name.lower() not in {"base", "root"}
    valid = valid and not site.ENABLE_USER_SITE and all(Path(p).is_relative_to(prefix) for p in modules.values())
    manager = os.getenv("CONDA_EXE")
    if manager and prefix == Path(manager).resolve().parents[1]:
        valid = False  # 常见 Conda base 根也必须拒绝。
    return {"valid": valid, "version": __version__, "python": sys.executable, "prefix": str(prefix),
            "environment": prefix.name, "user_site": site.ENABLE_USER_SITE, "modules": modules,
            "source": str(Path(__file__).resolve())}


def main(argv=None):
    parser = argparse.ArgumentParser(description="GitHub Stars++ · 每天观察，每周少量阅读")
    parser.add_argument("--root", type=Path, default=Path(os.getenv("GITHUB_STARS_ROOT", Path(__file__).resolve().parents[2])))
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--check-environment", action="store_true")
    parser.add_argument("command", nargs="?", choices=["gui", "scan", "digest", "tick", "status"], default="gui")
    args = parser.parse_args(argv)
    if args.check_environment:
        result = environment()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["valid"] else 1
    try:
        paths = Paths(args.root)
        if args.command == "gui":
            from .gui import App
            App(paths).mainloop()
        else:
            service = Service(paths)
            if args.command == "status":
                result = {"root": str(paths.root), "projects": service.store.one("SELECT count(*) n FROM repos")["n"],
                          "latest_scan": service.store.one("SELECT * FROM scans ORDER BY id DESC LIMIT 1"),
                          "latest_digest": service.store.one("SELECT * FROM digests ORDER BY week DESC LIMIT 1")}
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(service.run(args.command))
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else f"{type(exc).__name__}，请检查配置和运行记录"
        if args.command == "gui":
            import tkinter as tk
            from tkinter import messagebox
            window = tk.Tk()
            window.withdraw()
            messagebox.showerror("GitHub Stars++ · 启动失败", message)
            window.destroy()
        elif sys.stderr:
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
