"""
RentRadar -- Парсер ЦИАН.
Playwright headless для обхода капчи, извлечение данных из HTML/JSON.
"""

import asyncio
import json
import logging
import random
import re
from typing import Any

from parser.config import (
    FILTERS,
    REQUEST_DELAY,
    USER_AGENTS,
    ZONE_STREETS,
)

logger = logging.getLogger(__name__)

CIAN_SEARCH_URL = (
    "https://spb.cian.ru/cat.php"
    "?deal_type=rent&engine_version=2&offer_type=flat"
    "&region=2&room0=1&object_type%5B0%5D=2&type=4&sort=creation_date_desc"
    f"&minprice={FILTERS['price_min']}&maxprice={FILTERS['price_max']}"
    f"&mintarea={FILTERS['area_min']}&maxtarea={FILTERS['area_max']}"
)

_STREET_SUFFIXES = re.compile(
    r"\s*(ул\.?|улица|пр\.?|пр-т|проспект|пер\.?|переулок|наб\.?|набережная|ш\.?|шоссе)\s*$",
    re.IGNORECASE,
)


def normalize_street(raw_address: str) -> str | None:
    """Извлечь и нормализовать название улицы из адреса."""
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


def is_in_zone(address_parts: list[dict[str, Any]]) -> bool:
    """Проверить что адрес попадает в ZONE_STREETS."""
    for part in address_parts:
        if part.get("type") in ("street", "district"):
            name = part.get("shortName", "") or part.get("fullName", "")
            if normalize_street(name) is not None:
                return True
    full = ", ".join(p.get("fullName", "") for p in address_parts if p.get("fullName"))
    return normalize_street(full) is not None


def parse_cian_offer(offer: dict[str, Any]) -> dict[str, Any] | None:
    """Извлечь из JSON объекта ЦИАН нормализованные данные."""
    try:
        geo = offer.get("geo", {})
        address_parts = geo.get("address", [])
        # Пропускаем комнаты -- нужны только студии/квартиры
        flat_type = offer.get("flatType", "")
        if flat_type == "rooms":
            return None

        if not is_in_zone(address_parts):
            return None

        full_address = ", ".join(
            p.get("fullName", "") for p in address_parts if p.get("fullName")
        )
        street = normalize_street(full_address)

        bargain = offer.get("bargainTerms", {})
        price = bargain.get("priceRur") or bargain.get("price")
        if not price:
            return None

        communal = None
        if bargain.get("utilitiesTerms", {}).get("price"):
            communal = bargain["utilitiesTerms"]["price"]

        is_agent = offer.get("isByHomeowner") is False or offer.get("isFromAgent") is True
        owner_type = "agent" if is_agent else "owner"
        commission = bargain.get("agentFee", 0) or 0

        return {
            "external_id": str(offer.get("cianId", offer.get("id", ""))),
            "source": "cian",
            "url": offer.get("fullUrl", ""),
            "address": full_address,
            "street": street,
            "area": offer.get("totalArea"),
            "price": int(price),
            "communal": communal,
            "counters_included": 0,
            "owner_type": owner_type,
            "commission": int(commission) if commission else 0,
        }
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("Ошибка парсинга offer: %s", e)
        return None


def _extract_offers_from_html(html: str) -> list[dict]:
    """Извлечь JSON объявления из HTML страницы ЦИАН.

    Данные в initialState -> results -> offers.
    Используем bracket-counting для извлечения массива.
    """
    # Ищем начало массива offers
    marker = '"offers":['
    idx = html.find(marker)
    if idx == -1:
        logger.debug("ЦИАН: маркер 'offers' не найден в HTML")
        return []

    start = idx + len(marker) - 1  # позиция '['
    # Bracket counting для нахождения конца массива
    depth = 0
    end = start
    for i in range(start, min(start + 5_000_000, len(html))):
        c = html[i]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if depth != 0:
        logger.warning("ЦИАН: не удалось найти конец массива offers")
        return []

    json_str = html[start:end]
    try:
        offers = json.loads(json_str)
        logger.info("ЦИАН: извлечено %d offers из initialState", len(offers))
        return offers
    except json.JSONDecodeError as e:
        logger.warning("ЦИАН: ошибка парсинга JSON offers: %s", e)
        return []


