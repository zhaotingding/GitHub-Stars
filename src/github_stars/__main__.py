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
    parser.add_argument("--url", help="导入仓库链接或包含 Markdown 链接的文字")
    parser.add_argument('--question', help='项目研究问题')
    parser.add_argument('--job-id', help='已保存的研究任务编号')
    parser.add_argument('--mode', choices=['standard', 'agent'], default='standard')
    parser.add_argument('--repo-id', type=int, action='append', help='限定已保存项目编号，可重复')
    parser.add_argument('--allow-images', action='store_true', help='明确允许本题附件发送图片模型')
    parser.add_argument('--image', action='append', default=[], help='本题本地PNG附件，可重复')
    parser.add_argument('--rating', choices=['useful', 'irrelevant', 'clear'], default='useful')
    parser.add_argument('--unsave', action='store_true', help='取消收藏')
    research_commands = ['research', 'research-status', 'research-resume', 'research-continue',
                         'research-cancel', 'research-bookmark', 'research-feedback']
    parser.add_argument("command", nargs="?", choices=["gui", "scan", "digest", "tick", "status", "import"]+research_commands, default="gui")
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
            if args.command in research_commands:
                if args.command == 'research':
                    if not args.question:
                        raise ValueError('research需要--question')
                    result = service.run('research', question=args.question, mode=args.mode, repo_ids=args.repo_id,
                                         allow_images=args.allow_images, image_paths=args.image, job_id=args.job_id)
                else:
                    if not args.job_id:
                        raise ValueError('研究控制操作需要--job-id')
                    options = {'job_id': args.job_id}
                    if args.command == 'research-bookmark':
                        options['saved'] = not args.unsave
                    if args.command == 'research-feedback':
                        options['rating'] = args.rating
                    result = service.run(args.command.replace('-', '_'), **options)
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif args.command == "status":
                result = {"root": str(paths.root), "projects": service.store.one("SELECT count(*) n FROM repos")["n"],
                          "latest_scan": service.store.one("SELECT * FROM scans ORDER BY id DESC LIMIT 1"),
                          "latest_digest": service.store.one("SELECT * FROM digests ORDER BY week DESC LIMIT 1")}
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                if args.command == "import" and not args.url:
                    raise ValueError("import 需要 --url 指定仓库链接")
                print(service.run(args.command, text=args.url))
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else f"{type(exc).__name__}，请检查配置和运行记录"
        if args.command == "gui":
            from .theme import start_error_dialog
            try:
                selected_theme = Paths(args.root).load()["appearance"]["theme"]
            except Exception:
                selected_theme = "dark"
            start_error_dialog(message, selected_theme)
        elif sys.stderr:
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
