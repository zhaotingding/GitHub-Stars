import copy
import json
import os
import threading
import time
import uuid

import httpx
import pytest
from test_tutorial_html import lesson_fixture
from test_workflow import NOW, FakeGitHub, repository

from github_stars.config import Paths
from github_stars.service import Service
from github_stars.web import SECRET_NAMES, WebApplication, WebServer


class LocalGitHub(FakeGitHub):
    imports = 0

    def repository(self, name):
        type(self).imports += 1
        return repository(1)


@pytest.fixture
def browser(tmp_path, monkeypatch):
    for name in SECRET_NAMES.values():
        monkeypatch.setenv(name, '')
    paths = Paths(tmp_path)
    config = paths.load()
    config['schedule']['enabled'] = False
    paths.save(config)
    service = Service(paths, github_factory=LocalGitHub, clock=lambda: NOW)
    server = WebServer(paths, port=0, service=service)
    server.start()
    client = httpx.Client(base_url=server.url, timeout=5, trust_env=False)
    home = client.get('/')
    assert home.status_code == 200
    token = client.get('/api/state').json()['csrf']
    client.headers.update({'Origin': server.url.rstrip('/'), 'X-Stars-CSRF': token})
    yield server, client
    deadline = time.monotonic()+5
    while server.http.app.busy and time.monotonic() < deadline:
        time.sleep(.01)
    assert not server.http.app.busy
    client.close()
    server.close()


def submit(client, action, args=None, operation_id=None):
    operation_id = operation_id or uuid.uuid4().hex
    result = client.post('/api/action', json=dict(id=operation_id, action=action, args=args or {}))
    assert result.status_code == 202, result.text
    return operation_id


def finished(server, operation_id):
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        row = server.http.app.store.one('SELECT * FROM web_operations WHERE id=?', (operation_id,))
        if row['state'] not in {'queued', 'running'} and not server.http.app.busy:
            return row
        time.sleep(.01)
    raise AssertionError('后台操作未及时完成')


def test_http_assets_utf8_and_loopback_session(browser):
    server, client = browser
    assert server.http.server_address[0] == '127.0.0.1'
    response = client.get('/')
    assert '项目雷达' in response.text and '设置' in response.text
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=Strict' in response.headers['set-cookie']
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    for name, marker in (('/app.js', 'textContent'), ('/app.css', '@media')):
        assert marker in client.get(name).text
    assert client.get('/api/config').json()['config']['web']['port'] == 8765


