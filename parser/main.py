"""
RentRadar -- Точка входа, оркестратор.
Ежедневный запуск парсинга, аналитики и экспорта JSON.
"""

import asyncio
import logging
import sys
from pathlib import Path

from parser.analytics import calculate_daily_stats
from parser.cian import fetch_cian_listings
from parser.config import DB_PATH, JSON_OUTPUT_DIR, LOG_DIR, LOG_FILE, LOG_FORMAT, LOG_DATE_FORMAT
from parser.database import (
    get_active_listings,
    init_db,
    mark_inactive,
    save_daily_stats,
    upsert_listing,
)
from parser.json_export import export_all


def setup_logging() -> None:
    """Настройка логирования: файл + stdout."""
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Файл
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(file_handler)

    # Stdout
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(stream_handler)


logger = logging.getLogger(__name__)


async def run_daily() -> None:
    """Ежедневный запуск:
    1. Инициализация БД
    2. Парсинг ЦИАН
    3. Парсинг Авито (если доступен)
    4. Аналитика
    5. Экспорт JSON
    """
    logger.info("=" * 50)
    logger.info("RentRadar: начало ежедневного парсинга")
    logger.info("=" * 50)

    # 1. Инициализация БД
    init_db()

    # 2. Парсинг ЦИАН
    cian_listings: list[dict] = []
    try:
        cian_listings = await fetch_cian_listings()
        for listing in cian_listings:
            upsert_listing(listing)
        mark_inactive("cian", [l["external_id"] for l in cian_listings])
        logger.info("ЦИАН: обработано %d объявлений", len(cian_listings))
    except Exception as e:
        logger.error("ЦИАН: ошибка парсера: %s", e, exc_info=True)

    # 3. Парсинг Авито
    avito_listings: list[dict] = []
    try:
        from parser.avito import fetch_avito_listings
        avito_listings = await fetch_avito_listings()
        for listing in avito_listings:
            upsert_listing(listing)
        mark_inactive("avito", [l["external_id"] for l in avito_listings])
        logger.info("Авито: обработано %d объявлений", len(avito_listings))
    except ImportError:
        logger.info("Авито: модуль avito.py не найден, пропускаем")
    except Exception as e:
        logger.error("Авито: ошибка парсера: %s", e, exc_info=True)

    # 4. Аналитика
    all_active = get_active_listings()
    stats = calculate_daily_stats(all_active)
    save_daily_stats(stats)

    # 5. Экспорт JSON
    export_all(DB_PATH, JSON_OUTPUT_DIR)

    # Итоги
    total = len(cian_listings) + len(avito_listings)
    logger.info("=" * 50)
    logger.info(
        "RentRadar: завершено. ЦИАН: %d, Авито: %d, Всего активных: %d",
        len(cian_listings), len(avito_listings), len(all_active),
    )
    logger.info("=" * 50)


def main() -> None:
    """Точка входа."""
    setup_logging()
    asyncio.run(run_daily())


if __name__ == "__main__":
    main()
