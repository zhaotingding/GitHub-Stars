"""Single-user loopback browser interface sharing the desktop business service."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

import httpx

from . import __version__
from .config import merge, validate
from .reports import digest_text, html_document
from .research_search import png_attachment
from .service import Service
from .settings_schema import SECTIONS
from .store import STUDY_STATES, exclusive
from .tutorial_html import render_tutorial

SECRET_NAMES = {'openai': 'OPENAI_API_KEY', 'github': 'GITHUB_TOKEN', 'smtp': 'GITHUB_STARS_SMTP_PASSWORD'}
SCHEMA = """CREATE TABLE IF NOT EXISTS web_operations (
 id TEXT PRIMARY KEY, action TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
 created REAL NOT NULL, result TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '');"""


class WebError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def identity(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise WebError('任务编号无效')
    return value


def number(value):
    if type(value) is not int or not 0 < value < 10**15:
        raise WebError('项目编号无效')
    return value


def revision(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def json_numbers(value, template):
    # JavaScript JSON.stringify(0.0) produces 0; keep the existing YAML float contract.
    if type(template) is float and type(value) is int:
        return float(value)
    if isinstance(value, dict) and isinstance(template, dict):
        return {key: json_numbers(item, template.get(key)) for key, item in value.items()}
    return value


class WebApplication:
    def __init__(self, service):
        self.service = service
        self.paths, self.store = service.paths, service.store
        self.mutex = threading.RLock()
        self.active = None
        self.closing = False
        with self.store.connect() as db:
            db.executescript(SCHEMA)
            db.execute("UPDATE web_operations SET state='unknown',error='网页服务曾中断；不会自动重新执行，请先检查原任务' "
                       "WHERE state IN ('queued','running')")

    @property
    def busy(self):
        with self.mutex:
            return self.active is not None

    def state(self):
        rows = self.store.rows('SELECT id,name,metadata,score,study_state FROM repos ORDER BY score DESC LIMIT 300')
        for row in rows:
            metadata = json.loads(row.pop('metadata'))
            row.update(description=metadata.get('description') or '', stars=metadata.get('stargazers_count', 0))
        return dict(version=__version__, theme=self.paths.load()['appearance']['theme'], busy=self.busy, projects=rows, study_states=STUDY_STATES,
                    project_count=self.store.one('SELECT count(*) n FROM repos')['n'],
                    digests=self.store.rows('SELECT week,created,note,mail_state FROM digests ORDER BY week DESC LIMIT 30'),
                    research=self.store.rows('SELECT id,question,state FROM research_jobs WHERE expires>? '
                                             'ORDER BY created DESC LIMIT 50', (time.time(),)),
                    bookmarks=self.store.rows('SELECT id,question FROM research_bookmarks ORDER BY created DESC LIMIT 50'),
                    operations=self.store.rows('SELECT id,action,state,error,result FROM web_operations '
                                               'ORDER BY created DESC LIMIT 30'))

    def settings(self):
        config = self.paths.load()
        choices = {'credential_source': ['local', 'msgx', 'autogpu'],
                   'image_credential_source': ['local', 'msgx', 'autogpu'],
                   'service_tier': ['default', 'flex'], 'security': ['ssl', 'starttls']}
        schema = [dict(name=name, fields=[dict(section=s, key=k, label=label, type=type(config[s][k]).__name__,
                                               choices=choices.get(k, [])) for s, k, label in fields])
                  for name, fields in SECTIONS.items()]
        return dict(config=config, revision=revision(config), schema=schema)

    def save_settings(self, payload):
        if set(payload) - {'config', 'revision', 'secrets'}:
            raise WebError('未知的设置参数')
        entered = payload.get('secrets', {})
        if not isinstance(entered, dict) or set(entered) - SECRET_NAMES.keys():
            raise WebError('密钥类别无效')
        for value in entered.values():
            if not isinstance(value, str) or len(value) > 4096 or any(c in value for c in '\r\n\0'):
                raise WebError('密钥格式无效')
        with self.mutex:
            if self.active or self.closing:
                raise WebError('任务运行中，请等待完成后保存设置', 409)
            with exclusive(self.paths.data / 'worker.lock'), exclusive(self.paths.data / 'config.lock'):
                current = self.paths.load()
                if payload.get('revision') != revision(current):
                    raise WebError('设置已被其他窗口更新，请重新加载后再保存', 409)
                if not isinstance(payload.get('config'), dict):
                    raise WebError('设置格式无效')
                config = json_numbers(merge(current, payload['config']), current)
                validate(config)
                self.paths.save(config)
                for kind, value in entered.items():
                    if value.strip():
                        os.environ[SECRET_NAMES[kind]] = value.strip()
        return dict(message='设置已保存；输入的密钥仅用于当前应用进程，未写入文件', revision=revision(config))

    def project(self, repo_id):
        row = self.store.one('SELECT * FROM repos WHERE id=?', (number(repo_id),))
        if not row:
            raise WebError('项目不存在', 404)
        row['metadata'] = json.loads(row['metadata'])
        row['reasons'] = json.loads(row['reasons'])
        row['jobs'] = self.store.rows('SELECT id,kind,status,error,created,actual_model,input_tokens,output_tokens '
                                      'FROM ai_jobs WHERE repo_id=? ORDER BY id DESC LIMIT 20', (repo_id,))
        analysis = self.store.one("SELECT result FROM ai_jobs WHERE repo_id=? AND kind='analysis' AND status='completed' "
                                  'ORDER BY id DESC LIMIT 1', (repo_id,))
        row['analysis'] = json.loads(analysis['result']) if analysis else None
        row['legacy'] = [json.loads(item['result']) for item in self.store.rows(
            "SELECT result FROM ai_jobs WHERE repo_id=? AND kind='legacy' AND result IS NOT NULL ORDER BY id DESC LIMIT 3", (repo_id,))]
        return row

    def tutorial(self, repo_id):
        repo_id = number(repo_id)
        row = self.store.one('SELECT * FROM repos WHERE id=?', (repo_id,))
        job = self.store.one("SELECT result FROM ai_jobs WHERE repo_id=? AND kind='tutorial' AND status='completed' "
                             'ORDER BY id DESC LIMIT 1', (repo_id,))
        if not row or not job:
            raise WebError('尚无已完成教程，请先主动生成', 404)
        return render_tutorial(row, json.loads(job['result']), self.paths.load()['appearance']['theme']).encode('utf-8')

    def search_projects(self, query):
        if not isinstance(query, str) or len(query) > 200:
            raise WebError('搜索最多200字')
        rows = self.store.rows('SELECT id,name,metadata,score,study_state FROM repos '
                               'WHERE instr(lower(name||metadata),lower(?))>0 ORDER BY score DESC LIMIT 300', (query,))
        for row in rows:
            metadata = json.loads(row.pop('metadata'))
            row.update(description=metadata.get('description') or '', stars=metadata.get('stargazers_count', 0))
        return dict(projects=rows)

    def logs(self):
        return dict(events=self.store.rows('SELECT created,level,message FROM events ORDER BY id DESC LIMIT 60'),
                    jobs=self.store.rows('SELECT id,kind,status,actual_model,input_tokens,output_tokens,error '
                                         'FROM ai_jobs ORDER BY id DESC LIMIT 30'),
                    research_steps=self.store.rows('SELECT job_id,kind,state,actual_model,input_tokens,output_tokens,'
                                                   'cost,reserve FROM research_steps ORDER BY id DESC LIMIT 40'))

    def validate_action(self, action, args, scheduled=False):
        fields = {'scan': set(), 'digest': set(), 'import': {'text'}, 'analysis': {'repo_id'},
                  'tutorial': {'repo_id'}, 'recover': {'repo_id', 'kind'}, 'email': {'week', 'retry'},
                  'research': {'question', 'mode', 'repo_ids', 'allow_images', 'attachments'},
                  'research_resume': {'job_id'}, 'research_continue': {'job_id'}}
        if scheduled:
            fields['tick'] = set()
        if not isinstance(action, str) or action not in fields or not isinstance(args, dict) or set(args) - fields[action]:
            raise WebError('不支持的操作或参数')
        if 'repo_id' in fields[action]:
            number(args.get('repo_id'))
        if action == 'import' and (not isinstance(args.get('text'), str) or not 1 <= len(args['text']) <= 20000):
            raise WebError('请输入最多20000字的仓库链接')
        if action == 'recover' and args.get('kind') not in {'analysis', 'tutorial'}:
            raise WebError('恢复用途无效')
        if action == 'email' and (not isinstance(args.get('week'), str) or not re.fullmatch(r'\d{4}-W\d{2}', args['week'])
                                  or type(args.get('retry', False)) is not bool):
            raise WebError('周报或重发参数无效')
        if action in {'research_resume', 'research_continue'}:
            identity(args.get('job_id'))
        if action == 'research':
            if not isinstance(args.get('question'), str) or not 2 <= len(args['question'].strip()) <= 1000:
                raise WebError('问题需要2～1000字')
            if args.get('mode', 'standard') not in {'standard', 'agent'} or type(args.get('allow_images', False)) is not bool:
                raise WebError('模式或读图许可无效')
            ids = args.get('repo_ids')
            if ids is not None:
                if not isinstance(ids, list) or not 1 <= len(ids) <= 30:
                    raise WebError('项目范围无效')
                for repo_id in ids:
                    number(repo_id)
            images = args.get('attachments', [])
            if not isinstance(images, list) or len(images) > 2:
                raise WebError('最多两张PNG附件')
            if images and not args.get('allow_images', False):
                raise WebError('请先明确允许本题读图，附件尚未解码或保存')
            limit = self.paths.load()['research']['max_images']
            if len(images) > limit or (args.get('mode', 'standard') == 'standard' and len(images) > 1):
                raise WebError('附件数量超过本题或模式限制')
            for image in images:
                if (not isinstance(image, dict) or set(image) != {'data'} or not isinstance(image['data'], str)
                        or len(image['data']) > 2_666_668):
                    raise WebError('PNG附件格式无效或超过2MB')

    def submit(self, payload, scheduled=False):
        if set(payload) != {'id', 'action', 'args'}:
            raise WebError('操作格式无效')
        operation_id = identity(payload['id'])
        action, args = payload['action'], payload['args']
        self.validate_action(action, args, scheduled=scheduled)
        fingerprint = revision(dict(action=action, args=args))
        with self.mutex:
            if self.closing:
                raise WebError('网页服务正在关闭', 409)
            previous = self.store.one('SELECT * FROM web_operations WHERE id=?', (operation_id,))
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise WebError('同一操作编号不能替换参数', 409)
                return dict(id=operation_id, state=previous['state'])
            if self.active:
                raise WebError('已有任务正在运行，请等待完成', 409)
            self.store.execute('INSERT INTO web_operations(id,action,fingerprint,state,created) VALUES(?,?,?,?,?)',
                               (operation_id, action, fingerprint, 'queued', time.time()))
            self.active = operation_id
            threading.Thread(target=self.execute, args=(operation_id, action, args), daemon=False).start()
        return dict(id=operation_id, state='queued')

    def execute(self, operation_id, action, args):
        try:
            self.store.execute("UPDATE web_operations SET state='running' WHERE id=?", (operation_id,))
            with tempfile.TemporaryDirectory(prefix='stars-web-') as directory:
                if action == 'research':
                    args = dict(args)
                    args['job_id'] = operation_id
                    paths = []
                    for i, image in enumerate(args.pop('attachments', [])):
                        try:
                            data = base64.b64decode(image['data'], validate=True)
                        except ValueError:
                            raise WebError('PNG附件编码无效') from None
                        path = os.path.join(directory, f'attachment-{i+1}.png')
                        with open(path, 'xb') as stream:
                            stream.write(data)
                        png_attachment(path)
                        paths.append(path)
                    args['image_paths'] = paths
                result = self.service.run(action, **args)
            if isinstance(result, dict):
                public = {key: value for key, value in result.items() if key in {'message', 'repo_id'}}
                if 'research_job' in result:
                    public['research_job_id'] = result['research_job']['id']
            else:
                public = dict(message=str(result))
            self.store.execute("UPDATE web_operations SET state='done',result=? WHERE id=?",
                               (json.dumps(public, ensure_ascii=False), operation_id))
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__ + '，请检查设置与运行记录'
            self.store.execute("UPDATE web_operations SET state='failed',error=? WHERE id=?", (message[:500], operation_id))
        finally:
            with self.mutex:
                self.active = None

    def control(self, payload):
        action = payload.get('action')
        args = payload.get('args')
        allowed = {'study_state': {'repo_id', 'state'}, 'research_cancel': {'job_id'},
                   'research_bookmark': {'job_id', 'saved'}, 'research_feedback': {'job_id', 'rating'}}
        if (set(payload) != {'action', 'args'} or not isinstance(action, str) or action not in allowed
                or not isinstance(args, dict) or set(args) != allowed[action]):
            raise WebError('控制操作参数无效')
        if action == 'study_state':
            number(args['repo_id'])
            if args['state'] not in STUDY_STATES:
                raise WebError('研究状态无效')
        else:
            identity(args['job_id'])
        if action == 'research_bookmark' and type(args['saved']) is not bool:
            raise WebError('收藏参数无效')
        if action == 'research_feedback' and args['rating'] not in {'useful', 'irrelevant', 'clear'}:
            raise WebError('反馈参数无效')
        result = self.service.run(action, **args)
        return result if isinstance(result, dict) else dict(message=str(result))


class BrowserServer(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = 'GitHub-Stars'

    def log_message(self, *_args):
        pass  # Never log request bodies, cookies, keys or user questions.

    def reply(self, status, content, content_type='application/json; charset=utf-8', cookie=False, download=False):
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False).encode('utf-8')
        if isinstance(content, str):
            content = content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', f'{self.server.cookie_name}={self.server.session}; HttpOnly; SameSite=Strict; Path=/')
        if download:
            self.send_header('Content-Disposition', f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(content)

    def guard(self, authenticated=True, write=False):
        if self.headers.get('Host') not in self.server.allowed_hosts:
            raise WebError('只接受本机访问地址', 403)
        if authenticated:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
            except Exception:
                raise WebError('浏览器会话无效，请重新打开首页', 403) from None
            value = cookie.get(self.server.cookie_name)
            if not value or not secrets.compare_digest(value.value, self.server.session):
                raise WebError('请先打开网页首页', 403)
        if write:
            if (self.headers.get('Origin') not in self.server.allowed_origins
                    or not secrets.compare_digest(self.headers.get('X-Stars-CSRF', ''), self.server.csrf)):
                raise WebError('操作来源无效，请刷新本机页面', 403)

    def do_GET(self):
        try:
            self.guard(authenticated=False)
            parsed = urlsplit(self.path)
            static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/app.css': ('app.css', 'text/css; charset=utf-8')}
            if parsed.path in static:
                filename, content_type = static[parsed.path]
                return self.reply(200, files('github_stars').joinpath('web_assets', filename).read_bytes(),
                                  content_type, cookie=parsed.path == '/')
            if parsed.path == '/api/health':
                return self.reply(200, dict(application='github-stars', root=hashlib.sha256(
                    str(self.server.app.paths.root).encode()).hexdigest(), version=__version__))
            self.guard()
            app, query = self.server.app, parse_qs(parsed.query)
            if parsed.path == '/api/state':
                result = app.state() | {'csrf': self.server.csrf}
            elif parsed.path == '/api/config':
                result = app.settings()
            elif parsed.path == '/api/project':
                result = app.project(int(query.get('id', ['0'])[0]))
            elif parsed.path == '/api/projects':
                result = app.search_projects(query.get('q', [''])[0])
            elif parsed.path == '/api/research':
                result = app.service.run('research_status', job_id=identity(query.get('id', [''])[0]))
            elif parsed.path == '/api/logs':
                result = app.logs()
            elif parsed.path == '/api/digest':
                result = dict(text=digest_text(app.store, query.get('week', [''])[0]))
            elif parsed.path == '/api/report':
                text = digest_text(app.store, query.get('week', [''])[0])
                kind = query.get('format', ['markdown'])[0]
                if kind not in {'markdown', 'html'}:
                    raise WebError('导出格式无效')
                return self.reply(200, html_document(text) if kind == 'html' else text,
                                  'text/html; charset=utf-8' if kind == 'html' else 'text/markdown; charset=utf-8',
                                  download='github-stars-report.' + ('html' if kind == 'html' else 'md'))
            elif parsed.path == '/api/tutorial':
                return self.reply(200, app.tutorial(int(query.get('id', ['0'])[0])), 'text/html; charset=utf-8',
                                  download='github-stars-tutorial.html')
            else:
                raise WebError('页面不存在', 404)
            self.reply(200, result)
        except (ValueError, RuntimeError) as exc:
            self.reply(getattr(exc, 'status', 400), dict(error=str(exc)))
        except Exception:
            self.reply(500, dict(error='读取失败，请查看本机运行记录'))

    def do_POST(self):
        try:
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise WebError('需要JSON请求')
            length = int(self.headers.get('Content-Length', '-1'))
            if not 0 < length <= 5_500_000:
                raise WebError('请求为空或过大', 413)
            self.connection.settimeout(10)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise WebError('请求不完整')
            self.guard(write=True)  # Drain the bounded body before rejecting, without parsing or acting on it.
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise WebError('JSON格式无效')
            path = urlsplit(self.path).path
            if path == '/api/settings':
                result = self.server.app.save_settings(payload)
            elif path == '/api/action':
                result = self.server.app.submit(payload)
            elif path == '/api/control':
                result = self.server.app.control(payload)
            elif path == '/api/shutdown':
                if payload:
                    raise WebError('关闭操作不接受参数')
                with self.server.app.mutex:
                    if self.server.app.busy:
                        raise WebError('请等待运行中的任务结束，或先停止研究', 409)
                    self.server.app.closing = True
                self.reply(200, dict(message='网页服务已停止，可以关闭此页面。'))
                threading.Thread(target=self.server.owner.close, daemon=True).start()
                return
            else:
                raise WebError('操作不存在', 404)
            self.reply(202 if path == '/api/action' else 200, result)
        except (ValueError, RuntimeError) as exc:
            self.reply(getattr(exc, 'status', 400), dict(error=str(exc)))
        except Exception:
            self.reply(500, dict(error='操作失败，请检查设置和运行记录'))


class WebServer:
    def __init__(self, paths, port=8765, service=None, schedule=True):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('网页端口需要0～65535')
        self.lock = exclusive(paths.data / 'web.lock')
        self.lock.__enter__()
        try:
            self.http = BrowserServer(('127.0.0.1', port), Handler)
            self.http.app = WebApplication(service or Service(paths))
        except Exception:
            if hasattr(self, 'http'):
                self.http.server_close()
            self.lock.__exit__(None, None, None)
            raise
        self.http.session, self.http.csrf = secrets.token_hex(32), secrets.token_hex(32)
        actual_port = self.http.server_port
        self.http.cookie_name = f'stars_session_{actual_port}'
        self.http.allowed_hosts = {f'127.0.0.1:{actual_port}', f'localhost:{actual_port}'}
        self.http.allowed_origins = {'http://' + host for host in self.http.allowed_hosts}
        self.http.owner = self
        self.url = f'http://127.0.0.1:{actual_port}/'
        self.thread = None
        self.closed = False
        self.close_mutex = threading.Lock()
        self.stop_event = threading.Event()
        self.schedule = schedule

    def start(self):
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        self.thread.start()
        record = dict(url=self.url, pid=os.getpid())
        (self.http.app.paths.data / 'web-server.json').write_text(json.dumps(record), encoding='utf-8')
        if self.schedule:
            threading.Thread(target=self.scheduled, daemon=True).start()
        return self.url

    def scheduled(self):
        delay = 3
        while not self.stop_event.wait(delay):
            delay = 60
            try:
                if self.http.app.paths.load()['schedule']['enabled'] and not self.http.app.busy:
                    self.http.app.submit(dict(id=uuid.uuid4().hex, action='tick', args={}), scheduled=True)
            except (ValueError, RuntimeError):
                pass  # Existing task or changed settings; retry on the next scheduled check.

    def close(self):
        with self.close_mutex:
            self._close()

    def _close(self):
        if self.closed:
            return
        with self.http.app.mutex:
            if self.http.app.busy:
                raise WebError('网页任务仍在运行，请等待完成或先停止研究', 409)
            self.http.app.closing = True
            self.stop_event.set()
        if self.thread:
            self.http.shutdown()
            self.thread.join(timeout=2)
            self.thread = None
        self.http.server_close()
        (self.http.app.paths.data / 'web-server.json').unlink(missing_ok=True)
        self.lock.__exit__(None, None, None)
        self.closed = True


def open_browser(url):
    if os.getenv('WSL_DISTRO_NAME') and shutil.which('powershell.exe'):
        subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', 'Start-Process', url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


def existing_server(paths):
    try:
        record = json.loads((paths.data/'web-server.json').read_text())
        url = record['url']
        if not isinstance(url, str) or not re.fullmatch(r'http://127\.0\.0\.1:\d{1,5}/', url):
            return None
        with httpx.Client(timeout=1, trust_env=False) as client:
            response = client.get(url+'api/health')
        expected = hashlib.sha256(str(paths.root).encode()).hexdigest()
        if response.status_code == 200 and response.json().get('root') == expected:
            return url
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        pass
    return None
