"""
RentRadar — Конфигурация.
Зона парсинга, фильтры, константы, User-Agent ротация.
"""

import os
from pathlib import Path

# ── Пути ──────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = str(BASE_DIR / "data" / "rentradar.db")

# Для разработки — локальная папка; для продакшена — /var/www/rentradar/data/
JSON_OUTPUT_DIR = os.environ.get("RENTRADAR_JSON_DIR", str(BASE_DIR / "dashboard" / "data"))

LOG_DIR = str(BASE_DIR / "logs")
LOG_FILE = str(Path(LOG_DIR) / "rentradar.log")

# ── Зона парсинга ─────────────────────────────────────

ZONE_STREETS: list[str] = [
    "Подольская",
    "Серпуховская",
    "Верейская",
    "Бронницкая",
    "1-я Красноармейская",
    "2-я Красноармейская",
    "3-я Красноармейская",
    "4-я Красноармейская",
    "5-я Красноармейская",
    "Батайский",
    "Дойников",
    "Клинский",
    "Малодетскосельский",
    "Можайская",
    "Рузовская",
]

ZONE_BOUNDS: dict[str, float] = {
    "lat_min": 59.9050,   # Обводный канал
    "lat_max": 59.9220,   # Фонтанка
    "lon_min": 30.3050,   # Измайловский
    "lon_max": 30.3350,   # Рузовская
}

# ── Фильтры поиска ────────────────────────────────────

FILTERS: dict = {
    "room_type": "studio",
    "area_min": 0,
    "area_max": 35,
    "price_min": 5000,
    "price_max": 65000,
    "city": "saint-petersburg",
}

# ── Задержки между запросами ──────────────────────────

REQUEST_DELAY: tuple[int, int] = (3, 7)  # секунды, random.uniform

# ── User-Agent ротация ────────────────────────────────

USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# ── ЦИАН API ──────────────────────────────────────────

CIAN_API_URL = "https://api.cian.ru/search-offers/v2/search-offers-desktop/"

CIAN_PARAMS: dict = {
    "type": "flat",
    "deal_type": "rent",
    "offer_type": "flat",
    "region": 2,        # Санкт-Петербург
    "room1": 0,         # студия
    "minprice": FILTERS["price_min"],
    "maxprice": FILTERS["price_max"],
    "mintarea": FILTERS["area_min"],
    "maxtarea": FILTERS["area_max"],
    "sort": "creation_date_desc",
    "p": 1,
}

CIAN_HEADERS_BASE: dict[str, str] = {
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://spb.cian.ru/",
}

# ── Авито ─────────────────────────────────────────────

AVITO_SEARCH_URL = (
    "https://www.avito.ru/sankt-peterburg/kvartiry/sdam/na_dlitelnyy_srok/"
    "studiya-ASgBAQICAUSSA8gQ8AeQUg"
    "?cd=1"
    "&f=ASgBAQICAUSSA8gQ8AeQUgFAzAgUeyJmcm9tIjo1MDAwLCJ0byI6NjUwMDB9"
    "&s=104"
)

AVITO_MAX_PAGES = 5

# ── Логирование ───────────────────────────────────────

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
