# RentRadar — Техническая спецификация

## Модуль 1: Конфигурация (config.py)

### Константы
```python
ZONE_STREETS = [
    "Подольская", "Серпуховская", "Верейская", "Бронницкая",
    "1-я Красноармейская", "2-я Красноармейская", "3-я Красноармейская",
    "4-я Красноармейская", "5-я Красноармейская",
    "Батайский", "Дойников", "Клинский", "Малодетскосельский",
    "Можайская", "Рузовская"
]

ZONE_BOUNDS = {
    "lat_min": 59.9050,  # Обводный канал
    "lat_max": 59.9220,  # Фонтанка
    "lon_min": 30.3050,  # Измайловский
    "lon_max": 30.3350   # Рузовская
}

FILTERS = {
    "room_type": "studio",
    "area_min": 0,
    "area_max": 35,
    "price_min": 5000,
    "price_max": 65000,
    "city": "saint-petersburg"
}

DB_PATH = "data/rentradar.db"
JSON_OUTPUT_DIR = "/var/www/rentradar/data/"
# Для разработки: JSON_OUTPUT_DIR = "dashboard/data/"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...",
    # ... минимум 10 штук
]

REQUEST_DELAY = (3, 7)  # секунды, random.uniform
```

## Модуль 2: База данных (database.py)

### Таблица: listings
```sql
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
CREATE INDEX idx_listings_active ON listings(is_active, source);
CREATE INDEX idx_listings_street ON listings(street);
CREATE INDEX idx_listings_price ON listings(price);
```

### Таблица: price_history
```sql
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    price INTEGER NOT NULL,
    recorded_at DATE NOT NULL DEFAULT (date('now')),
    UNIQUE(listing_id, recorded_at)
);
CREATE INDEX idx_ph_date ON price_history(recorded_at);
```

### Таблица: daily_stats
```sql
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
CREATE INDEX idx_ds_date ON daily_stats(date);
```

### Функции database.py
```python
def init_db() -> None
    """Создать таблицы если не существуют."""

def upsert_listing(data: dict) -> int
    """Вставить или обновить объявление. Вернуть listing_id.
    При обновлении: обновить last_seen, проверить изменение цены.
    Если цена изменилась — записать в price_history."""

def mark_inactive(source: str, active_ids: list[str]) -> int
    """Пометить is_active=0 для объявлений source, 
    чьи external_id нет в active_ids. Вернуть кол-во деактивированных."""

def get_active_listings() -> list[dict]
    """Все активные объявления, отсортированные по цене."""

def save_daily_stats(stats: dict) -> None
    """Записать дневную статистику."""

def get_price_history(days: int = 90) -> list[dict]
    """История мин/макс/средней цены за N дней."""

def get_supply_history(days: int = 90) -> list[dict]
    """История количества объявлений по источникам."""
```

## Модуль 3: Парсер ЦИАН (cian.py)

### Стратегия
ЦИАН имеет JSON API, используемый фронтендом. Эндпоинт:
```
GET https://api.cian.ru/search-offers/v2/search-offers-desktop/
```

### Параметры запроса
```python
params = {
    "type": "flat",
    "deal_type": "rent",
    "offer_type": "flat",
    "region": 2,  # СПб
    "room1": 0,   # студия
    "minprice": 5000,
    "maxprice": 65000,
    "mintarea": 0,
    "maxtarea": 35,
    "sort": "creation_date_desc",
    "p": 1  # страница
}
```

### Функции
```python
async def fetch_cian_listings() -> list[dict]
    """Получить все объявления с ЦИАН.
    1. Запросить первую страницу → узнать total
    2. Пагинация по всем страницам (задержка между запросами)
    3. Фильтрация по зоне (ZONE_STREETS / ZONE_BOUNDS)
    4. Нормализация в формат upsert_listing
    """

def parse_cian_offer(offer: dict) -> dict
    """Извлечь из JSON ответа ЦИАН:
    - external_id: offer['cianId']
    - url: offer['fullUrl']
    - address: из offer['geo']['address']
    - street: нормализованное название улицы
    - area: offer['totalArea']
    - price: offer['bargainTerms']['priceRur']
    - communal: из offer['bargainTerms'] если есть
    - owner_type: 'owner' если offer['isFromAgent']==False, иначе 'agent'
    - commission: offer['bargainTerms']['agentFee'] если есть
    """

def is_in_zone(address_parts: list) -> bool
    """Проверить что адрес попадает в ZONE_STREETS."""
```