def test_cross_origin_host_and_uninitialized_browser_are_rejected(browser):
    server, client = browser
    assert client.get('/api/state', headers={'Cookie': ''}).status_code == 403
    assert client.get('/', headers={'Host': 'attacker.invalid'}).status_code == 403
    payload = dict(id=uuid.uuid4().hex, action='scan', args={})
    assert client.post('/api/action', json=payload, headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    assert client.post('/api/action', json=payload, headers={'X-Stars-CSRF': ''}).status_code == 403
    assert not server.http.app.store.rows('SELECT * FROM web_operations')
    assert client.get('/api/../../config.local.yaml').status_code == 404


def test_settings_session_keys_never_return_or_enter_files(browser):
    server, client = browser
    before = client.get('/api/config').json()
    changed = copy.deepcopy(before['config'])
    changed['profile']['description'] = '机器人多模态视觉研究'
    key = 'test-web-session-key'
    response = client.post('/api/settings', json=dict(config=changed, revision=before['revision'], secrets={'openai': key}))
    assert response.status_code == 200
    assert server.http.app.paths.secret('openai', source='local') == key
    assert key not in server.http.app.paths.settings.read_text()
    for route in ('/api/config', '/api/state', '/api/logs'):
        assert key not in client.get(route).text
    assert key not in response.text
    assert server.http.app.paths.load()['profile']['description'] == '机器人多模态视觉研究'


def test_invalid_and_stale_settings_do_not_overwrite_or_change_keys(browser):
    server, client = browser
    before = client.get('/api/config').json()
    invalid = {'config': {'research': {'max_cost_cny': -1.0}}, 'revision': before['revision'],
               'secrets': {'openai': 'test-invalid-key'}}
    assert client.post('/api/settings', json=invalid).status_code == 400
    assert os.environ['OPENAI_API_KEY'] == ''
    config = server.http.app.paths.load()
    config['profile']['description'] = '从桌面保存的新配置'
    server.http.app.paths.save(config)
    assert client.post('/api/settings', json=dict(config=before['config'], revision=before['revision'])).status_code == 409
    assert server.http.app.paths.load()['profile']['description'] == '从桌面保存的新配置'


def test_browser_integer_json_preserves_yaml_float_types(browser):
    server, client = browser
    current = client.get('/api/config').json()
    config = current['config']
    for name, value in config['research'].items():
        if type(value) is float and value.is_integer():
            config['research'][name] = int(value)
    response = client.post('/api/settings', json=dict(config=config, revision=current['revision'], secrets={}))
    assert response.status_code == 200
    assert type(server.http.app.paths.load()['research']['input_cny_per_million']) is float


def test_import_project_state_and_durable_idempotency(browser):
    server, client = browser
    LocalGitHub.imports = 0
    operation_id = submit(client, 'import', {'text': 'https://github.com/owner1/project1'})
    assert finished(server, operation_id)['state'] == 'done'
    assert client.get('/api/project?id=1').json()['readme']
    assert client.get('/api/state').json()['project_count'] == 1
    response = client.post('/api/control', json=dict(action='study_state', args={'repo_id': 1, 'state': 'focus'}))
    assert response.status_code == 200
    assert client.get('/api/project?id=1').json()['study_state'] == 'focus'
    submit(client, 'import', {'text': 'https://github.com/owner1/project1'}, operation_id)
    assert LocalGitHub.imports == 1
    reopened = WebApplication(server.http.app.service)
    assert reopened.submit(dict(id=operation_id, action='import', args={'text': 'https://github.com/owner1/project1'}))['state'] == 'done'
    assert LocalGitHub.imports == 1
    changed = client.post('/api/action', json=dict(id=operation_id, action='scan', args={}))
    assert changed.status_code == 409


def test_busy_worker_keeps_reads_responsive_and_blocks_new_writes(browser, monkeypatch):
    server, client = browser
    entered, release = threading.Event(), threading.Event()
    original = server.http.app.service.run

    def slow(action, **kwargs):
        if action == 'scan':
            entered.set()
            assert release.wait(5)
            return '模拟采集完成'
        return original(action, **kwargs)

    monkeypatch.setattr(server.http.app.service, 'run', slow)
    initial = client.get('/api/config').json()
    operation_id = submit(client, 'scan')
    try:
        assert entered.wait(2)
        assert client.get('/api/state').json()['busy']
        assert client.post('/api/action', json=dict(id=uuid.uuid4().hex, action='scan', args={})).status_code == 409
        assert client.post('/api/settings', json=dict(config=initial['config'], revision=initial['revision'])).status_code == 409
        assert client.post('/api/shutdown', json={}).status_code == 409
        assert not server.closed
        with pytest.raises(ValueError, match='任务仍在运行'):
            server.close()
    finally:
        release.set()
    assert finished(server, operation_id)['state'] == 'done'


def test_standard_empty_research_creates_record_without_model(browser, monkeypatch):
    server, client = browser
    monkeypatch.setattr(server.http.app.service, 'research_client_factory', lambda *_: pytest.fail('没有资料不应调用模型'))
    operation_id = submit(client, 'research', {'question': '哪些项目适合机器人视觉？', 'mode': 'standard'})
    assert finished(server, operation_id)['state'] == 'done'
    job = client.get('/api/research?id='+operation_id).json()
    assert job['state'] == 'empty' and job['calls'] == 0
    assert '未调用模型' in job['error']


@pytest.mark.parametrize('args', [
    {'question': '解释架构图', 'image_paths': ['/etc/passwd']},
    {'question': '解释架构图', 'allow_images': False, 'attachments': [{'data': 'not-base64'}]},
    {'question': '解释架构图', 'allow_images': True, 'attachments': [{'data': '', 'name': '../../outside.png'}]},
])
def test_unapproved_or_path_based_attachments_rejected_before_work(browser, args):
    server, client = browser
    response = client.post('/api/action', json=dict(id=uuid.uuid4().hex, action='research', args=args))
    assert response.status_code == 400
    assert not server.http.app.store.rows('SELECT * FROM web_operations')


def test_invalid_png_does_not_reach_model(browser, monkeypatch):
    server, client = browser
    monkeypatch.setattr(server.http.app.service, 'research_client_factory', lambda *_: pytest.fail('损坏PNG不应调用模型'))
    operation_id = submit(client, 'research', {'question': '解释架构图', 'allow_images': True,
                                              'attachments': [{'data': 'YWJj'}]})
    assert finished(server, operation_id)['state'] == 'failed'
    assert not server.http.app.store.rows('SELECT * FROM research_steps')


def test_no_arbitrary_actions_and_bad_json_are_safe(browser):
    server, client = browser
    for action, args in [('tick', {}), ('shell', {'command': 'whoami'}), ('analysis', {'repo_id': True})]:
        assert client.post('/api/action', json=dict(id=uuid.uuid4().hex, action=action, args=args)).status_code == 400
    assert client.post('/api/action', content='not-json', headers={'Content-Type': 'application/json'}).status_code == 400
    assert not server.http.app.store.rows('SELECT * FROM web_operations')


def test_unknown_operations_not_replayed_after_restart(browser):
    server, client = browser
    app = server.http.app
    operation_id = uuid.uuid4().hex
    app.store.execute("INSERT INTO web_operations(id,action,fingerprint,state,created) VALUES(?,?,?,'running',?)",
                      (operation_id, 'tutorial', 'old', time.time()))
    WebApplication(app.service)
    row = app.store.one('SELECT * FROM web_operations WHERE id=?', (operation_id,))
    assert row['state'] == 'unknown' and '不会自动重新执行' in row['error']


def test_shared_root_only_allows_one_server(browser):
    server, _ = browser
    with pytest.raises(RuntimeError):
        WebServer(server.http.app.paths, port=0)


def test_health_has_no_private_data_and_shutdown_is_authenticated(browser):
    server, client = browser
    response = client.get('/api/health', headers={'Cookie': ''})
    assert response.status_code == 200
    assert set(response.json()) == {'application', 'root', 'version'}
    assert client.post('/api/shutdown', json={}, headers={'X-Stars-CSRF': ''}).status_code == 403
    assert client.post('/api/shutdown', json={}).status_code == 200
    deadline = time.monotonic()+3
    while not server.closed and time.monotonic() < deadline:
        time.sleep(.01)
    assert server.closed
    server.close()


def test_weekly_export_and_explicit_mail_reuse_service(browser, monkeypatch):
    server, client = browser
    submit_id = submit(client, 'scan')
    finished(server, submit_id)
    finished(server, submit(client, 'digest'))
    weeks = client.get('/api/state').json()['digests']
    assert weeks
    week = weeks[0]['week']
    for kind in ('html', 'markdown'):
        response = client.get('/api/report', params={'week': week, 'format': kind})
        assert response.status_code == 200 and 'attachment;' in response.headers['content-disposition']
        assert '周报' in response.text
    seen = []
    original = server.http.app.service.run

    def capture(action, **kwargs):
        if action == 'email':
            seen.append(kwargs)
            return '模拟邮件，不投递'
        return original(action, **kwargs)

    monkeypatch.setattr(server.http.app.service, 'run', capture)
    finished(server, submit(client, 'email', {'week': week, 'retry': False}))
    assert seen == [{'week': week, 'retry': False}]


def test_existing_tutorial_download_never_creates_generation(browser):
    server, client = browser
    assert client.get('/api/tutorial?id=1').status_code == 404
    app = server.http.app
    app.store.upsert(repository(1), 'research', NOW)
    app.store.execute('INSERT INTO ai_jobs(repo_id,week,created,status,model,result,evidence,kind) VALUES(?,?,?,?,?,?,?,?)',
                      (1, '2026-W45', NOW.isoformat(), 'completed', 'test-model',
                       json.dumps(lesson_fixture(), ensure_ascii=False), '{}', 'tutorial'))
    before = app.store.one('SELECT count(*) n FROM ai_jobs')['n']
    response = client.get('/api/tutorial?id=1')
    assert response.status_code == 200, response.text
    assert 'attachment;' in response.headers['content-disposition'] and '<!doctype html>' in response.text.lower()
    assert app.store.one('SELECT count(*) n FROM ai_jobs')['n'] == before


def test_standalone_web_honors_enabled_schedule_without_exposing_tick(browser, monkeypatch):
    server, client = browser
    seen = threading.Event()
    original = server.http.app.service.run

    def scheduled(action, **kwargs):
        if action == 'tick':
            seen.set()
            return '模拟到期检查，不联网'
        return original(action, **kwargs)

    monkeypatch.setattr(server.http.app.service, 'run', scheduled)
    config = server.http.app.paths.load()
    config['schedule']['enabled'] = True
    server.http.app.paths.save(config)
    assert seen.wait(5)
    response = client.post('/api/action', json=dict(id=uuid.uuid4().hex, action='tick', args={}))
    assert response.status_code == 400
