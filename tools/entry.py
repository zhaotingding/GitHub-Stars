import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]  # 源码、轻量启动器和计划任务共用此入口。
os.environ.pop("PYTHONHOME", None)
os.environ.pop("PYTHONPATH", None)
os.environ["PYTHONNOUSERSITE"] = "1"
sys.path.insert(0, str(root / "src"))

if __name__ == "__main__":
    try:
        from github_stars.__main__ import main
    except Exception as exc:
        from datetime import datetime
        data = root / "data"
        data.mkdir(exist_ok=True)
        missing = getattr(exc, "name", "") or ""
        with (data / "startup.log").open("a", encoding="utf-8") as log:
            log.write(f"{datetime.now().isoformat()} {type(exc).__name__} {missing}；检查专用环境依赖和 README 安装步骤\n")
        raise SystemExit(1) from None
    raise SystemExit(main())
