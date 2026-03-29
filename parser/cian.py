"""
RentRadar -- Парсер ЦИАН.
Парсинг HTML страницы поиска через httpx, извлечение данных из разметки.
"""

import asyncio
import json
import logging
import random
import re
from typing import Any

import httpx

from parser.config import (
    FILTERS,
    REQUEST_DELAY,
    USER_AGENTS,
    ZONE_STREETS,
)

logger = logging.getLogger(__name__)

# URL поиска на сайте ЦИАН (не API)
CIAN_SEARCH_URL = "https://spb.cian.ru/cat.php"

CIAN_SEARCH_PARAMS: dict = {
    "deal_type": "rent",
    "engine_version": 2,
    "offer_type": "flat",
    "region": 2,
    "room0": 1,          # студия
    "p": 1,
    "minprice": FILTERS["price_min"],
    "maxprice": FILTERS["price_max"],
    "mintarea": FILTERS["area_min"],
    "maxtarea": FILTERS["area_max"],
    "type": 4,            # длительная аренда
    "sort": "creation_date_desc",
}

_STREET_SUFFIXES = re.compile(
    r"\s*(ул\.?|улица|пр\.?|пр-т|проспект|пер\.?|переулок|наб\.?|набережная|ш\.?|шоссе)\s*$",
    re.IGNORECASE,
)


