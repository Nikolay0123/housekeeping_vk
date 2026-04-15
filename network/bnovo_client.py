from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests

BASE_URL = "https://api.pms.bnovo.ru"
BOOKINGS_PAGE_LIMIT = 50
MAX_BOOKINGS_PAGES = 500
BOOKINGS_DATE_PAST_DAYS = 120
BOOKINGS_DATE_FUTURE_DAYS = 60

TERMINAL_OCCUPANCY = frozenset(
    {
        "выехал",
        "отменен",
        "отменён",
        "отменена",
        "cancelled",
        "canceled",
    }
)


class BnovoApiException(Exception):
    pass


@dataclass
class NormalizedBooking:
    room_label: str
    arrival: date
    departure: date
    status_name: Optional[str] = None
    has_cancel_date: bool = False
    room_type_name: Optional[str] = None

    def is_active_for_occupancy(self) -> bool:
        if self.has_cancel_date:
            return False
        n = (self.status_name or "").strip().lower()
        if not n:
            return True
        return n not in TERMINAL_OCCUPANCY


def normalize_room_label(raw: str) -> Optional[str]:
    t = raw.strip().replace("\u00a0", " ")
    if t.startswith("id:"):
        return t
    collapsed = re.sub(r"\s+", " ", t)
    m = re.search(r"(\d{3,4}(?:\.\d+)?)", collapsed)
    if m:
        return f"Номер {m.group(1)}"
    n = collapsed.removeprefix("Номер").strip()
    n = n.removeprefix("номер").strip()
    if n.startswith("№"):
        n = n[1:].strip()
    n = n.removeprefix("No.").strip()
    n = n.removeprefix("no.").strip()
    if n.isdigit() and 3 <= len(n) <= 4:
        return f"Номер {n}"
    return None


def _extract_token(payload: dict[str, Any]) -> Optional[str]:
    for key in ("access_token", "token", "jwt"):
        v = payload.get(key)
        if v and isinstance(v, str) and v.strip():
            return v
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("access_token", "token"):
            v = data.get(key)
            if v and isinstance(v, str) and v.strip():
                return v
    return None


def _extract_array(root: Any) -> Optional[list]:
    if isinstance(root, list):
        return root
    if not isinstance(root, dict):
        return None
    for key in ("data", "bookings", "items", "result"):
        el = root.get(key)
        if isinstance(el, list):
            return el
        if isinstance(el, dict):
            inner = el.get("bookings") or el.get("booking") or el.get("data")
            if isinstance(inner, list):
                return inner
    return None


def _get_str(o: dict, key: str) -> Optional[str]:
    v = o.get(key)
    if isinstance(v, str):
        return v
    return None


