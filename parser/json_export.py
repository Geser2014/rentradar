"""
RentRadar -- Генерация JSON для дашборда.
Экспорт current.json, stats.json, history.json.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from parser.analytics import calculate_daily_stats, calculate_deltas, calculate_listing_age
from parser.config import DB_PATH, JSON_OUTPUT_DIR
from parser.database import get_active_listings, get_price_history, get_supply_history

logger = logging.getLogger(__name__)


def _write_json(data: Any, filepath: str) -> None:
    """Записать JSON файл с UTF-8."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("JSON записан: %s", filepath)


def export_current(listings: list[dict[str, Any]], output_dir: str) -> None:
    """Экспорт current.json -- текущие объявления."""
    items = []
    for listing in listings:
        age = calculate_listing_age(listing.get("first_seen", ""))
        items.append({
            "id": listing.get("id"),
            "address": listing.get("address", ""),
            "area": listing.get("area"),
            "price": listing.get("price"),
            "communal": listing.get("communal"),
            "counters_included": bool(listing.get("counters_included", 0)),
            "owner_type": listing.get("owner_type", "unknown"),
            "source": listing.get("source", ""),
            "url": listing.get("url", ""),
            "days_active": age["days"],
            "age_color": age["color"],
        })

    data = {
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "count": len(items),
        "listings": items,
    }
    _write_json(data, str(Path(output_dir) / "current.json"))


def export_stats(
    stats: dict[str, Any],
    deltas: dict[str, dict[str, Any]],
    output_dir: str,
) -> None:
    """Экспорт stats.json -- сводка с дельтами."""
    data = {
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "current": {
            "min_price": stats.get("min_price"),
            "max_price": stats.get("max_price"),
            "avg_price": stats.get("avg_price"),
            "total_count": stats.get("total_count", 0),
        },
        "deltas": deltas,
    }
    _write_json(data, str(Path(output_dir) / "stats.json"))


def export_history(
    price_history: list[dict],
    supply_history: list[dict],
    output_dir: str,
) -> None:
    """Экспорт history.json -- история для графиков."""
    data = {
        "price_history": [
            {
                "date": row["date"],
                "min": row.get("min_price"),
                "avg": row.get("avg_price"),
                "max": row.get("max_price"),
            }
            for row in price_history
        ],
        "supply_history": [
            {
                "date": row["date"],
                "cian": row.get("cian_count", 0),
                "avito": row.get("avito_count", 0),
                "total": row.get("total_count", 0),
            }
            for row in supply_history
        ],
    }
    _write_json(data, str(Path(output_dir) / "history.json"))


def export_all(db_path: str | None = None, output_dir: str | None = None) -> None:
    """Главная функция: собирает всё и экспортирует 3 JSON файла."""
    db = db_path or DB_PATH
    out = output_dir or JSON_OUTPUT_DIR

    # Текущие объявления
    listings = get_active_listings(db)
    export_current(listings, out)

    # Статистика + дельты
    stats = calculate_daily_stats(listings)
    deltas = calculate_deltas(stats, days_ago=7, db_path=db)
    export_stats(stats, deltas, out)

    # История
    price_hist = get_price_history(days=90, db_path=db)
    supply_hist = get_supply_history(days=90, db_path=db)
    export_history(price_hist, supply_hist, out)

    logger.info(
        "Экспорт завершён: %d объявлений, output=%s",
        len(listings), out,
    )
