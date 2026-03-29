# RentRadar — CLAUDE.md

## Обзор
Система парсинга Авито + ЦИАН для мониторинга аренды студий в определённом районе СПб.
Парсер (Python) → SQLite → JSON → статический HTML дашборд (nginx).

## Стек
- Python 3.11+, httpx, Playwright, APScheduler, SQLite
- HTML/CSS/JS (vanilla), Chart.js 4
- nginx, systemd timer
- Деплой: Veeps VPS Ubuntu 2GB RAM

## Архитектура
```
Cron 06:00 → cian.py (httpx API) + avito.py (Playwright) → database.py (SQLite)
→ analytics.py → JSON файлы → /var/www/rentradar/ (nginx)
```

## Структура проекта
```
rentradar/
├── CLAUDE.md
├── PROJECT_IDEA.md
├── parser/
│   ├── main.py          — точка входа, оркестратор
│   ├── config.py        — зона, фильтры, константы
│   ├── cian.py          — парсер ЦИАН (httpx + API)
│   ├── avito.py         — парсер Авито (Playwright)
│   ├── database.py      — SQLite модели, CRUD
│   ├── analytics.py     — мин/макс/средняя, дельты
│   ├── json_export.py   — генерация JSON для дашборда
│   └── requirements.txt
├── dashboard/
│   ├── index.html       — единый HTML файл дашборда
│   └── data/            — JSON файлы (генерируются парсером)
├── deploy/
│   ├── rentradar.service
│   ├── rentradar.timer
│   └── nginx.conf
└── .claude/
    ├── settings.json
    └── agents/
```

## Правила
1. Python: typing, docstrings, логирование через logging
2. SQL: параметризованные запросы, никакого f-string в SQL
3. Парсинг: задержки 3-7с между запросами, ротация User-Agent
4. HTML: один файл, Chart.js из CDN, CSS variables из референса
5. Футер HTML: «разработано Gesolutions©»
6. JSON: UTF-8, ensure_ascii=False
7. Все тексты интерфейса на русском

## Фазы
- Фаза 1: SQLite схема + config + database.py
- Фаза 2: ЦИАН парсер (cian.py) + тесты
- Фаза 3: Аналитика + JSON export
- Фаза 4: HTML дашборд (из макета)
- Фаза 5: Авито парсер (Playwright)
- Фаза 6: Деплой (systemd + nginx)

## Контроль контекста (анти context-rot)

### Субагенты:
- Компактный вывод — макс 150 строк на файл
- Только выводы и тезисы, не копируй исходники
- Суммарный объём research < 500 строк

### Синтез:
- Перед синтезом: wc -l на все research-файлы
- Если > 500 строк — сжать каждый до 100 строк
- Читай файлы последовательно, не все сразу
- Промежуточные результаты — сразу на диск

### Чтение:
- > 3 файлов — разбей на шаги
- Большие файлы — только нужный диапазон
- Между шагами — запись на диск

## Permissions

В `.claude/settings.json` прописаны allowedTools:
- Bash(mkdir:*), Bash(cp:*), Bash(wc:*), Bash(cat:*), Bash(python3:*), Bash(pip:*)
- Write, Edit, Read
- Все MCP-серверы проекта

Без этого субагенты зависают на запросе разрешений.
