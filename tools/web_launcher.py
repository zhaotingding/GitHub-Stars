"""Launch or reopen this installation's loopback browser application."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from github_stars.__main__ import environment
from github_stars.config import Paths
from github_stars.web import open_browser


def main():
    if not environment()['valid']:
        raise ValueError('请使用已安装本项目的独立Conda环境，并带-s启动')
    root = Path(__file__).resolve().parents[1]
    paths = Paths(root)
    expected = hashlib.sha256(str(root).encode()).hexdigest()
    port = paths.load()['web']['port']
    url = f'http://127.0.0.1:{port}/'
    record = paths.data / 'web-server.json'
    if record.exists():
        try:
            candidate = json.loads(record.read_text())['url']
            import re
            if re.fullmatch(r'http://127\.0\.0\.1:\d{1,5}/', candidate):
                url = candidate
        except (ValueError, KeyError):
            pass
    with httpx.Client(timeout=1, trust_env=False) as client:
        def running():
            try:
                response = client.get(url+'api/health')
                return response.status_code == 200 and response.json().get('root') == expected
            except (httpx.HTTPError, ValueError):
                return False
        if running():
            open_browser(url)
            print('已打开运行中的网页端：'+url)
            return 0
        url = f'http://127.0.0.1:{port}/'
        child_env = os.environ.copy()
        child_env.pop('PYTHONHOME', None)
        child_env.pop('PYTHONPATH', None)
        with (paths.data/'web.log').open('a', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, '-s', str(root/'tools/entry.py'), '--root', str(root),
                                        'web', '--port', str(port)], cwd=root, env=child_env,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        for _ in range(40):
            if running():
                open_browser(url)
                print('网页端已启动：'+url)
                return 0
            if process.poll() is not None:
                break
            time.sleep(.1)
    print('网页服务未启动，请检查端口或data/web.log。', file=sys.stderr)
    return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