def normalize_street(raw_address: str) -> str | None:
    """Извлечь и нормализовать название улицы из адреса.

    'Санкт-Петербург, Подольская ул., 38' -> 'Подольская'
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


def is_in_zone(address_parts: list[dict[str, Any]]) -> bool:
    """Проверить что адрес попадает в ZONE_STREETS через компоненты адреса ЦИАН."""
    for part in address_parts:
        if part.get("type") in ("street", "district"):
            name = part.get("shortName", "") or part.get("fullName", "")
            if normalize_street(name) is not None:
                return True
    full = ", ".join(p.get("fullName", "") for p in address_parts if p.get("fullName"))
    return normalize_street(full) is not None


def parse_cian_offer(offer: dict[str, Any]) -> dict[str, Any] | None:
    """Извлечь из JSON объекта ЦИАН нормализованные данные объявления."""
    try:
        geo = offer.get("geo", {})
        address_parts = geo.get("address", [])

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

        counters_included = 0
        if bargain.get("utilitiesTerms", {}).get("flowMetersNotIncluded") is False:
            counters_included = 1

        return {
            "external_id": str(offer.get("cianId", offer.get("id", ""))),
            "source": "cian",
            "url": offer.get("fullUrl", ""),
            "address": full_address,
            "street": street,
            "area": offer.get("totalArea"),
            "price": int(price),
            "communal": communal,
            "counters_included": counters_included,
            "owner_type": owner_type,
            "commission": int(commission) if commission else 0,
        }
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("Ошибка парсинга offer %s: %s", offer.get("cianId", "?"), e)
        return None


def _extract_offers_from_html(html: str) -> list[dict[str, Any]]:
    """Извлечь JSON данные объявлений из HTML страницы ЦИАН.

    ЦИАН встраивает данные в window._cianConfig['frontend-serp'] или
    в JSON-LD разметку.
    """
    offers = []

    # Способ 1: ищем JSON в initialState / frontend-serp
    patterns = [
        r'"offersSerialized"\s*:\s*(\[[\s\S]*?\])\s*,\s*"',
        r'"offers"\s*:\s*(\[[\s\S]*?\])\s*,\s*"',
        r'window\.__serp_data__\s*=\s*(\{[\s\S]*?\})\s*;',
        r'window\._cianConfig\[[\'"](frontend-serp|serp-state)[\'"]\]\s*=\s*(\{[\s\S]*?\})\s*;',
    ]

    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            try:
                # Берём последнюю группу (для паттерна с 2 группами)
                json_str = match.group(match.lastindex)
                data = json.loads(json_str)

                if isinstance(data, list):
                    offers = data
                elif isinstance(data, dict):
                    offers = (
                        data.get("offersSerialized", [])
                        or data.get("offers", [])
                        or data.get("data", {}).get("offersSerialized", [])
                    )
                if offers:
                    logger.info("ЦИАН: извлечено %d offers из HTML (паттерн)", len(offers))
                    return offers
            except json.JSONDecodeError:
                continue

    # Способ 2: JSON-LD (schema.org)
    ld_pattern = r'<script type="application/ld\+json">([\s\S]*?)</script>'
    for match in re.finditer(ld_pattern, html):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                items = data.get("itemListElement", [])
                logger.info("ЦИАН: извлечено %d items из JSON-LD", len(items))
                return items
        except json.JSONDecodeError:
            continue

    # Способ 3: парсинг data-atрибутов карточек
    card_pattern = r'data-offer="(\{[^"]*\})"'
    for match in re.finditer(card_pattern, html):
        try:
            offer = json.loads(match.group(1).replace("&quot;", '"'))
            offers.append(offer)
        except json.JSONDecodeError:
            continue

    if offers:
        logger.info("ЦИАН: извлечено %d offers из data-атрибутов", len(offers))

    return offers


def _parse_html_card(html: str) -> list[dict[str, Any]]:
    """Fallback: парсинг карточек из HTML если JSON не найден."""
    listings = []
    # Ищем ссылки на объявления
    card_re = re.compile(
        r'<a[^>]*href="(https://spb\.cian\.ru/rent/flat/(\d+)/)"[^>]*>',
    )
    price_re = re.compile(r'data-mark="Price"[^>]*>[\s]*([^<]+)')
    address_re = re.compile(r'data-mark="Address"[^>]*>[\s]*([^<]+)')
    area_re = re.compile(r'(\d+[.,]?\d*)\s*м\s*²')

    # Разбиваем на карточки по ссылкам
    for match in card_re.finditer(html):
        url = match.group(1)
        external_id = match.group(2)

        # Берём фрагмент HTML после ссылки (примерно карточка)
        start = match.start()
        chunk = html[start:start + 3000]

        # Цена
        pm = price_re.search(chunk)
        if not pm:
            continue
        price_text = re.sub(r"[^\d]", "", pm.group(1))
        if not price_text:
            continue
        price = int(price_text)
        if price < 5000 or price > 200000:
            continue

        # Адрес
        am = address_re.search(chunk)
        address = am.group(1).strip() if am else ""
        street = normalize_street(address)
        if street is None:
            continue

        # Площадь
        area_m = area_re.search(chunk)
        area = float(area_m.group(1).replace(",", ".")) if area_m else None

        listings.append({
            "external_id": external_id,
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
    """Получить все объявления с ЦИАН через парсинг HTML."""
    all_listings: list[dict[str, Any]] = []
    page = 1
    max_pages = 10
    seen_ids: set[str] = set()

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://spb.cian.ru/",
        "DNT": "1",
    }

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        http2=False,
    ) as client:
        while page <= max_pages:
            params = {**CIAN_SEARCH_PARAMS, "p": page}
            logger.info("ЦИАН: запрос страницы %d", page)

            try:
                response = await _request_with_retry(client, params, headers)
            except Exception as e:
                logger.error("ЦИАН: критическая ошибка на стр. %d: %s", page, e)
                break

            if response is None:
                break

            html = response.text

            # Проверка на капчу
            if "captcha" in html.lower() and "offer" not in html.lower():
                logger.warning("ЦИАН: капча на стр. %d, прерываем", page)
                break

            # Попытка извлечь JSON из HTML
            offers = _extract_offers_from_html(html)
            page_listings = []

            if offers:
                for offer in offers:
                    parsed = parse_cian_offer(offer)
                    if parsed and parsed["external_id"] not in seen_ids:
                        seen_ids.add(parsed["external_id"])
                        page_listings.append(parsed)
            else:
                # Fallback: парсинг HTML карточек
                page_listings = _parse_html_card(html)
                page_listings = [
                    l for l in page_listings if l["external_id"] not in seen_ids
                ]
                for l in page_listings:
                    seen_ids.add(l["external_id"])

            if not page_listings:
                logger.info("ЦИАН: нет объявлений на стр. %d, завершаем", page)
                break

            all_listings.extend(page_listings)
            logger.info("ЦИАН: стр. %d -- %d в зоне", page, len(page_listings))

            page += 1
            delay = random.uniform(*REQUEST_DELAY)
            await asyncio.sleep(delay)

    logger.info("ЦИАН: итого %d объявлений в зоне", len(all_listings))
    return all_listings


async def _request_with_retry(
    client: httpx.AsyncClient,
    params: dict,
    headers: dict,
    max_retries: int = 3,
) -> httpx.Response | None:
    """HTTP запрос с retry и обработкой ошибок."""
    for attempt in range(1, max_retries + 1):
        try:
            # Ротация User-Agent на каждую попытку
            headers = {**headers, "User-Agent": random.choice(USER_AGENTS)}
            response = await client.get(CIAN_SEARCH_URL, params=params, headers=headers)

            if response.status_code == 200:
                return response

            if response.status_code == 429:
                wait = 60
                logger.warning("ЦИАН: 429, ожидание %dс", wait)
                await asyncio.sleep(wait)
                continue

            if response.status_code == 403:
                logger.warning("ЦИАН: 403, пропускаем")
                return None

            logger.warning("ЦИАН: HTTP %d (попытка %d/%d)", response.status_code, attempt, max_retries)

        except httpx.TimeoutException:
            wait = 2 ** attempt
            logger.warning("ЦИАН: таймаут (попытка %d/%d), ожидание %dс", attempt, max_retries, wait)
            await asyncio.sleep(wait)

        except httpx.HTTPError as e:
            logger.warning("ЦИАН: ошибка (попытка %d/%d): %s", attempt, max_retries, e)
            await asyncio.sleep(2 ** attempt)

    logger.error("ЦИАН: все %d попыток исчерпаны", max_retries)
    return None
