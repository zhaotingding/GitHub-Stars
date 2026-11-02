import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def launch(arguments=None):
    parser = argparse.ArgumentParser(description="GitHub Stars++ 源码启动器")
    parser.add_argument("--env", default="github-stars")
    parser.add_argument("--conda")
    options, forwarded = parser.parse_known_args(arguments)
    if not re.fullmatch(r"[\w.-]+", options.env) or options.env.lower() in {"base", "root"}:
        raise ValueError("请选择专用 Conda 环境，不能使用 base/root")
    manager = options.conda or os.getenv("CONDA_EXE") or shutil.which("conda.exe")
    if not manager or not Path(manager).is_file():
        raise ValueError("找不到 Conda。请在 Conda PowerShell 中运行，或用 --conda 指定 conda.exe")
    frozen = getattr(sys, "frozen", False)
    root = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[1]
    entry = root / "tools" / "entry.py"
    if not entry.is_file():
        raise ValueError("启动器必须与 src、tools 源码目录放在一起")
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    for key in list(env):
        if key in {"CONDA_DEFAULT_ENV", "CONDA_PROMPT_MODIFIER"} or key.startswith("CONDA_PREFIX"):
            env.pop(key, None)
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", CONDA_SHLVL="0", CONDA_EXE=str(manager))
    # 从干净激活栈选择目标环境，避免继承不完整的 Conda 激活状态。
    if frozen and os.name == "nt":
        ctypes.windll.kernel32.SetDllDirectoryW(None)  # 清除 PyInstaller DLL 搜索路径。
        bundle = Path(sys._MEIPASS).resolve()
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                      if p and not Path(p).resolve().is_relative_to(bundle))
    command = [manager, "run", "-n", options.env, "--no-capture-output", "python", "-s", str(entry)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    check = subprocess.run([*command, "--check-environment"], check=False, cwd=root, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=90, creationflags=flags)
    if check.returncode:
        raise ValueError("环境检查失败：" + (check.stderr or check.stdout)[-1800:])
    info = json.loads(check.stdout)
    if info["environment"] != options.env or not info["valid"]:
        raise ValueError("实际解释器与指定 Conda 环境不匹配")
    subprocess.Popen([*command, *forwarded], cwd=root, env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


if __name__ == "__main__":
    try:
        launch()
    except Exception as exc:
        text = f"{exc}\n\n请按 README 创建 github-stars 环境并安装依赖；启动器不会自动安装或回退到其他 Python。"
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, text, "GitHub Stars++ · 启动失败", 16)
        else:
            print(text, file=sys.stderr)
        raise SystemExit(1)
