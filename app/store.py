"""SQLite 持久化层：订阅源、分组、文章、设置。

设计要点：
* 单连接 + 可重入锁，抓取线程与 UI 线程共用（写入量小，够用且简单）。
* published 统一存 UTC 字符串 "%Y-%m-%dT%H:%M:%SZ"，字符串排序即时间排序。
* 搜索用 LIKE（中文无需分词），标题优先命中。
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE,
    sort    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feeds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL DEFAULT '',
    site_url    TEXT,
    folder_id   INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    added_at    TEXT,
    last_fetch  TEXT,
    last_status TEXT,
    error       TEXT,
    etag        TEXT,
    modified    TEXT,
    sort        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id      INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid         TEXT NOT NULL,
    title        TEXT NOT NULL DEFAULT '',
    url          TEXT,
    author       TEXT,
    published    TEXT,
    fetched_at   TEXT,
    summary      TEXT,
    content      TEXT,
    content_html TEXT,
    is_read      INTEGER NOT NULL DEFAULT 0,
    is_starred   INTEGER NOT NULL DEFAULT 0,
    full_fetched INTEGER NOT NULL DEFAULT 0,
    UNIQUE(feed_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_articles_feed_pub ON articles(feed_id, published DESC);
CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published DESC);
CREATE INDEX IF NOT EXISTS idx_articles_unread ON articles(is_read, published DESC);
CREATE INDEX IF NOT EXISTS idx_articles_star ON articles(is_starred, published DESC);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

LIST_COLUMNS = ("a.id, a.feed_id, a.title, a.url, a.author, a.published, a.summary, "
                "a.is_read, a.is_starred, a.full_fetched, f.title AS feed_title")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ------------------------------------------------------------------ 基础
    def close(self) -> None:
        with self.lock:
            try:
                self.conn.commit()
                self.conn.close()
            except sqlite3.Error:
                pass

    def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        with self.lock:
            cur = self.conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def _row(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur.lastrowid or 0

    def _execmany(self, sql: str, seq: Iterable[Sequence[Any]]) -> None:
        with self.lock:
            self.conn.executemany(sql, seq)
            self.conn.commit()

    # ------------------------------------------------------------------ 设置
    def settings(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._rows("SELECT key, value FROM settings")}

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._row("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec("INSERT INTO settings(key, value) VALUES(?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def set_settings(self, values: dict[str, str]) -> None:
        self._execmany("INSERT INTO settings(key, value) VALUES(?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       [(k, str(v)) for k, v in values.items()])

    # ------------------------------------------------------------------ 分组
    def folders(self) -> list[dict]:
        return self._rows("SELECT * FROM folders ORDER BY sort, name COLLATE NOCASE")

    def add_folder(self, name: str) -> int:
        name = name.strip()
        row = self._row("SELECT id FROM folders WHERE name=?", (name,))
        if row:
            return int(row["id"])
        return self._exec("INSERT INTO folders(name, sort) VALUES(?, "
                          "(SELECT COALESCE(MAX(sort), 0) + 1 FROM folders))", (name,))

    def rename_folder(self, folder_id: int, name: str) -> None:
        self._exec("UPDATE folders SET name=? WHERE id=?", (name.strip(), folder_id))

    def delete_folder(self, folder_id: int) -> None:
        with self.lock:
            self.conn.execute("UPDATE feeds SET folder_id=NULL WHERE folder_id=?", (folder_id,))
            self.conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
            self.conn.commit()

    # ------------------------------------------------------------------ 订阅源
    def feeds(self) -> list[dict]:
        return self._rows(
            "SELECT f.*, "
            " (SELECT COUNT(*) FROM articles a WHERE a.feed_id=f.id AND a.is_read=0) AS unread, "
            " (SELECT COUNT(*) FROM articles a WHERE a.feed_id=f.id) AS total "
            "FROM feeds f ORDER BY f.folder_id IS NULL, f.folder_id, f.title COLLATE NOCASE")

    def feed(self, feed_id: int) -> dict | None:
        return self._row("SELECT * FROM feeds WHERE id=?", (feed_id,))

    def feed_by_url(self, url: str) -> dict | None:
        return self._row("SELECT * FROM feeds WHERE url=?", (url,))

    def add_feed(self, url: str, title: str = "", site_url: str = "",
                 folder_id: int | None = None) -> int:
        url = url.strip()
        existing = self.feed_by_url(url)
        if existing:
            return int(existing["id"])
        return self._exec(
            "INSERT INTO feeds(url, title, site_url, folder_id, added_at, sort) "
            "VALUES(?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort), 0) + 1 FROM feeds))",
            (url, title.strip(), site_url or None, folder_id, utcnow()))

    def update_feed(self, feed_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {"title", "site_url", "folder_id", "last_fetch", "last_status",
                   "error", "etag", "modified"}
        pairs = [(k, v) for k, v in fields.items() if k in allowed]
        if not pairs:
            return
        sets = ", ".join(f"{k}=?" for k, _ in pairs)
        self._exec(f"UPDATE feeds SET {sets} WHERE id=?", [v for _, v in pairs] + [feed_id])

    def delete_feed(self, feed_id: int) -> None:
        self._exec("DELETE FROM feeds WHERE id=?", (feed_id,))

    def move_feed(self, feed_id: int, folder_id: int | None) -> None:
        self._exec("UPDATE feeds SET folder_id=? WHERE id=?", (folder_id, feed_id))

    # ------------------------------------------------------------------ 文章
    def insert_articles(self, feed_id: int, entries: Iterable[dict]) -> int:
        """批量写入，按 (feed_id, guid) 去重；返回新增条数。"""
        now = utcnow()
        rows = []
        for e in entries:
            rows.append((
                feed_id, e.get("guid") or e.get("url") or "", (e.get("title") or "").strip() or "(无标题)",
                e.get("url") or "", e.get("author") or "", e.get("published") or now,
                now, (e.get("summary") or "")[:4000], e.get("content") or "",
                e.get("content_html") or "", 0, 0, 0,
            ))
        if not rows:
            return 0
        new = 0
        with self.lock:
            cur = self.conn.executemany(
                "INSERT OR IGNORE INTO articles(feed_id, guid, title, url, author, published, "
                "fetched_at, summary, content, content_html, is_read, is_starred, full_fetched) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            new = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            self.conn.commit()
        return new

    def article(self, article_id: int) -> dict | None:
        return self._row(
            "SELECT a.*, f.title AS feed_title, f.site_url AS feed_site FROM articles a "
            "JOIN feeds f ON f.id=a.feed_id WHERE a.id=?", (article_id,))

    def scope_counts(self) -> dict[str, int]:
        row = self._row("SELECT COUNT(*) AS total, SUM(is_read=0) AS unread, "
                        "SUM(is_starred=1) AS starred FROM articles") or {}
        return {"total": int(row.get("total") or 0),
                "unread": int(row.get("unread") or 0),
                "starred": int(row.get("starred") or 0)}

    def unread_by_feed(self) -> dict[int, int]:
        return {int(r["feed_id"]): int(r["n"]) for r in
                self._rows("SELECT feed_id, COUNT(*) AS n FROM articles "
                           "WHERE is_read=0 GROUP BY feed_id")}

    def unread_by_folder(self) -> dict[int, int]:
        return {int(r["folder_id"]): int(r["n"]) for r in self._rows(
            "SELECT f.folder_id AS folder_id, COUNT(*) AS n FROM articles a "
            "JOIN feeds f ON f.id=a.feed_id WHERE a.is_read=0 AND f.folder_id IS NOT NULL "
            "GROUP BY f.folder_id")}

    def _scope_sql(self, scope: tuple[str, int | None]) -> tuple[str, list[Any]]:
        kind, ident = scope
        if kind == "feed":
            return "a.feed_id=?", [ident]
        if kind == "folder":
            return "a.feed_id IN (SELECT id FROM feeds WHERE folder_id=?)", [ident]
        if kind == "unread":
            return "a.is_read=0", []
        if kind == "starred":
            return "a.is_starred=1", []
        return "1=1", []

    def article_list(self, scope: tuple[str, int | None] = ("all", None), *,
                     search: str = "", unread_only: bool = False,
                     limit: int = 200, offset: int = 0) -> list[dict]:
        where, params = self._scope_sql(scope)
        if unread_only:
            where += " AND a.is_read=0"
        if search:
            where += " AND (a.title LIKE ? ESCAPE '\\' OR a.content LIKE ? ESCAPE '\\')"
            like = f"%{search.replace(chr(92), chr(92) * 2).replace('%', chr(92) + '%').replace('_', chr(92) + '_')}%"
            params = params + [like, like]
        sql = (f"SELECT {LIST_COLUMNS} FROM articles a JOIN feeds f ON f.id=a.feed_id "
               f"WHERE {where} ORDER BY a.published DESC, a.id DESC LIMIT ? OFFSET ?")
        return self._rows(sql, params + [int(limit), int(offset)])

    def article_count(self, scope: tuple[str, int | None] = ("all", None), *,
                      search: str = "", unread_only: bool = False) -> int:
        where, params = self._scope_sql(scope)
        if unread_only:
            where += " AND a.is_read=0"
        if search:
            where += " AND (a.title LIKE ? ESCAPE '\\' OR a.content LIKE ? ESCAPE '\\')"
            like = f"%{search.replace(chr(92), chr(92) * 2).replace('%', chr(92) + '%').replace('_', chr(92) + '_')}%"
            params = params + [like, like]
        row = self._row(f"SELECT COUNT(*) AS n FROM articles a JOIN feeds f ON f.id=a.feed_id "
                        f"WHERE {where}", params)
        return int(row["n"]) if row else 0

    def mark_read(self, ids: Sequence[int], value: bool = True) -> None:
        if not ids:
            return
        self._execmany("UPDATE articles SET is_read=? WHERE id=?",
                       [(1 if value else 0, i) for i in ids])

    def mark_all_read(self, scope: tuple[str, int | None] = ("all", None)) -> None:
        where, params = self._scope_sql(scope)
        self._exec(f"UPDATE articles SET is_read=1 WHERE id IN "
                   f"(SELECT a.id FROM articles a JOIN feeds f ON f.id=a.feed_id WHERE {where})", params)

    def toggle_star(self, article_id: int) -> int:
        with self.lock:
            row = self._row("SELECT is_starred FROM articles WHERE id=?", (article_id,))
            if not row:
                return 0
            value = 0 if row["is_starred"] else 1
            self.conn.execute("UPDATE articles SET is_starred=? WHERE id=?", (value, article_id))
            self.conn.commit()
            return int(value)

    def set_full_content(self, article_id: int, html: str, text: str) -> None:
        self._exec("UPDATE articles SET content_html=?, content=?, full_fetched=1 WHERE id=?",
                   (html, text, article_id))

    def prune(self, feed_id: int, keep: int) -> int:
        """每个订阅只保留最近 keep 篇（收藏的永不删除）。"""
        if keep <= 0:
            return 0
        with self.lock:
            cur = self.conn.execute(
                "DELETE FROM articles WHERE feed_id=? AND is_starred=0 AND id NOT IN "
                "(SELECT id FROM articles WHERE feed_id=? ORDER BY published DESC, id DESC LIMIT ?)",
                (feed_id, feed_id, keep))
            self.conn.commit()
            return cur.rowcount or 0

    def vacuum_if_needed(self, max_rows: int = 50000) -> None:
        row = self._row("SELECT COUNT(*) AS n FROM articles")
        if row and int(row["n"]) > max_rows:
            with self.lock:
                self.conn.execute("PRAGMA incremental_vacuum")
                self.conn.commit()

    # ------------------------------------------------------------------ 统计
    def stats(self) -> dict[str, Any]:
        feeds = self._row("SELECT COUNT(*) AS n FROM feeds") or {"n": 0}
        arts = self._row("SELECT COUNT(*) AS n FROM articles") or {"n": 0}
        size = 0
        try:
            size = Path(self.path).stat().st_size
        except OSError:
            pass
        return {"feeds": int(feeds["n"]), "articles": int(arts["n"]), "db_bytes": size}