### Заголовки
```python
headers = {
    "User-Agent": random.choice(USER_AGENTS),
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://spb.cian.ru/",
}
```

### Обработка ошибок
- HTTP 429 → ждать 60с, повторить
- HTTP 403 → логировать, пропустить
- Таймаут → 3 попытки с экспоненциальной задержкой
- Невалидный JSON → логировать, пропустить страницу

## Модуль 4: Парсер Авито (avito.py)

### Стратегия
Playwright headless Chromium. Загрузка страницы поиска, извлечение данных из DOM.

### URL
```
https://www.avito.ru/sankt-peterburg/kvartiry/sdam/na_dlitelnyy_srok/studiya-ASgBAQICAUSSA8gQ8AeQUg?cd=1&f=ASgBAQICAUSSA8gQ8AeQUgFAzAgUeyJmcm9tIjo1MDAwLCJ0byI6NjUwMDB9&s=104
```
Параметры кодируются в URL (студия, долгосрок, ценовой диапазон).

### Функции
```python
async def fetch_avito_listings() -> list[dict]
    """Получить все объявления с Авито.
    1. Запустить Playwright Chromium (headless)
    2. Загрузить страницу поиска
    3. Прокрутить до конца для подгрузки
    4. Извлечь данные из DOM-элементов
    5. Пагинация через ?p=N
    6. Фильтрация по зоне
    7. Нормализация
    """

async def parse_avito_page(page) -> list[dict]
    """Извлечь из DOM:
    - external_id: из data-item-id или URL
    - url: href ссылки объявления (полный)
    - address: из блока адреса
    - street: нормализовать
    - area: из описания (парсинг текста "XX м²")
    - price: из блока цены (убрать пробелы, "₽")
    - communal: если указано отдельно
    - owner_type: из бейджа "Собственник" / по умолчанию 'unknown'
    """

def normalize_street(raw_address: str) -> str | None
    """Извлечь и нормализовать название улицы из адреса.
    'Россия, Санкт-Петербург, Подольская ул., 38' → 'Подольская'
    Если улица не в ZONE_STREETS → None (вне зоны)."""
```

### Anti-bot
- User-Agent ротация
- Random delay 3-7с между страницами
- Viewport 1920x1080
- Locale ru-RU
- Не более 5 страниц за сессию
- При капче → логировать, прервать

## Модуль 5: Аналитика (analytics.py)

### Функции
```python
def calculate_daily_stats(listings: list[dict]) -> dict
    """Из активных объявлений рассчитать:
    - total_count, cian_count, avito_count
    - min_price, max_price, avg_price, median_price
    """

def calculate_deltas(current: dict, days_ago: int = 7) -> dict
    """Сравнить текущую статистику с N дней назад.
    Вернуть дельты: min_delta, max_delta, avg_delta, count_delta.
    Каждая дельта: {value: int, direction: 'up'|'down'|'neutral'}
    """

def calculate_listing_age(first_seen: str) -> dict
    """Вернуть {days: int, color: 'green'|'yellow'|'red'}.
    green: 0-7, yellow: 8-15, red: 21+
    """
```

## Модуль 6: JSON Export (json_export.py)

### Выходные файлы

**current.json** — текущие объявления
```json
{
  "updated_at": "2026-03-29T06:00:00",
  "count": 47,
  "listings": [
    {
      "id": 1,
      "address": "Подольская ул., 38",
      "area": 22,
      "price": 25000,
      "communal": 3500,
      "counters_included": false,
      "owner_type": "owner",
      "source": "cian",
      "url": "https://spb.cian.ru/rent/flat/123456/",
      "days_active": 5,
      "age_color": "green"
    }
  ]
}
```

**stats.json** — сводка с дельтами
```json
{
  "updated_at": "2026-03-29T06:00:00",
  "current": {
    "min_price": 18500,
    "max_price": 58000,
    "avg_price": 32400,
    "total_count": 47
  },
  "deltas": {
    "min_price": {"value": -1500, "direction": "down"},
    "max_price": {"value": 3000, "direction": "up"},
    "avg_price": {"value": 800, "direction": "up"},
    "total_count": {"value": 0, "direction": "neutral"}
  }
}
```

