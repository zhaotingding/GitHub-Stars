import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, "-s", "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                "--name", "GitHub Stars++", "--distpath", str(root / "dist"), "--workpath", str(root / "build"),
                "--specpath", str(root / "build"), str(root / "tools" / "launcher.py")], cwd=root, check=True)
target = root / "GitHub Stars++.exe"
if target.exists():
    raise SystemExit("根目录已有启动器。新产物在 dist，请验证后自行替换。")
shutil.copy2(root / "dist" / "GitHub Stars++.exe", target)  # 首次构建可直接部署，升级不覆盖旧入口。
print(target)
