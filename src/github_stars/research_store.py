"""项目研究的证据版本、独立任务与逐步结果；不存 API 密钥。"""
from __future__ import annotations

import hashlib
import json
import time

from .research_search import safe_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_documents (
 id INTEGER PRIMARY KEY, repo_id INTEGER NOT NULL, sha TEXT NOT NULL,
 text TEXT NOT NULL, url TEXT NOT NULL, captured TEXT NOT NULL, UNIQUE(repo_id,sha));
CREATE TABLE IF NOT EXISTS research_jobs (
 id TEXT PRIMARY KEY, question TEXT NOT NULL, mode TEXT NOT NULL, created REAL NOT NULL,
 expires REAL NOT NULL, state TEXT NOT NULL, settings TEXT NOT NULL, scope TEXT NOT NULL,
 sources TEXT NOT NULL DEFAULT '[]', organization TEXT NOT NULL DEFAULT '{}',
 result TEXT NOT NULL DEFAULT '{}', trace TEXT NOT NULL DEFAULT '[]',
 tools INTEGER NOT NULL DEFAULT 0, pending_image TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '', cancelled INTEGER NOT NULL DEFAULT 0,
 feedback TEXT NOT NULL DEFAULT '', terms TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS research_steps (
 id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, number INTEGER NOT NULL, kind TEXT NOT NULL,
 state TEXT NOT NULL, prepared TEXT NOT NULL, reserve REAL NOT NULL, created REAL NOT NULL,
 response TEXT NOT NULL DEFAULT '', response_id TEXT NOT NULL DEFAULT '',
 input_tokens INTEGER, output_tokens INTEGER, actual_model TEXT, actual_tier TEXT,
 cost REAL, applied INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
 UNIQUE(job_id,number));
CREATE TABLE IF NOT EXISTS research_bookmarks (
 id TEXT PRIMARY KEY, question TEXT NOT NULL, result TEXT NOT NULL,
 sources TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS research_image_cache (
 fingerprint TEXT PRIMARY KEY, description TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS research_image_claims (
 fingerprint TEXT PRIMARY KEY, step_id INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_research_step_job ON research_steps(job_id,number);
"""

JOB_JSON = {'settings', 'scope', 'sources', 'organization', 'result', 'trace', 'terms'}
JOB_UPDATE = {'state', 'sources', 'organization', 'result', 'trace', 'tools', 'pending_image', 'error', 'cancelled', 'feedback'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def decode_job(row):
    if not row:
        raise ValueError('研究任务不存在或已经到期')
    row = dict(row)
    for name in JOB_JSON:
        row[name] = json.loads(row[name])
    return row


class ResearchStore:
    def cache_readme(self, repo_id, content, sha, url, captured):
        """保存新旧 README 的可追溯版本；采集时间不是作者提交时间。"""
        with self.connect() as db:
            old = db.execute('SELECT * FROM repos WHERE id=?', (repo_id,)).fetchone()
            if not old:
                raise ValueError('需要先保存项目，再缓存README')
            def version_sha(text, supplied):
                if supplied:
                    return supplied
                archived = db.execute('SELECT sha FROM research_documents WHERE repo_id=? AND text=? ORDER BY id LIMIT 1',
                                      (repo_id, text)).fetchone()
                return archived['sha'] if archived else 'local:' + hashlib.sha256(text.encode()).hexdigest()
            if old and old['readme'].strip():
                old_sha = version_sha(old['readme'], old['readme_sha'])
                db.execute('INSERT OR IGNORE INTO research_documents(repo_id,sha,text,url,captured) VALUES(?,?,?,?,?)',
                           (repo_id, old_sha, old['readme'], old['readme_url'], old['readme_at'] or old['seen_at']))
            db.execute('UPDATE repos SET readme=?,readme_sha=?,readme_url=?,readme_at=? WHERE id=?',
                       (content, sha, url, captured, repo_id))
            if content.strip():
                identity = version_sha(content, sha)
                db.execute('INSERT OR IGNORE INTO research_documents(repo_id,sha,text,url,captured) VALUES(?,?,?,?,?)',
                           (repo_id, identity, content, url, captured))

    def research_job(self, identity):
        return decode_job(self.one('SELECT * FROM research_jobs WHERE id=? AND expires>?', (identity, time.time())))

    def research_update(self, identity, **values):
        if not values or not values.keys() <= JOB_UPDATE:
            raise ValueError('无效的研究任务更新')
        assignments = ','.join("state=CASE WHEN cancelled=1 THEN 'cancelled' ELSE ? END" if key == 'state' else f'{key}=?' for key in values)
        self.execute('UPDATE research_jobs SET ' + assignments + ' WHERE id=? AND expires>?',
                     tuple(encode(value) if key in JOB_JSON else value for key, value in values.items()) + (identity, time.time()))

    def research_steps(self, identity):
        rows = self.rows('SELECT * FROM research_steps WHERE job_id=? ORDER BY number', (identity,))
        for row in rows:
            row['prepared'] = json.loads(row['prepared'])
        return rows

    def research_apply(self, identity, step, **values):
        if not values or not values.keys() <= JOB_UPDATE:
            raise ValueError('无效的研究结果应用')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT cancelled FROM research_jobs WHERE id=? AND expires>?', (identity, time.time())).fetchone()
            pending = db.execute('SELECT state,applied FROM research_steps WHERE id=? AND job_id=?', (step, identity)).fetchone()
            if not job or not pending:
                raise ValueError('研究任务或步骤不存在或已经到期')
            if pending['applied']:
                return
            if pending['state'] != 'received':
                raise ValueError('只能应用已经收到的原步骤')
            # 与停止操作争用同一写锁；迟到的回答不恢复任务或推进工具。
            if job['cancelled']:
                values = {'state': 'cancelled'}
            db.execute('UPDATE research_jobs SET ' + ','.join(f'{key}=?' for key in values) + ' WHERE id=?',
                       tuple(encode(value) if key in JOB_JSON else value for key, value in values.items()) + (identity,))
            db.execute('UPDATE research_steps SET applied=1 WHERE id=?', (step,))

    def research_prune(self):
        with self.connect() as db:
            now = time.time()
            db.execute('DELETE FROM research_image_claims WHERE step_id IN '
                       "(SELECT id FROM research_steps WHERE (state IN ('prepared','failed') OR applied=1) AND job_id IN "
                       '(SELECT id FROM research_jobs WHERE expires<=?))', (now,))
            # 保留周归属和用量账目，删除冻结原文、图片输入、模型响应。
            db.execute("UPDATE research_steps SET prepared=CASE WHEN json_valid(prepared) "
                       "THEN json_object('week',json_extract(prepared,'$.week')) ELSE '{}' END,response='' WHERE job_id IN "
                       '(SELECT id FROM research_jobs WHERE expires<=?)', (now,))
            db.execute('DELETE FROM research_jobs WHERE expires<=?', (now,))

    def research_interrupt(self):
        # Service 已取得跨进程业务锁，遗留 running/submitting 不会是另一个活跃业务任务。
        self.research_prune()
        self.execute("UPDATE research_steps SET state='unknown',error='执行曾中断，未自动重发' WHERE state='submitting'")
        for job in self.rows("SELECT id FROM research_jobs WHERE state='running'"):
            pending = next((s for s in self.research_steps(job['id']) if not s['applied']), None)
            state = ('continuable' if not pending or pending['state'] == 'prepared' else
                     'paused' if pending['response'] or pending['response_id'] else 'blocked')
            self.research_update(job['id'], state=state, error='执行曾中断，请先取回原步骤或明确继续')

    def research_cancel(self, identity):
        job = self.research_job(identity)
        if job['state'] not in {'done', 'empty', 'failed', 'limited', 'cancelled'}:
            self.research_update(identity, cancelled=1, state='cancelled', error='停止后续步骤；已提交的费用不能撤销')
        return self.research_public(identity)

    def research_public(self, identity):
        raw = self.one('SELECT id,question,mode,state,created,sources,organization,result,trace,error,feedback,cancelled,'
                       "CAST(json_extract(settings,'$.deadline') AS REAL) deadline FROM research_jobs WHERE id=? AND expires>?",
                       (identity, time.time()))
        if not raw:
            saved = self.one('SELECT * FROM research_bookmarks WHERE id=?', (identity,))
            if not saved:
                raise ValueError('研究任务不存在或已经到期')
            return {**saved, 'result': json.loads(saved['result']), 'sources': json.loads(saved['sources']),
                    'state': 'archived', 'saved': True, 'trace': [], 'organization': {}, 'calls': 0,
                    'can_resume': False, 'can_continue': False, 'error': '收藏只保留答案与来源位置，原文需重新核对'}
        job = dict(raw)
        for key in ('sources', 'organization', 'result', 'trace'):
            job[key] = json.loads(job[key])
        # 状态展示不读取 prepared 中的图片/base64、配置与原始模型响应。
        steps = self.rows("SELECT applied,reserve,response<>'' has_response,response_id<>'' has_response_id "
                          'FROM research_steps WHERE job_id=? ORDER BY number', (identity,))
        pending = next((s for s in steps if not s['applied']), None)
        return {key: job[key] for key in ('id', 'question', 'mode', 'state', 'created', 'sources', 'organization',
                                         'result', 'trace', 'error', 'feedback')} | {
            'calls': len(steps), 'reserved_cny': sum(s['reserve'] for s in steps),
            'saved': self.one('SELECT id FROM research_bookmarks WHERE id=?', (identity,)) is not None,
            'can_resume': bool(pending and (pending['has_response'] or pending['has_response_id'])),
            'can_continue': bool(job['state'] == 'continuable' and not job['cancelled'] and job['deadline'] and time.time() < job['deadline'])}

    def research_bookmark(self, identity, saved):
        if type(saved) is not bool:
            raise ValueError('请明确收藏或取消收藏')
        if not saved:
            self.execute('DELETE FROM research_bookmarks WHERE id=?', (identity,))
            if not self.one('SELECT id FROM research_jobs WHERE id=? AND expires>?', (identity, time.time())):
                return {'id': identity, 'state': 'deleted', 'saved': False, 'can_resume': False, 'can_continue': False}
        else:
            job = self.research_job(identity)
            if job['state'] != 'done':
                raise ValueError('只能收藏已完成的回答')
            fields = ('label', 'name', 'url', 'sha', 'captured', 'kind')
            pointers = [{k: source.get(k, '') for k in fields} for source in job['sources']]
            for source in pointers:
                source['url'] = safe_url(source['url'])
            self.execute('INSERT OR REPLACE INTO research_bookmarks VALUES(?,?,?,?,?)',
                         (identity, job['question'], encode(job['result']), encode(pointers), time.time()))
        return self.research_public(identity)

    def research_feedback(self, identity, rating):
        if rating not in {'useful', 'irrelevant', 'clear'}:
            raise ValueError('反馈只能为 useful、irrelevant 或 clear')
        job = self.research_job(identity)
        if job['state'] != 'done':
            raise ValueError('请在回答完成后反馈')
        self.research_update(identity, feedback='' if rating == 'clear' else rating)
        return self.research_public(identity)