**history.json** — история для графиков
```json
{
  "price_history": [
    {"date": "2026-03-01", "min": 19200, "avg": 31800, "max": 54000}
  ],
  "supply_history": [
    {"date": "2026-03-01", "cian": 25, "avito": 22, "total": 47}
  ]
}
```

### Функции
```python
def export_current(listings: list[dict], output_dir: str) -> None
def export_stats(stats: dict, deltas: dict, output_dir: str) -> None
def export_history(price_history: list, supply_history: list, output_dir: str) -> None
def export_all(db_path: str, output_dir: str) -> None
    """Главная функция: собирает всё и экспортирует."""
```

## Модуль 7: Оркестратор (main.py)

```python
async def run_daily():
    """Ежедневный запуск:
    1. init_db()
    2. cian_listings = await fetch_cian_listings()
    3. Для каждого: upsert_listing(l)
    4. mark_inactive('cian', [l['external_id'] for l in cian_listings])
    5. avito_listings = await fetch_avito_listings()
    6. Для каждого: upsert_listing(l)
    7. mark_inactive('avito', [l['external_id'] for l in avito_listings])
    8. all_active = get_active_listings()
    9. stats = calculate_daily_stats(all_active)
    10. save_daily_stats(stats)
    11. export_all(DB_PATH, JSON_OUTPUT_DIR)
    12. Логировать итоги
    """
```

Обработка ошибок: если один парсер упал — второй всё равно работает.
Логирование: файл `logs/rentradar.log`, ротация по дням.

## Модуль 8: Дашборд (index.html)

Единый HTML файл. Загружает JSON из `data/` через fetch().
Макет утверждён (dashboard.html) — 4 блока:
1. Сводка — 4 карточки из stats.json
2. График цен — Chart.js линейный из history.json, табы период + шаг
3. Таблица — из current.json, сортируемая, бейджи, активные ссылки
4. График предложения — Chart.js столбчатый stacked, табы шаг

Дизайн: тёмная тема из референса (CSS variables).
Футер: «разработано Gesolutions©»

## Модуль 9: Деплой

### systemd timer
```ini
# /etc/systemd/system/rentradar.service
[Unit]
Description=RentRadar daily parser
After=network.target

[Service]
Type=oneshot
User=www-data
WorkingDirectory=/opt/rentradar
ExecStart=/opt/rentradar/venv/bin/python3 parser/main.py
StandardOutput=append:/var/log/rentradar.log
StandardError=append:/var/log/rentradar.log

# /etc/systemd/system/rentradar.timer
[Unit]
Description=RentRadar daily at 06:00

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### nginx
```nginx
server {
    listen 80;
    server_name rentradar.example.com;
    root /var/www/rentradar;
    index index.html;

    location /data/ {
        add_header Cache-Control "no-cache";
        add_header Access-Control-Allow-Origin "*";
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

### Установка на VPS
```bash
# 1. Создать структуру
sudo mkdir -p /opt/rentradar /var/www/rentradar/data
# 2. Скопировать файлы
# 3. Виртуальное окружение
cd /opt/rentradar && python3 -m venv venv
source venv/bin/activate
pip install -r parser/requirements.txt
playwright install chromium --with-deps
# 4. Первый запуск
python3 parser/main.py
# 5. Активировать таймер
sudo systemctl enable --now rentradar.timer
# 6. nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/rentradar
sudo ln -s /etc/nginx/sites-available/rentradar /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Крайние случаи

1. **Нет объявлений** → дашборд показывает "Нет данных", графики пустые
2. **Парсер Авито заблокирован** → логировать, продолжить с ЦИАН
3. **ЦИАН сменил API** → fallback на Playwright (как Авито)
4. **Дубли** → UNIQUE(external_id, source) + дедупликация по адрес+цена
5. **Объявление снято** → mark_inactive, не удалять из БД
6. **Цена изменилась** → записать в price_history, обновить в listings
7. **Нет интернета** → retry 3 раза, логировать, выйти без обновления JSON
8. **Первый запуск (пустая БД)** → дельты = neutral, графики пустые
