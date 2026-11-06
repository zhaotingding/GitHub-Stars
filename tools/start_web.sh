#!/usr/bin/env bash
set -euo pipefail
stars_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
stars_python="${GITHUB_STARS_PYTHON:-}"
if [[ -z "$stars_python" && -x "$stars_root/../.task_envs/github-stars/bin/python" ]]; then
  stars_python="$stars_root/../.task_envs/github-stars/bin/python"
fi
if [[ -z "$stars_python" && -n "${CONDA_PREFIX:-}" && -x "$CONDA_PREFIX/bin/python" ]]; then
  stars_python="$CONDA_PREFIX/bin/python"
fi
if [[ -z "$stars_python" || ! -x "$stars_python" ]]; then
  printf '%s\n' '请先激活独立Conda环境，或将GITHUB_STARS_PYTHON设为该环境的Python路径。' >&2
  exit 1
fi
exec /usr/bin/env -u PYTHONHOME -u PYTHONPATH "$stars_python" -s "$stars_root/tools/web_launcher.py" "$@"
