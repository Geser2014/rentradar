"""
RentRadar -- Парсер Авито.
Playwright headless Chromium, извлечение данных из DOM, anti-bot меры.
"""

import asyncio
import logging
import random
import re
from typing import Any

from parser.config import (
    AVITO_MAX_PAGES,
    AVITO_SEARCH_URL,
    REQUEST_DELAY,
    USER_AGENTS,
    ZONE_STREETS,
)

logger = logging.getLogger(__name__)

_STREET_SUFFIXES = re.compile(
    r"\s*(ул\.?|улица|пр\.?|пр-т|проспект|пер\.?|переулок|наб\.?|набережная|ш\.?|шоссе)\s*$",
    re.IGNORECASE,
)


def normalize_street(raw_address: str) -> str | None:
    """Извлечь и нормализовать название улицы из адреса Авито.

    'Россия, Санкт-Петербург, Подольская ул., 38' -> 'Подольская'
    Если улица не в ZONE_STREETS -> None (вне зоны).
    """
    if not raw_address:
        return None

    parts = [p.strip() for p in raw_address.split(",")]
    for part in parts:
        cleaned = _STREET_SUFFIXES.sub("", part).strip()
        cleaned = re.sub(r"\s+\d+.*$", "", cleaned).strip()
        if not cleaned or len(cleaned) < 3:
            continue
        for street in ZONE_STREETS:
            if street.lower() == cleaned.lower():
                return street
            if len(cleaned) >= 4 and street.lower() in cleaned.lower():
                return street
    return None