def _parse_date_el(el: Any) -> Optional[date]:
    if el is None:
        return None
    if isinstance(el, str):
        s = el.strip()
    else:
        s = str(el).strip().strip('"')
    if not s:
        return None
    day = s[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(day, fmt).date()
        except ValueError:
            continue
    return None


def _parse_status_name(o: dict) -> Optional[str]:
    st = o.get("status")
    if isinstance(st, dict):
        return _get_str(st, "name")
    return None


def _parse_has_cancel(o: dict) -> bool:
    dates = o.get("dates")
    if not isinstance(dates, dict):
        return False
    cd = dates.get("cancel_date")
    if cd is None:
        return False
    if isinstance(cd, str):
        return bool(cd.strip())
    return True


def _parse_room_type_name(o: dict) -> Optional[str]:
    prices = o.get("prices")
    if isinstance(prices, list):
        for el in prices:
            if isinstance(el, dict):
                n = _get_str(el, "room_type_name")
                if n and n.strip():
                    return n.strip()
    return _get_str(o, "room_type_name")


def _parse_date_from_object(o: dict) -> Optional[date]:
    dates = o.get("dates")
    if isinstance(dates, dict):
        for k in ("arrival", "real_arrival", "original_arrival"):
            d = _parse_date_el(dates.get(k))
            if d:
                return d
    keys = (
        "date_arrival",
        "date_arrival_hotel",
        "arrival_date",
        "arrival",
        "check_in",
        "checkin",
        "date_from",
        "dateCheckIn",
        "start_date",
    )
    for k in keys:
        d = _parse_date_el(o.get(k))
        if d:
            return d
    room = o.get("room")
    if isinstance(room, dict):
        for k in keys:
            d = _parse_date_el(room.get(k))
            if d:
                return d
    return None


def _parse_departure(o: dict) -> Optional[date]:
    dates = o.get("dates")
    if isinstance(dates, dict):
        for k in ("departure", "real_departure", "original_departure"):
            d = _parse_date_el(dates.get(k))
            if d:
                return d
    keys = (
        "date_departure",
        "date_departure_hotel",
        "departure_date",
        "departure",
        "check_out",
        "checkout",
        "date_to",
        "dateCheckOut",
        "end_date",
    )
    for k in keys:
        d = _parse_date_el(o.get(k))
        if d:
            return d
    room = o.get("room")
    if isinstance(room, dict):
        for k in keys:
            d = _parse_date_el(room.get(k))
            if d:
                return d
    return None


def _extract_room_labels(o: dict) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    direct_keys = (
        "room_name",
        "room_number",
        "roomNumber",
        "apartment",
        "room_title",
        "flat",
        "flat_number",
        "room_flat",
        "category_room",
        "placement",
        "placement_name",
    )
    for k in direct_keys:
        s = _get_str(o, k)
        if s:
            norm = normalize_room_label(s)
            if norm and norm not in seen:
                seen.add(norm)
                labels.append(norm)
    room = o.get("room")
    if isinstance(room, dict):
        for k in ("name", "title", "number", "room_number", "id", "short_name", "code"):
            raw = room.get(k)
            if isinstance(raw, str):
                norm = normalize_room_label(raw)
            elif isinstance(raw, (int, float)):
                norm = normalize_room_label(str(raw))
            else:
                norm = None
            if norm and norm not in seen:
                seen.add(norm)
                labels.append(norm)
    if not labels:
        for key in ("room_id", "id_room"):
            rid = o.get(key)
            if isinstance(rid, (int, float)):
                labels.append(f"id:{int(rid)}")
                break
    return labels


def _parse_bookings_payload(text: str) -> list[NormalizedBooking]:
    try:
        root = json.loads(text)
    except json.JSONDecodeError:
        return []
    arr = _extract_array(root)
    if not arr:
        return []
    out: list[NormalizedBooking] = []
    for el in arr:
        if not isinstance(el, dict):
            continue
        arrival = _parse_date_from_object(el)
        departure = _parse_departure(el)
        if not arrival or not departure:
            continue
        status = _parse_status_name(el)
        cancel = _parse_has_cancel(el)
        rt = _parse_room_type_name(el)
        for label in _extract_room_labels(el):
            out.append(
                NormalizedBooking(
                    room_label=label,
                    arrival=arrival,
                    departure=departure,
                    status_name=status,
                    has_cancel_date=cancel,
                    room_type_name=rt,
                )
            )
    return out


def _bookings_page_count(text: str) -> int:
    try:
        root = json.loads(text)
    except json.JSONDecodeError:
        return 0
    arr = _extract_array(root)
    return len(arr) if arr else 0


class BnovoClient:
    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self._session = session or requests.Session()

    def fetch_access_token(self, account_id: str, api_key: str) -> str:
        aid = account_id.strip()
        pwd = api_key.strip()
        if not aid or not pwd:
            raise BnovoApiException("Укажите ID аккаунта и API-ключ Bnovo.")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        bodies: list[dict] = []
        if aid.isdigit():
            bodies.append({"id": int(aid), "password": pwd})
        else:
            bodies.append({"id": aid, "password": pwd})
        bodies.append({"username": aid, "password": pwd})
        seen: set[str] = set()
        unique_bodies = []
        for b in bodies:
            key = json.dumps(b, sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique_bodies.append(b)
        last_code = -1
        last_body = ""
        for body in unique_bodies:
            r = self._session.post(f"{BASE_URL}/api/v1/auth", json=body, headers=headers, timeout=60)
            last_code = r.status_code
            last_body = r.text
            if r.status_code == 200:
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    continue
                tok = _extract_token(data)
                if tok:
                    return tok
                raise BnovoApiException(f"В ответе Bnovo нет access_token. Фрагмент: {r.text[:400]}")
            if r.status_code != 404:
                raise BnovoApiException(f"Bnovo auth {r.status_code}: {r.text[:400]}")
        raise BnovoApiException(f"Bnovo auth {last_code}: {last_body[:400]}")

    def fetch_bookings_normalized(self, access_token: str, date_from: date, date_to: date) -> list[NormalizedBooking]:
        token = access_token.strip()
        all_rows: list[NormalizedBooking] = []
        offset = 0
        pages = 0
        while pages < MAX_BOOKINGS_PAGES:
            pages += 1
            qs = urlencode(
                {
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                    "limit": str(BOOKINGS_PAGE_LIMIT),
                    "offset": str(offset),
                }
            )
            url = f"{BASE_URL}/api/v1/bookings?{qs}"
            r = self._session.get(
                url,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                timeout=120,
            )
            text = r.text
            if r.status_code != 200:
                raise BnovoApiException(f"Bnovo bookings {r.status_code}: {text[:500]}")
            all_rows.extend(_parse_bookings_payload(text))
            cnt = _bookings_page_count(text)
            if cnt < BOOKINGS_PAGE_LIMIT or cnt == 0:
                break
            offset += BOOKINGS_PAGE_LIMIT
        return all_rows