def _parse_html_cards(html: str) -> list[dict]:
    """Fallback: парсинг карточек из HTML разметки."""
    listings = []
    # Ищем ссылки на объявления + цену + адрес в окружающем HTML
    card_re = re.compile(r'href="(https://spb\.cian\.ru/rent/flat/(\d+)/)"')
    seen = set()

    for match in card_re.finditer(html):
        url = match.group(1)
        ext_id = match.group(2)
        if ext_id in seen:
            continue
        seen.add(ext_id)

        chunk = html[max(0, match.start() - 1000):match.end() + 2000]

        # Цена
        price_m = re.search(r'([\d\s]{5,10})\s*[₽\u20BD]', chunk)
        if not price_m:
            continue
        price = int(re.sub(r'\s', '', price_m.group(1)))
        if price < 5000 or price > 200000:
            continue

        # Адрес -- ищем строки с названиями улиц
        address = ""
        street = None
        for s in ZONE_STREETS:
            if s.lower() in chunk.lower():
                street = s
                addr_m = re.search(re.escape(s) + r'[^<,]*', chunk, re.IGNORECASE)
                if addr_m:
                    address = addr_m.group(0).strip()
                break

        if not street:
            continue

        # Площадь
        area = None
        area_m = re.search(r'(\d+[.,]?\d*)\s*м\s*[²2]', chunk)
        if area_m:
            area = float(area_m.group(1).replace(',', '.'))

        listings.append({
            "external_id": ext_id,
            "source": "cian",
            "url": url,
            "address": address,
            "street": street,
            "area": area,
            "price": price,
            "communal": None,
            "counters_included": 0,
            "owner_type": "unknown",
            "commission": 0,
        })

    return listings


async def fetch_cian_listings() -> list[dict[str, Any]]:
    """Получить объявления с ЦИАН через Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("ЦИАН: playwright не установлен")
        return []

    all_listings: list[dict] = []
    seen_ids: set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1920, "height": 1080},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru']});
            window.chrome = {runtime: {}};
        """)
        page = await context.new_page()

        try:
            for page_num in range(1, 6):
                url = CIAN_SEARCH_URL + f"&p={page_num}"
                logger.info("ЦИАН: загрузка стр. %d", page_num)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=60000)
                    await asyncio.sleep(5)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning("ЦИАН: ошибка загрузки стр. %d: %s", page_num, e)
                    break

                html = await page.content()
                logger.info("ЦИАН: стр. %d загружена, %d байт", page_num, len(html))

                # Капча только если страница маленькая (нет данных)
                if len(html) < 50000 and '"offers"' not in html:
                    logger.warning("ЦИАН: страница слишком маленькая, возможна капча")
                    await asyncio.sleep(10)
                    html = await page.content()
                    if len(html) < 50000:
                        logger.warning("ЦИАН: капча не прошла, прерываем")
                        break

                # Извлечение данных
                page_listings = []
                offers = _extract_offers_from_html(html)
                if offers:
                    for offer in offers:
                        parsed = parse_cian_offer(offer)
                        if parsed and parsed["external_id"] not in seen_ids:
                            seen_ids.add(parsed["external_id"])
                            page_listings.append(parsed)
                else:
                    page_listings = _parse_html_cards(html)
                    page_listings = [l for l in page_listings if l["external_id"] not in seen_ids]
                    for l in page_listings:
                        seen_ids.add(l["external_id"])

                if not page_listings:
                    logger.info("ЦИАН: нет объявлений на стр. %d (HTML %d байт)", page_num, len(html))
                    break

                all_listings.extend(page_listings)
                logger.info("ЦИАН: стр. %d -- %d в зоне", page_num, len(page_listings))

                delay = random.uniform(*REQUEST_DELAY)
                await asyncio.sleep(delay)

        except Exception as e:
            logger.error("ЦИАН: критическая ошибка: %s", e, exc_info=True)
        finally:
            await browser.close()

    logger.info("ЦИАН: итого %d объявлений в зоне", len(all_listings))
    return all_listings