def _parse_price(text: str) -> int | None:
    """Извлечь цену из текста: '25 000 \\u20bd/мес.' -> 25000."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    price = int(digits)
    # Фильтр разумных цен (отсечь цену за сутки и т.п.)
    if price < 5000 or price > 200000:
        return None
    return price


def _parse_area(text: str) -> float | None:
    """Извлечь площадь из текста: '22 м\\u00b2' -> 22.0."""
    if not text:
        return None
    match = re.search(r"(\d+[.,]?\d*)\s*м", text)
    if match:
        return float(match.group(1).replace(",", "."))
    return None


async def parse_avito_page(page: Any) -> list[dict[str, Any]]:
    """Извлечь объявления из загруженной страницы Авито.

    Возвращает список нормализованных dict для upsert_listing.
    """
    listings: list[dict[str, Any]] = []

    # Ждём появления карточек объявлений
    try:
        await page.wait_for_selector("[data-marker='item']", timeout=15000)
    except Exception:
        logger.warning("Авито: карточки не найдены на странице")
        return listings

    items = await page.query_selector_all("[data-marker='item']")
    logger.info("Авито: найдено %d карточек на странице", len(items))

    for item in items:
        try:
            # External ID
            item_id = await item.get_attribute("data-item-id")
            if not item_id:
                href_el = await item.query_selector("a[itemprop='url']")
                if not href_el:
                    href_el = await item.query_selector("a[href*='/kvartiry/']")
                if href_el:
                    href = await href_el.get_attribute("href")
                    match = re.search(r"_(\d+)$", href or "")
                    item_id = match.group(1) if match else None
            if not item_id:
                continue

            # URL
            link_el = await item.query_selector("a[itemprop='url']")
            if not link_el:
                link_el = await item.query_selector("a[href*='/kvartiry/']")
            href = await link_el.get_attribute("href") if link_el else ""
            url = "https://www.avito.ru" + href if href and not href.startswith("http") else href or ""

            # Название (содержит площадь)
            title_el = await item.query_selector("h3")
            if not title_el:
                title_el = await item.query_selector("[itemprop='name']")
            title = await title_el.inner_text() if title_el else ""

            # Цена
            price_el = await item.query_selector("[itemprop='price']")
            if not price_el:
                price_el = await item.query_selector("[data-marker='item-price']")
            price_text = ""
            if price_el:
                price_text = await price_el.get_attribute("content") or await price_el.inner_text()
            price = _parse_price(price_text)
            if not price:
                continue

            # Площадь из заголовка
            area = _parse_area(title)

            # Адрес
            addr_el = await item.query_selector("[class*='geo-address']")
            if not addr_el:
                addr_el = await item.query_selector("[data-marker='item-address']")
            if not addr_el:
                # Fallback: ищем span с адресом
                spans = await item.query_selector_all("span")
                for span in spans:
                    text = await span.inner_text()
                    if any(s in text for s in ["ул.", "пр.", "пер.", "наб."]):
                        addr_el = span
                        break
            address = await addr_el.inner_text() if addr_el else ""
            address = address.strip().replace("\n", ", ")

            # Фильтрация по зоне
            street = normalize_street(address)
            if street is None:
                continue

            # Тип владельца
            owner_type = "unknown"
            badge_els = await item.query_selector_all("span")
            for badge in badge_els:
                badge_text = (await badge.inner_text()).lower()
                if "собственник" in badge_text:
                    owner_type = "owner"
                    break
                if "агент" in badge_text or "компания" in badge_text:
                    owner_type = "agent"
                    break

            listings.append({
                "external_id": str(item_id),
                "source": "avito",
                "url": url,
                "address": address,
                "street": street,
                "area": area,
                "price": price,
                "communal": None,
                "counters_included": 0,
                "owner_type": owner_type,
                "commission": 0,
            })

        except Exception as e:
            logger.warning("Авито: ошибка парсинга карточки: %s", e)
            continue

    logger.info("Авито: распарсено %d объявлений в зоне", len(listings))
    return listings


async def fetch_avito_listings() -> list[dict[str, Any]]:
    """Получить все объявления с Авито через Playwright.

    1. Запустить Playwright Chromium (headless)
    2. Загрузить страницу поиска
    3. Пагинация через ?p=N
    4. Фильтрация по зоне
    5. Нормализация
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Авито: playwright не установлен. pip install playwright && playwright install chromium")
        return []

    all_listings: list[dict[str, Any]] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
            ],
        )
        ua = random.choice(USER_AGENTS)
        context = await browser.new_context(
            user_agent=ua,
            viewport={"width": 1920, "height": 1080},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            extra_http_headers={
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
        )
        # Stealth: скрыть webdriver
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = {runtime: {}};
        """)
        page = await context.new_page()

        try:
            for page_num in range(1, AVITO_MAX_PAGES + 1):
                url = AVITO_SEARCH_URL
                if page_num > 1:
                    sep = "&" if "?" in url else "?"
                    url = f"{url}{sep}p={page_num}"

                logger.info("Авито: загрузка стр. %d", page_num)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    logger.warning("Авито: ошибка загрузки стр. %d: %s", page_num, e)
                    break

                # Проверка на капчу
                content = await page.content()
                if "captcha" in content.lower() or "blocked" in content.lower():
                    logger.warning("Авито: обнаружена капча/блокировка на стр. %d, прерываем", page_num)
                    break

                # Скролл вниз для подгрузки
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)

                # Парсинг страницы
                page_listings = await parse_avito_page(page)
                if not page_listings:
                    logger.info("Авито: нет объявлений на стр. %d, завершаем", page_num)
                    break

                all_listings.extend(page_listings)

                # Проверяем наличие кнопки "следующая страница"
                next_btn = await page.query_selector("[data-marker='pagination-button/nextPage']")
                if not next_btn:
                    next_btn = await page.query_selector("a[class*='pagination-page'][rel='next']")
                if not next_btn:
                    logger.info("Авито: нет следующей страницы после стр. %d", page_num)
                    break

                # Задержка между страницами
                delay = random.uniform(*REQUEST_DELAY)
                logger.debug("Авито: задержка %.1fс", delay)
                await asyncio.sleep(delay)

        except Exception as e:
            logger.error("Авито: критическая ошибка: %s", e, exc_info=True)
        finally:
            await browser.close()

    logger.info("Авито: итого %d объявлений в зоне", len(all_listings))
    return all_listings
