"""
RentRadar — Модуль базы данных.
SQLite: создание таблиц, upsert объявлений, статистика, история цен.
"""

import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from parser.config import DB_PATH

logger = logging.getLogger(__name__)

# ── Схема ─────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('cian', 'avito')),
    url TEXT NOT NULL,
    address TEXT NOT NULL,
    street TEXT,
    area REAL,
    price INTEGER NOT NULL,
    communal INTEGER,
    counters_included INTEGER DEFAULT 0,
    owner_type TEXT CHECK(owner_type IN ('owner', 'agent', 'unknown')),
    commission INTEGER DEFAULT 0,
    first_seen DATE NOT NULL DEFAULT (date('now')),
    last_seen DATE NOT NULL DEFAULT (date('now')),
    is_active INTEGER DEFAULT 1,
    raw_json TEXT,
    UNIQUE(external_id, source)
);

CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active, source);
CREATE INDEX IF NOT EXISTS idx_listings_street ON listings(street);
CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    price INTEGER NOT NULL,
    recorded_at DATE NOT NULL DEFAULT (date('now')),
    UNIQUE(listing_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_ph_date ON price_history(recorded_at);

CREATE TABLE IF NOT EXISTS daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL UNIQUE,
    total_count INTEGER,
    cian_count INTEGER,
    avito_count INTEGER,
    min_price INTEGER,
    max_price INTEGER,
    avg_price INTEGER,
    median_price INTEGER
);

CREATE INDEX IF NOT EXISTS idx_ds_date ON daily_stats(date);
"""


def _get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Создать подключение к SQLite с настройками."""
    path = db_path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | None = None) -> None:
    """Создать таблицы если не существуют."""
    conn = _get_connection(db_path)
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
        logger.info("База данных инициализирована: %s", db_path or DB_PATH)
    finally:
        conn.close()


def upsert_listing(data: dict[str, Any], db_path: str | None = None) -> int:
    """Вставить или обновить объявление. Вернуть listing_id.

    При обновлении: обновить last_seen, проверить изменение цены.
    Если цена изменилась — записать в price_history.
    """
    conn = _get_connection(db_path)
    try:
        cur = conn.cursor()
        today = date.today().isoformat()

        # Проверяем существующее объявление
        cur.execute(
            "SELECT id, price FROM listings WHERE external_id = ? AND source = ?",
            (data["external_id"], data["source"]),
        )
        existing = cur.fetchone()

        if existing:
            listing_id = existing["id"]
            old_price = existing["price"]

            # Обновить last_seen и поля
            cur.execute(
                """UPDATE listings SET
                    url = ?, address = ?, street = ?, area = ?,
                    price = ?, communal = ?, counters_included = ?,
                    owner_type = ?, commission = ?,
                    last_seen = ?, is_active = 1, raw_json = ?
                WHERE id = ?""",
                (
                    data.get("url", ""),
                    data.get("address", ""),
                    data.get("street"),
                    data.get("area"),
                    data["price"],
                    data.get("communal"),
                    data.get("counters_included", 0),
                    data.get("owner_type", "unknown"),
                    data.get("commission", 0),
                    today,
                    data.get("raw_json"),
                    listing_id,
                ),
            )

            # Если цена изменилась — записать в историю
            if old_price != data["price"]:
                cur.execute(
                    """INSERT OR IGNORE INTO price_history (listing_id, price, recorded_at)
                    VALUES (?, ?, ?)""",
                    (listing_id, data["price"], today),
                )
                logger.info(
                    "Цена изменилась: %s %s → %s",
                    data["external_id"],
                    old_price,
                    data["price"],
                )
        else:
            # Новое объявление
            cur.execute(
                """INSERT INTO listings
                (external_id, source, url, address, street, area,
                 price, communal, counters_included, owner_type, commission,
                 first_seen, last_seen, is_active, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    data["external_id"],
                    data["source"],
                    data.get("url", ""),
                    data.get("address", ""),
                    data.get("street"),
                    data.get("area"),
                    data["price"],
                    data.get("communal"),
                    data.get("counters_included", 0),
                    data.get("owner_type", "unknown"),
                    data.get("commission", 0),
                    today,
                    today,
                    data.get("raw_json"),
                ),
            )
            listing_id = cur.lastrowid

            # Первая запись в историю цен
            cur.execute(
                """INSERT OR IGNORE INTO price_history (listing_id, price, recorded_at)
                VALUES (?, ?, ?)""",
                (listing_id, data["price"], today),
            )
            logger.info("Новое объявление: %s (%s)", data["external_id"], data["source"])

        conn.commit()
        return listing_id
    finally:
        conn.close()


def mark_inactive(source: str, active_ids: list[str], db_path: str | None = None) -> int:
    """Пометить is_active=0 для объявлений source, чьи external_id нет в active_ids.
    Вернуть количество деактивированных.
    """
    conn = _get_connection(db_path)
    try:
        cur = conn.cursor()

        if not active_ids:
            # Все объявления этого источника деактивируются
            cur.execute(
                "UPDATE listings SET is_active = 0 WHERE source = ? AND is_active = 1",
                (source,),
            )
        else:
            placeholders = ",".join("?" * len(active_ids))
            cur.execute(
                f"UPDATE listings SET is_active = 0 "
                f"WHERE source = ? AND is_active = 1 AND external_id NOT IN ({placeholders})",
                [source] + active_ids,
            )

        count = cur.rowcount
        conn.commit()
        if count > 0:
            logger.info("Деактивировано %d объявлений (%s)", count, source)
        return count
    finally:
        conn.close()


def get_active_listings(db_path: str | None = None) -> list[dict]:
    """Все активные объявления, отсортированные по цене."""
    conn = _get_connection(db_path)
    try:
        cur = conn.execute(
            "SELECT * FROM listings WHERE is_active = 1 ORDER BY price ASC"
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def save_daily_stats(stats: dict[str, Any], db_path: str | None = None) -> None:
    """Записать дневную статистику."""
    conn = _get_connection(db_path)
    try:
        today = date.today().isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO daily_stats
            (date, total_count, cian_count, avito_count,
             min_price, max_price, avg_price, median_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                today,
                stats.get("total_count", 0),
                stats.get("cian_count", 0),
                stats.get("avito_count", 0),
                stats.get("min_price"),
                stats.get("max_price"),
                stats.get("avg_price"),
                stats.get("median_price"),
            ),
        )
        conn.commit()
        logger.info("Статистика за %s сохранена", today)
    finally:
        conn.close()


def get_price_history(days: int = 90, db_path: str | None = None) -> list[dict]:
    """История мин/макс/средней цены за N дней."""
    conn = _get_connection(db_path)
    try:
        since = (date.today() - timedelta(days=days)).isoformat()
        cur = conn.execute(
            """SELECT date, min_price, max_price, avg_price
            FROM daily_stats
            WHERE date >= ?
            ORDER BY date ASC""",
            (since,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_supply_history(days: int = 90, db_path: str | None = None) -> list[dict]:
    """История количества объявлений по источникам."""
    conn = _get_connection(db_path)
    try:
        since = (date.today() - timedelta(days=days)).isoformat()
        cur = conn.execute(
            """SELECT date, cian_count, avito_count, total_count
            FROM daily_stats
            WHERE date >= ?
            ORDER BY date ASC""",
            (since,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
