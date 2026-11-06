"""Start the installed WSL desktop app without keeping a terminal open."""

import argparse
import fcntl
import os
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def main():
    parser = argparse.ArgumentParser(description="GitHub Stars++ WSL 桌面启动器")
    parser.add_argument("--root", type=Path, default=APP_ROOT, help="配置和数据所在目录")
    options = parser.parse_args()
    from github_stars.__main__ import environment as check_environment
    if not check_environment()["valid"]:
        print("请使用已安装项目的独立Conda环境，并带-s启动。", file=sys.stderr)
        return 1
    data_root = options.root.resolve()
    if not PYTHON.is_file() or not (APP_ROOT / "tools/entry.py").is_file():
        print("启动文件或独立环境不存在，请检查安装目录。", file=sys.stderr)
        return 1
    data = data_root / "data"
    data.mkdir(parents=True, exist_ok=True)
    with (data / "desktop.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("GitHub Stars++ 已在运行，请查看已打开的窗口。")
            return 0
        environment = os.environ.copy()
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONUTF8"] = "1"
        # The Conda Tk build lacks Xft and renders CJK as literal Unicode escapes.
        # Use this machine's compatible Tk 8.6 with Xft for this GUI process only.
        native_tk = Path("/usr/lib/x86_64-linux-gnu/libtk8.6.so")
        native_scripts = Path("/usr/share/tcltk/tk8.6")
        bundled_tk = Path(sys.prefix) / "lib/libtk8.6.so"
        if bundled_tk.is_file():
            links = subprocess.run(["ldd", str(bundled_tk)], capture_output=True, text=True,
                                   check=True, timeout=5).stdout
            if "libXft" not in links:
                if not native_tk.is_file() or not native_scripts.is_dir():
                    print("当前Tk缺少Xft，且系统没有可用替代库；请按使用说明配置中文字体。", file=sys.stderr)
                    return 1
                existing_preloads = environment.get("LD_PRELOAD", "").split()
                environment["LD_PRELOAD"] = " ".join([str(native_tk), *existing_preloads])
                environment["TK_LIBRARY"] = str(native_scripts)
        with (data / "desktop.log").open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(PYTHON), "-s", str(APP_ROOT / "tools/entry.py"), "--root", str(data_root), "gui"],
                cwd=APP_ROOT, env=environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                pass_fds=(lock.fileno(),),
            )
        (data / "desktop.pid").write_text(str(process.pid) + "\n", encoding="ascii")
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            print(f"已启动 GitHub Stars++，进程 {process.pid}。")
            return 0
        print(f"程序已退出（{process.returncode}），请查看 {data / 'desktop.log'}。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
