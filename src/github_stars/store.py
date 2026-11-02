from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, metadata TEXT NOT NULL, bucket TEXT NOT NULL,
 seen_at TEXT NOT NULL, readme TEXT NOT NULL DEFAULT '', readme_sha TEXT NOT NULL DEFAULT '',
 readme_url TEXT NOT NULL DEFAULT '', readme_at TEXT, score REAL NOT NULL DEFAULT 0,
 reasons TEXT NOT NULL DEFAULT '[]', feedback TEXT NOT NULL DEFAULT 'new');
CREATE TABLE IF NOT EXISTS snapshots (
 repo_id INTEGER NOT NULL, day TEXT NOT NULL, stars INTEGER NOT NULL, PRIMARY KEY(repo_id,day));
CREATE TABLE IF NOT EXISTS scans (
 id INTEGER PRIMARY KEY, started TEXT NOT NULL, status TEXT NOT NULL, count INTEGER DEFAULT 0, detail TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS digests (
 week TEXT PRIMARY KEY, created TEXT NOT NULL, note TEXT NOT NULL, mail_state TEXT NOT NULL DEFAULT 'pending',
 mail_detail TEXT NOT NULL DEFAULT '', mail_attempt TEXT);
CREATE TABLE IF NOT EXISTS selections (
 week TEXT NOT NULL, repo_id INTEGER NOT NULL, position INTEGER NOT NULL, snapshot TEXT NOT NULL,
 PRIMARY KEY(week,repo_id), FOREIGN KEY(week) REFERENCES digests(week));
CREATE TABLE IF NOT EXISTS ai_jobs (
 id INTEGER PRIMARY KEY, repo_id INTEGER NOT NULL, week TEXT NOT NULL, created TEXT NOT NULL,
 status TEXT NOT NULL, model TEXT NOT NULL, response_id TEXT, result TEXT, error TEXT,
 input_tokens INTEGER, output_tokens INTEGER, evidence TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, created TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL);
PRAGMA user_version=1;
"""


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("此数据库来自更新版本，请使用匹配的程序")
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)  # 每个线程独立连接。
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).lastrowid

    def state(self, key, default=""):
        row = self.one("SELECT value FROM state WHERE key=?", (key,))
        return row["value"] if row else default

    def set_state(self, key, value):
        self.execute("INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def upsert(self, repo, bucket, now):
        with self.connect() as db:
            db.execute("""INSERT INTO repos(id,name,metadata,bucket,seen_at) VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,metadata=excluded.metadata,
                seen_at=excluded.seen_at,bucket=CASE WHEN repos.bucket='research' THEN 'research' ELSE excluded.bucket END""",
                       (repo["id"], repo["full_name"], json.dumps(repo, ensure_ascii=False), bucket, now.isoformat()))
            db.execute("INSERT INTO snapshots VALUES (?,?,?) ON CONFLICT(repo_id,day) DO UPDATE SET stars=excluded.stars",
                       (repo["id"], now.date().isoformat(), repo["stargazers_count"]))

    def event(self, now, level, message):
        self.execute("INSERT INTO events(created,level,message) VALUES (?,?,?)", (now.isoformat(), level, message))


@contextmanager
def exclusive(path):
    file = open(path, "a+b")  # 操作系统锁随进程退出释放，不依赖易过期的 PID 文件。
    file.seek(0, 2)
    if file.tell() == 0:
        file.write(b"0")
        file.flush()
    file.seek(0)
    import os
    if os.name == "nt":
        import msvcrt
        def lock():
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)

        def unlock():
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        def lock():
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def unlock():
            fcntl.flock(file, fcntl.LOCK_UN)
    try:
        try:
            lock()
        except OSError:
            raise RuntimeError("另一个采集／生成任务正在运行，请稍后刷新") from None
        try:
            yield
        finally:
            file.seek(0)
            unlock()
    finally:
        file.close()
