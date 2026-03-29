"""
RentRadar -- Парсер ЦИАН.
Получение объявлений через JSON API, фильтрация по зоне, нормализация.
"""

import asyncio
import logging
import random
import re
from typing import Any

import httpx

from parser.config import (
    CIAN_API_URL,
    CIAN_HEADERS_BASE,
    CIAN_PARAMS,
    REQUEST_DELAY,
    USER_AGENTS,
    ZONE_STREETS,
)

logger = logging.getLogger(__name__)

# Нормализация: убираем окончания "ул.", "пр.", "пер." и т.д.
_STREET_SUFFIXES = re.compile(
    r"\s*(ул\.?|улица|пр\.?|пр-т|проспект|пер\.?|переулок|наб\.?|набережная|ш\.?|шоссе)\s*$",
    re.IGNORECASE,
)


def normalize_street(raw_address: str) -> str | None:
    """Извлечь и нормализовать название улицы из адреса.

    'Россия, Санкт-Петербург, Подольская ул., 38' -> 'Подольская'
    Если улица не в ZONE_STREETS -> None (вне зоны).
    """
    if not raw_address:
        return None

    # Разбить по запятым, искать совпадение в каждой части
    parts = [p.strip() for p in raw_address.split(",")]
    for part in parts:
        cleaned = _STREET_SUFFIXES.sub("", part).strip()
        # Убираем номер дома (цифры в конце)
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
    # Fallback: собрать полный адрес
    full = ", ".join(p.get("fullName", "") for p in address_parts if p.get("fullName"))
    return normalize_street(full) is not None


def parse_cian_offer(offer: dict[str, Any]) -> dict[str, Any] | None:
    """Извлечь из JSON ответа ЦИАН нормализованные данные объявления.

    Возвращает None если объявление вне зоны.
    """
    try:
        # Адрес
        geo = offer.get("geo", {})
        address_parts = geo.get("address", [])

        if not is_in_zone(address_parts):
            return None

        full_address = ", ".join(
            p.get("fullName", "") for p in address_parts if p.get("fullName")
        )
        street = normalize_street(full_address)

        # Цена
        bargain = offer.get("bargainTerms", {})
        price = bargain.get("priceRur") or bargain.get("price")
        if not price:
            return None

        # Коммуналка
        communal = None
        if bargain.get("utilitiesTerms", {}).get("price"):
            communal = bargain["utilitiesTerms"]["price"]
        elif bargain.get("includedOptions"):
            communal = 0  # включено в стоимость

        # Тип владельца
        is_agent = offer.get("isByHomeowner") is False or offer.get("isFromAgent") is True
        owner_type = "agent" if is_agent else "owner"

        # Комиссия
        commission = bargain.get("agentFee", 0) or 0

        # Счётчики
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


async def fetch_cian_listings() -> list[dict[str, Any]]:
    """Получить все объявления с ЦИАН.

    1. Запросить первую страницу -> узнать total
    2. Пагинация по всем страницам (задержка между запросами)
    3. Фильтрация по зоне (ZONE_STREETS)
    4. Нормализация в формат upsert_listing
    """
    all_listings: list[dict[str, Any]] = []
    page = 1
    max_pages = 50  # защита от бесконечного цикла

    headers = {**CIAN_HEADERS_BASE, "User-Agent": random.choice(USER_AGENTS)}

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        while page <= max_pages:
            params = {**CIAN_PARAMS, "p": page}
            logger.info("ЦИАН: запрос страницы %d", page)

            try:
                response = await _request_with_retry(client, params, headers)
            except Exception as e:
                logger.error("ЦИАН: критическая ошибка на стр. %d: %s", page, e)
                break

            if response is None:
                break

            try:
                data = response.json()
            except Exception:
                logger.warning("ЦИАН: невалидный JSON на стр. %d", page)
                break

            offers = data.get("data", {}).get("offersSerialized", [])
            if not offers:
                logger.info("ЦИАН: нет объявлений на стр. %d, завершаем", page)
                break

            page_count = 0
            for offer in offers:
                parsed = parse_cian_offer(offer)
                if parsed:
                    all_listings.append(parsed)
                    page_count += 1

            logger.info(
                "ЦИАН: стр. %d -- %d/%d в зоне",
                page, page_count, len(offers),
            )

            # Проверяем наличие следующей страницы
            total = data.get("data", {}).get("totalOffers", 0)
            offers_per_page = len(offers)
            if page * offers_per_page >= total:
                break

            page += 1
            delay = random.uniform(*REQUEST_DELAY)
            logger.debug("ЦИАН: задержка %.1fс", delay)
            await asyncio.sleep(delay)

    logger.info("ЦИАН: итого %d объявлений в зоне", len(all_listings))
    return all_listings


async def _request_with_retry(
    client: httpx.AsyncClient,
    params: dict,
    headers: dict,
    max_retries: int = 3,
) -> httpx.Response | None:
    """HTTP запрос с retry и обработкой 429/403."""
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.get(CIAN_API_URL, params=params, headers=headers)

            if response.status_code == 200:
                return response

            if response.status_code == 429:
                wait = 60
                logger.warning("ЦИАН: 429 Too Many Requests, ожидание %dс", wait)
                await asyncio.sleep(wait)
                headers["User-Agent"] = random.choice(USER_AGENTS)
                continue

            if response.status_code == 403:
                logger.warning("ЦИАН: 403 Forbidden, пропускаем")
                return None

            logger.warning(
                "ЦИАН: HTTP %d (попытка %d/%d)",
                response.status_code, attempt, max_retries,
            )

        except httpx.TimeoutException:
            wait = 2 ** attempt
            logger.warning(
                "ЦИАН: таймаут (попытка %d/%d), ожидание %dс",
                attempt, max_retries, wait,
            )
            await asyncio.sleep(wait)

        except httpx.HTTPError as e:
            logger.warning("ЦИАН: HTTP ошибка (попытка %d/%d): %s", attempt, max_retries, e)
            await asyncio.sleep(2 ** attempt)

    logger.error("ЦИАН: все %d попыток исчерпаны", max_retries)
    return None
