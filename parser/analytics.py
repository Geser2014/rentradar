"""
RentRadar -- Модуль аналитики.
Расчёт статистики, дельт, возраста объявлений.
"""

import logging
from datetime import date, timedelta
from statistics import median
from typing import Any

from parser.database import get_price_history

logger = logging.getLogger(__name__)


def calculate_daily_stats(listings: list[dict[str, Any]]) -> dict[str, Any]:
    """Из активных объявлений рассчитать статистику.

    Возвращает: total_count, cian_count, avito_count,
    min_price, max_price, avg_price, median_price.
    """
    if not listings:
        return {
            "total_count": 0,
            "cian_count": 0,
            "avito_count": 0,
            "min_price": None,
            "max_price": None,
            "avg_price": None,
            "median_price": None,
        }

    prices = [l["price"] for l in listings if l.get("price")]
    cian = [l for l in listings if l.get("source") == "cian"]
    avito = [l for l in listings if l.get("source") == "avito"]

    stats = {
        "total_count": len(listings),
        "cian_count": len(cian),
        "avito_count": len(avito),
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "avg_price": round(sum(prices) / len(prices)) if prices else None,
        "median_price": round(median(prices)) if prices else None,
    }

    logger.info(
        "Статистика: %d объявлений (ЦИАН: %d, Авито: %d), "
        "цены: %s - %s, средняя: %s",
        stats["total_count"],
        stats["cian_count"],
        stats["avito_count"],
        stats["min_price"],
        stats["max_price"],
        stats["avg_price"],
    )
    return stats


def calculate_deltas(
    current: dict[str, Any],
    days_ago: int = 7,
    db_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Сравнить текущую статистику с N дней назад.

    Возвращает дельты: min_price, max_price, avg_price, total_count.
    Каждая дельта: {value: int, direction: 'up'|'down'|'neutral'}
    """
    history = get_price_history(days=days_ago + 1, db_path=db_path)

    # Ищем запись ближайшую к days_ago назад
    target_date = (date.today() - timedelta(days=days_ago)).isoformat()
    past_stats = None

    for record in history:
        if record["date"] <= target_date:
            past_stats = record

    def _delta(current_val: int | None, past_val: int | None) -> dict[str, Any]:
        if current_val is None or past_val is None:
            return {"value": 0, "direction": "neutral"}
        diff = current_val - past_val
        if diff > 0:
            direction = "up"
        elif diff < 0:
            direction = "down"
        else:
            direction = "neutral"
        return {"value": diff, "direction": direction}

    if past_stats is None:
        return {
            "min_price": {"value": 0, "direction": "neutral"},
            "max_price": {"value": 0, "direction": "neutral"},
            "avg_price": {"value": 0, "direction": "neutral"},
            "total_count": {"value": 0, "direction": "neutral"},
        }

    return {
        "min_price": _delta(current.get("min_price"), past_stats.get("min_price")),
        "max_price": _delta(current.get("max_price"), past_stats.get("max_price")),
        "avg_price": _delta(current.get("avg_price"), past_stats.get("avg_price")),
        "total_count": _delta(current.get("total_count"), past_stats.get("total_count")),
    }


def calculate_listing_age(first_seen: str) -> dict[str, Any]:
    """Возраст объявления.

    Возвращает {days: int, color: 'green'|'yellow'|'red'}.
    green: 0-7, yellow: 8-15, red: 21+
    """
    try:
        seen_date = date.fromisoformat(first_seen)
        days = (date.today() - seen_date).days
    except (ValueError, TypeError):
        days = 0

    if days <= 7:
        color = "green"
    elif days <= 15:
        color = "yellow"
    else:
        color = "red"

    return {"days": days, "color": color}
