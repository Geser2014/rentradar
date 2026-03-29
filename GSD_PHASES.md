# RentRadar — GSD План фаз

> **ПРАВИЛО**: Claude Code выполняет каждую фазу автономно БЕЗ запроса подтверждений.
> Исключение: Фаза 4 (дашборд) — показать результат перед деплоем.

---

## Фаза 1: Фундамент (config + database + структура)

### Задачи:
1. Создать структуру директорий проекта
2. Создать `parser/config.py` — все константы из TECHNICAL_SPEC.md (зона, фильтры, UA, пути)
3. Создать `parser/database.py` — SQLite: init_db(), upsert_listing(), mark_inactive(), get_active_listings(), save_daily_stats(), get_price_history(), get_supply_history()
4. Создать `parser/requirements.txt`: httpx, playwright, apscheduler, aiosqlite (или sqlite3 стандартный)
5. Написать тест: создать БД, вставить 5 моковых объявлений, проверить upsert, mark_inactive, get_active

### Критерии завершения:
- [ ] `python3 -c "from parser.database import init_db; init_db()"` — без ошибок
- [ ] Тест проходит: вставка, дедупликация, деактивация работают
- [ ] config.py содержит все константы

---

## Фаза 2: Парсер ЦИАН

### Задачи:
1. Создать `parser/cian.py` — async функции из TECHNICAL_SPEC.md
2. Реализовать fetch_cian_listings(): запрос к API, пагинация, задержки
3. Реализовать parse_cian_offer(): извлечение полей из JSON
4. Реализовать is_in_zone(): фильтрация по ZONE_STREETS
5. Реализовать normalize_street(): нормализация адресов
6. Обработка ошибок: 429 → wait, 403 → skip, timeout → retry
7. Написать тест: мок JSON ответ ЦИАН → parse_cian_offer → проверить все поля

### Критерии завершения:
- [ ] Тест парсинга JSON проходит
- [ ] Логирование: INFO для каждой страницы, WARNING для ошибок
- [ ] Задержки между запросами 3-7с

---

## Фаза 3: Аналитика + JSON export

### Задачи:
1. Создать `parser/analytics.py` — calculate_daily_stats(), calculate_deltas(), calculate_listing_age()
2. Создать `parser/json_export.py` — export_current(), export_stats(), export_history(), export_all()
3. Создать `parser/main.py` — оркестратор run_daily() из TECHNICAL_SPEC.md
4. Написать тест: заполнить БД моковыми данными → export_all() → проверить JSON файлы
5. JSON формат точно по TECHNICAL_SPEC.md (current.json, stats.json, history.json)

### Критерии завершения:
- [ ] main.py запускается и генерирует 3 JSON файла
- [ ] JSON валидный, структура соответствует спецификации
- [ ] Дельты считаются корректно (если нет истории → neutral)
- [ ] Логирование итогов в stdout

---

## Фаза 4: HTML Дашборд ⚠️ ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ

### Задачи:
1. Взять утверждённый макет `dashboard.html` как основу
2. Заменить моковые данные на загрузку из `data/*.json` через fetch()
3. Добавить обработку состояния "нет данных"
4. Добавить обработку ошибок загрузки JSON
5. Проверить что все ссылки открываются в новой вкладке
6. Футер: «разработано Gesolutions©»

### ⚠️ СТОП: показать результат перед продолжением
После завершения — открыть index.html и показать результат.
Ждать подтверждения пользователя.

### Критерии завершения:
- [ ] Дашборд загружает JSON и отображает данные
- [ ] Переключатели периода и шага работают
- [ ] Таблица сортируется
- [ ] Ссылки активны (target=_blank)
- [ ] Состояние "нет данных" обрабатывается
- [ ] Пользователь подтвердил дизайн

---

## Фаза 5: Парсер Авито (Playwright)

### Задачи:
1. Создать `parser/avito.py` — async функции из TECHNICAL_SPEC.md
2. Реализовать fetch_avito_listings(): Playwright Chromium, headless
3. Реализовать parse_avito_page(): извлечение из DOM
4. Anti-bot: UA ротация, задержки, viewport, locale
5. Обработка капчи: логировать и прервать
6. Интегрировать в main.py: если avito упал — продолжить с ЦИАН
7. Тест: мок HTML → parse функции → проверить извлечение

### Критерии завершения:
- [ ] Playwright запускается в headless
- [ ] Парсинг DOM извлекает все поля
- [ ] При ошибке Авито — ЦИАН продолжает работать
- [ ] Логирование всех шагов

---

## Фаза 6: Деплой

### Задачи:
1. Создать `deploy/rentradar.service` — systemd service
2. Создать `deploy/rentradar.timer` — ежедневно 06:00
3. Создать `deploy/nginx.conf` — статика
4. Создать `deploy/install.sh` — скрипт установки на VPS:
   - mkdir, venv, pip install, playwright install
   - Копирование файлов
   - Активация systemd timer
   - Настройка nginx
5. Создать README.md с инструкцией

### Критерии завершения:
- [ ] install.sh создаёт полную рабочую среду
- [ ] systemd timer запускает парсер ежедневно
- [ ] nginx отдаёт дашборд
- [ ] README содержит все шаги
