from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Optional

from .queue_item import QueueItem
from .seed_data import ROOM_PICKER_PRIORITY


class RoomPickerTab(Enum):
    FLOOR1 = "Floor1"
    BLOCK_404_405 = "Block404405"
    OTHER = "Other"


AREA_LIMIT = 375.0
BOSS_NAME = "Екатерина"

FLOOR4_TAB_BY_NAME = frozenset(
    {
        "Блок 401",
        "Блок 402",
        "Кухня блока 401,402",
        "Блок 404",
        "Блок 405",
        "Кухня блока 404,405",
        "Холл 4 этаж",
        "Лестница до 5 этажа",
    }
)

CLEANING_TYPES: dict[str, str] = {
    "current": "текущая",
    "current_linen": "текущая/смена белья",
    "departure": "выезд",
    "departure_arrival": "выезд/заезд",
    "general": "генеральная",
}

LEGACY_EMPLOYEE_NAMES = {
    "dina": "ДИНА",
    "lena": "ЛЕНА",
    "olya": "ОЛЯ",
    "admin": "АДМИНИСТРАТОР",
}

LINEN_COLORS = {
    "blue": "голубое",
    "gray": "серое",
    "stripe": "в полоску",
    "white": "белое",
}

LINEN_COLOR_ORDER = ["blue", "gray", "stripe", "white"]
LINEN_COLOR_ORDER_FLOOR4_PER_BED = ["blue", "gray", "stripe"]

LINEN_VARIANT_FLOOR4_PER_BED = 10
LINEN_VARIANT_FLOOR4_JOINED = 11
LINEN_VARIANT_FLOOR4_SPLIT = 12
LINEN_VARIANT_CLASSIC_101_107 = 7

LINEN_FOOT_TOWEL = "Полотенце для ног"

LINEN_PACKAGES: dict[int, dict[str, int]] = {
    1: {
        "Простыня двуспальная": 1,
        "Пододеяльник двуспальный": 1,
        "Наволочка": 2,
        "Полотенце банное с вышивкой": 2,
        "Полотенце для лица": 2,
        "Полотенце для ног": 1,
    },
    2: {
        "Простыня 1,5 спальная": 2,
        "Пододеяльник 1,5 спальный": 2,
        "Наволочка": 2,
        "Полотенце банное с вышивкой": 2,
        "Полотенце для лица": 2,
        "Полотенце для ног": 1,
    },
    3: {
        "Простыня люкс": 1,
        "Пододеяльник люкс": 1,
        "Наволочка с люкс (с вышивкой)": 4,
        "Полотенце банное с вышивкой": 2,
        "Полотенце для лица": 2,
        "Полотенце для ног": 1,
    },
    4: {
        "Простыня люкс": 1,
        "Пододеяльник двуспальный": 1,
        "Наволочка": 2,
        "Полотенце банное с вышивкой": 2,
        "Полотенце для лица": 2,
        "Полотенце для ног": 1,
    },
    5: {
        "Простыня 240х275 для полулюкса": 1,
        "Пододеяльник 200х220 с широкой полоской": 1,
        "Наволочка с вышивкой": 2,
        "Наволочка": 2,
        "Полотенце банное с вышивкой": 2,
        "Полотенце для лица": 2,
        "Полотенце для ног": 1,
        "Халат вафельный": 2,
    },
    6: {
        "Простыня 1,5 спальная": 2,
        "Пододеяльник 1,5 спальный": 2,
        "Наволочка": 2,
        "Наволочка с вышивкой": 2,
        "Полотенце банное с вышивкой": 2,
        "Полотенце для лица": 2,
        "Полотенце для ног": 1,
        "Халат вафельный": 2,
    },
    LINEN_VARIANT_CLASSIC_101_107: {
        "Простыня двуспальная": 1,
        "Пододеяльник двуспальный": 1,
        "Наволочка": 2,
        "Полотенце банное с вышивкой": 1,
        "Полотенце для лица": 1,
        "Полотенце для ног": 1,
    },
}

LINEN_PACKAGE_108: dict[str, int] = {
    "Простыня для люкса": 1,
    "Пододеяльник 200х220 с широкой полоской для люкса": 1,
    "Наволочка белая с широкой полоской для люкса": 4,
    "Полотенце банное с вышивкой": 2,
    "Полотенце для лица": 2,
    "Полотенце для ног": 1,
    "Халат махровый": 2,
}

LINEN_FLOOR4_PER_BED_BASE: dict[str, int] = {
    "Простыня 1,5 спальная": 1,
    "Пододеяльник 1,5 спальный": 1,
    "Наволочка": 1,
    "Полотенце банное": 1,
    "Полотенце 40х70": 1,
}

LINEN_FLOOR4_JOINED_LAYOUT: dict[str, int] = {
    "Простыня двуспальная": 1,
    "Пододеяльник 1,5 спальный": 2,
    "Наволочка": 2,
    "Полотенце банное": 2,
    "Полотенце 40х70": 2,
}

LINEN_FLOOR4_SPLIT_LAYOUT: dict[str, int] = {
    "Простыня 1,5 спальная": 2,
    "Пододеяльник 1,5 спальный": 2,
    "Наволочка": 2,
    "Полотенце банное": 2,
    "Полотенце 40х70": 2,
}

LINEN_PACKAGES_FLOOR4: dict[int, dict[str, int]] = {
    1: {
        "Простыня 1,5 спальная": 2,
        "Пододеяльник 1,5 спальный": 2,
        "Наволочка": 2,
        "Полотенце банное": 2,
        "Полотенце 40х70": 2,
    },
    2: {
        "Простыня 1,5 спальная": 3,
        "Пододеяльник 1,5 спальный": 3,
        "Наволочка": 3,
        "Полотенце банное": 3,
        "Полотенце 40х70": 3,
    },
    3: {
        "Простыня 1,5 спальная": 4,
        "Пододеяльник 1,5 спальный": 4,
        "Наволочка": 4,
        "Полотенце банное": 4,
        "Полотенце 40х70": 4,
    },
}

FLOOR4_PER_BED_ROOM_NAMES = frozenset(
    {
        "Номер 401.2",
        "Номер 401.3",
        "Номер 401.4",
        "Номер 402.1",
        "Номер 402.2",
        "Номер 402.3",
        "Номер 403",
        "Номер 404.2",
        "Номер 404.3",
        "Номер 404.4",
        "Номер 405.1",
        "Номер 405.2",
        "Номер 405.3",
    }
)

FLOOR4_LAYOUT_ROOM_NAMES = frozenset({"Номер 401.1", "Номер 402.4", "Номер 404.1", "Номер 405.4"})


def room_picker_tab(room_name: str) -> RoomPickerTab:
    if room_name in FLOOR4_TAB_BY_NAME:
        return RoomPickerTab.BLOCK_404_405
    if not room_name.startswith("Номер "):
        return RoomPickerTab.OTHER
    rest = room_name.removeprefix("Номер ").strip()
    if rest.isdigit():
        n = int(rest)
        if 101 <= n <= 109:
            return RoomPickerTab.FLOOR1
        if n == 403:
            return RoomPickerTab.BLOCK_404_405
        return RoomPickerTab.OTHER
    m = re.fullmatch(r"(\d+)\.(\d+)", rest)
    if not m:
        return RoomPickerTab.OTHER
    major, minor = int(m.group(1)), int(m.group(2))
    if minor not in range(1, 5):
        return RoomPickerTab.OTHER
    if major in (401, 402, 404, 405):
        return RoomPickerTab.BLOCK_404_405
    return RoomPickerTab.OTHER


def sort_rooms_for_picker(rooms: list) -> list:
    order = {name: i for i, name in enumerate(ROOM_PICKER_PRIORITY)}
    return sorted(rooms, key=lambda r: (order.get(r.name, 10_000), r.name))


def is_floor404_to405_block_room(room_name: str) -> bool:
    if not room_name.startswith("Номер "):
        return False
    rest = room_name.removeprefix("Номер ").strip()
    m = re.fullmatch(r"(\d+)\.(\d+)", rest)
    if not m:
        return False
    major, minor = int(m.group(1)), int(m.group(2))
    return 404 <= major <= 405 and 1 <= minor <= 4


def format_cleaning_type(key: str) -> str:
    return CLEANING_TYPES.get(key, key)


def format_employee_name(employee_key: str, display_names_by_key: Optional[dict[str, str]] = None) -> str:
    m = display_names_by_key or {}
    k = employee_key.lower()
    if k in m:
        return m[k]
    for mk, mv in m.items():
        if mk.lower() == employee_key.lower():
            return mv
    if k in LEGACY_EMPLOYEE_NAMES:
        return LEGACY_EMPLOYEE_NAMES[k]
    return employee_key.upper()


def format_area(value: float) -> str:
    s = f"{value:,.2f}"
    return s.replace(",", " ").replace(".", ",")


def format_date_group(d: date) -> str:
    today = date.today()
    if d == today:
        return "Сегодня"
    if d == today.fromordinal(today.toordinal() - 1):
        return "Вчера"
    return d.strftime("%d.%m.%Y")


def room_linen_profile(room_name: str) -> Optional[str]:
    if not room_name.startswith("Номер "):
        return None
    rest = room_name.removeprefix("Номер ").strip()
    if rest.isdigit():
        n = int(rest)
        if 101 <= n <= 109:
            return "classic"
        if n == 403:
            return "floor4"
        return None
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?", rest)
    if not m:
        return None
    major = int(m.group(1))
    minor_s = m.group(2)
    minor = int(minor_s) if minor_s else None
    if major == 403 and minor is None:
        return "floor4"
    if major in (401, 402, 404, 405) and minor is not None and 1 <= minor <= 4:
        return "floor4"
    return None


def guest_capacity_from_room_type_name(room_type_name: Optional[str]) -> Optional[int]:
    if not room_type_name or not room_type_name.strip():
        return None
    s = room_type_name.lower()
    if any(x in s for x in ("4-мест", "4 мест", "четырёхмест", "четырехмест")):
        return 4
    if any(x in s for x in ("3-мест", "3 мест", "трёхмест", "трехмест")):
        return 3
    if any(x in s for x in ("2-мест", "2 мест", "двухмест", "двуспальн")):
        return 2
    if any(x in s for x in ("1-мест", "1 мест", "одномест")):
        return 1
    return None


def format_linen_color(key: Optional[str]) -> str:
    if not key:
        return ""
    return LINEN_COLORS.get(key, key)


def resolve_linen_profile(item: QueueItem) -> Optional[str]:
    p = item.linen_profile
    if p in ("classic", "floor4"):
        return p
    return room_linen_profile(item.name)


def is_floor4_per_bed_bnovo_room(room_name: str) -> bool:
    return room_name in FLOOR4_PER_BED_ROOM_NAMES


def is_floor4_layout_bnovo_room(room_name: str) -> bool:
    return room_name in FLOOR4_LAYOUT_ROOM_NAMES


def is_room108(room_name: str) -> bool:
    return room_name.strip() == "Номер 108"


def is_room109(room_name: str) -> bool:
    return room_name.strip() == "Номер 109"


def is_room101_or107(room_name: str) -> bool:
    n = room_name.strip()
    return n in ("Номер 101", "Номер 107")


def classic_linen_quantities(item: QueueItem) -> Optional[dict[str, int]]:
    v = item.linen_variant
    if v is None:
        return None
    if is_room108(item.name) and v == 3:
        return dict(LINEN_PACKAGE_108)
    if v == 5:
        pkg = LINEN_PACKAGES.get(5)
        return dict(pkg) if pkg else None
    if v == 6:
        base = LINEN_PACKAGES.get(6)
        if not base:
            return None
        beds_raw = item.linen_beds if item.linen_beds is not None else 2
        beds = beds_raw if beds_raw in (1, 2) else 2
        if beds == 1:
            scaled: dict[str, int] = {}
            for k, q in base.items():
                if k == LINEN_FOOT_TOWEL and q > 0:
                    scaled[k] = max(1, q // 2)
                elif k == "Халат вафельный" and q > 0:
                    scaled[k] = max(1, q)
                else:
                    scaled[k] = max(0, q // 2)
            return scaled
        return dict(base)
    if v not in LINEN_PACKAGES:
        return None
    base = LINEN_PACKAGES[v]
    if v == 2:
        beds_raw = item.linen_beds if item.linen_beds is not None else 2
        beds = beds_raw if beds_raw in (1, 2) else 2
        if beds == 1:
            scaled = {}
            for k, q in base.items():
                if k == LINEN_FOOT_TOWEL and q > 0:
                    scaled[k] = max(1, q // 2)
                else:
                    scaled[k] = max(0, q // 2)
            return scaled
    return dict(base)


def classic_variant2_beds_label(beds: Optional[int]) -> int:
    return 1 if beds == 1 else 2


def floor4_default_beds_for_variant(variant: int) -> int:
    if variant == 1:
        return 2
    if variant == 2:
        return 3
    if variant == 3:
        return 4
    return 2


def floor4_linen_quantities(item: QueueItem) -> Optional[dict[str, int]]:
    variant = item.linen_variant
    if variant is None or resolve_linen_profile(item) != "floor4":
        return None
    if variant == LINEN_VARIANT_FLOOR4_PER_BED:
        n = max(1, min(20, item.linen_beds or 1))
        return {k: q * n for k, q in LINEN_FLOOR4_PER_BED_BASE.items()}
    if variant == LINEN_VARIANT_FLOOR4_JOINED:
        return dict(LINEN_FLOOR4_JOINED_LAYOUT)
    if variant == LINEN_VARIANT_FLOOR4_SPLIT:
        return dict(LINEN_FLOOR4_SPLIT_LAYOUT)
    base = LINEN_PACKAGES_FLOOR4.get(variant)
    return dict(base) if base else None


def format_linen_package_lines(pkg: dict[str, int]) -> list[str]:
    return [f"• {name} — {qty} шт." for name, qty in pkg.items()]


def classic_linen_variant_button_title(variant: int) -> str:
    return {
        1: "Вариант 1 — двуспальная связка",
        2: "Вариант 2 — две 1,5-спальные",
        3: "Вариант 3 — люкс (4 наволочки)",
        4: "Вариант 4 — люкс + двуспальный пододеяльник",
        5: "Номер 109 — соединённые кровати",
        6: "Номер 109 — разъединённые кровати",
        LINEN_VARIANT_CLASSIC_101_107: "Номера 101 и 107 — фиксированный комплект",
    }.get(variant, f"Вариант {variant}")


def floor4_linen_variant_button_title(variant: int) -> str:
    return {
        LINEN_VARIANT_FLOOR4_PER_BED: "Бельё: на каждую заправляемую кровать",
        LINEN_VARIANT_FLOOR4_JOINED: "Кровати соединены (двуспальная простыня)",
        LINEN_VARIANT_FLOOR4_SPLIT: "Кровати разъединены (две 1,5-спальные)",
        1: "Комплект на 2 гостя (база для масштаба)",
        2: "Комплект на 3 гостя",
        3: "Комплект на 4 гостя",
    }.get(variant, f"Вариант {variant}")


def format_room_linen_detail_lines(item: QueueItem) -> list[str]:
    profile = resolve_linen_profile(item)
    v = item.linen_variant
    if profile is None or v is None:
        return []
    lines: list[str] = []
    if profile == "classic":
        pkg = classic_linen_quantities(item)
        if not pkg:
            return []
        lines.append(f"Бельё ({classic_linen_variant_button_title(v)}):")
        lines.extend(format_linen_package_lines(pkg))
    elif profile == "floor4" and floor4_linen_quantities(item):
        pkg = floor4_linen_quantities(item) or {}
        col = format_linen_color(item.linen_color)
        if col and v == LINEN_VARIANT_FLOOR4_PER_BED:
            lines.append(f"Цвет комплекта: {col}")
        if v == LINEN_VARIANT_FLOOR4_PER_BED and item.linen_beds is not None:
            lines.append(f"Заправляемых кроватей: {item.linen_beds}")
        lines.append(f"Состав белья ({floor4_linen_variant_button_title(v)}):")
        lines.extend(format_linen_package_lines(pkg))
    return lines


def format_channel_message(
    employee_key: str,
    queue: list[QueueItem],
    total_area: float,
    comment: Optional[str],
    task_for_date: Optional[date] = None,
    employee_display_names: Optional[dict[str, str]] = None,
) -> str:
    emp_name = format_employee_name(employee_key, employee_display_names)
    limit = AREA_LIMIT
    remainder = limit - total_area
    now = datetime.now()
    date_str = now.strftime("%d.%m.%Y %H:%M")
    task_date_str = task_for_date.strftime("%d.%m.%Y") if task_for_date else None

    lines: list[str] = [
        "НОВОЕ ЗАДАНИЕ",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"Исполнитель: {emp_name}",
    ]
    if task_date_str:
        lines.extend(["", f"Дата уборки: {task_date_str}"])
    lines.extend(["", "ПОРЯДОК УБОРКИ:"])

    linen_totals: dict[str, int] = {}
    linen_color_totals = {LINEN_COLORS[k]: 0 for k in LINEN_COLOR_ORDER if k in LINEN_COLORS}

    def add_linen_item(name: str, qty: int) -> None:
        linen_totals[name] = linen_totals.get(name, 0) + qty

    for idx, r in enumerate(queue):
        i = idx + 1
        num_e = f"{i}."
        ct = format_cleaning_type(r.cleaning_type)
        profile = resolve_linen_profile(r)
        classic_pkg = classic_linen_quantities(r) if profile == "classic" else None
        floor4_pkg = floor4_linen_quantities(r) if profile == "floor4" else None

        bed_config = ""
        if r.linen_variant is not None:
            variant = r.linen_variant
            if profile == "classic" and classic_pkg is not None:
                if variant == 1:
                    bed_config = " — кровати соединены"
                elif variant == 2:
                    bk = classic_variant2_beds_label(r.linen_beds)
                    bed_config = (
                        " — кровати разъединены, застелить 1 кровать"
                        if bk == 1
                        else " — кровати разъединены, застелить 2 кровати"
                    )
                elif variant == 5:
                    bed_config = " — кровати соединены (109)"
                elif variant == 6:
                    bk = classic_variant2_beds_label(r.linen_beds)
                    bed_config = (
                        " — кровати разъединены (109), застелить 1 кровать"
                        if bk == 1
                        else " — кровати разъединены (109), застелить 2 кровати"
                    )
            elif profile == "floor4":
                if variant == LINEN_VARIANT_FLOOR4_PER_BED:
                    col = format_linen_color(r.linen_color)
                    n = r.linen_beds or 1
                    parts = []
                    if col:
                        parts.append(col)
                    parts.append(f"кроватей: {n}")
                    bed_config = " — " + " — ".join(parts) if parts else ""
                elif variant == LINEN_VARIANT_FLOOR4_JOINED:
                    bed_config = " — кровати соединены"
                elif variant == LINEN_VARIANT_FLOOR4_SPLIT:
                    bed_config = " — кровати разъединены"
                else:
                    col = format_linen_color(r.linen_color)
                    if col:
                        bed_config = f" — бельё: {col}"

        area0 = int(round(r.area))
        lines.append(f"{num_e} {r.name} — {area0} м² — {ct}{bed_config}")
        for ln in format_room_linen_detail_lines(r):
            lines.append(f"    {ln}")

        if floor4_pkg is not None:
            variant = r.linen_variant or 0
            for item_name, qty in floor4_pkg.items():
                add_linen_item(item_name, qty)
            if variant == LINEN_VARIANT_FLOOR4_PER_BED:
                ck = r.linen_color
                if ck and ck in LINEN_COLORS:
                    label = LINEN_COLORS[ck]
                    sum_qty = sum(floor4_pkg.values())
                    linen_color_totals[label] = linen_color_totals.get(label, 0) + sum_qty
        elif classic_pkg is not None:
            for item_name, qty in classic_pkg.items():
                add_linen_item(item_name, qty)
            linen_color_totals["белое"] = linen_color_totals.get("белое", 0) + sum(classic_pkg.values())

    total_area0 = int(round(total_area))
    limit0 = int(round(limit))
    remainder_int = int(remainder)
    limit_line = (
        f"Превышение лимита: {abs(remainder_int)} м²" if remainder < 0 else f"Остаток лимита: {remainder_int} м²"
    )
    lines.extend(
        [
            "",
            "ИТОГО:",
            f"• Помещений: {len(queue)}",
            f"• Общая площадь: {total_area0} / {limit0} м²",
            f"• {limit_line}",
            "",
            f"Смена от: {date_str}",
        ]
    )
    if linen_totals:
        lines.append("")
        lines.append("БЕЛЬЕ (ИТОГО ПО ЗАДАНИЮ):")
        lines.append("По цвету (всего единиц):")
        for key in LINEN_COLOR_ORDER:
            label = LINEN_COLORS.get(key)
            if not label:
                continue
            lines.append(f"• {label}: {linen_color_totals.get(label, 0)} шт.")
        lines.extend(["", "По наименованию:"])
        for item_name, qty in linen_totals.items():
            lines.append(f"• {item_name}: {qty} шт.")
        lines.append(f"• Всего единиц (сумма строк выше): {sum(linen_totals.values())} шт.")
    if comment and comment.strip():
        lines.extend(["", f"Комментарий: {comment}"])
    lines.extend(["━━━━━━━━━━━━━━━━━━━━━", "Задание действительно до конца смены"])
    return "\n".join(lines)


def format_datetime_ms(millis: int) -> str:
    return datetime.fromtimestamp(millis / 1000.0).strftime("%d.%m.%Y %H:%M")


def format_time_hhmm_ms(millis: int) -> str:
    return datetime.fromtimestamp(millis / 1000.0).strftime("%H:%M")


def format_history_detail_text(
    task_id: int,
    created_at_ms: int,
    employee_key: str,
    rooms: list[QueueItem],
    total_area: float,
    comment: Optional[str],
    employee_display_names: Optional[dict[str, str]] = None,
    task_for_date: Optional[date] = None,
) -> str:
    total_area0 = int(round(total_area))
    lines = [
        f"Задание #{task_id}",
        format_employee_name(employee_key, employee_display_names),
        format_datetime_ms(created_at_ms),
        f"{total_area0} м², помещений: {len(rooms)}",
    ]
    if task_for_date:
        lines.append(f"Дата уборки: {task_for_date.strftime('%d.%m.%Y')}")
    lines.extend(["", "Порядок уборки:"])
    for idx, r in enumerate(rooms):
        i = idx + 1
        ct = format_cleaning_type(r.cleaning_type)
        profile = resolve_linen_profile(r)
        extra = ""
        if profile == "floor4" and r.linen_variant is not None:
            v = r.linen_variant
            if v == LINEN_VARIANT_FLOOR4_PER_BED:
                lc = format_linen_color(r.linen_color)
                extra = f", {r.linen_beds or 1} кров. бельё" + (f" ({lc})" if lc else "")
            elif v == LINEN_VARIANT_FLOOR4_JOINED:
                extra = ", соед. кровати"
            elif v == LINEN_VARIANT_FLOOR4_SPLIT:
                extra = ", разъед. кровати"
            else:
                lc = format_linen_color(r.linen_color)
                extra = f", комплект {v}" + (f" ({lc})" if lc else "")
        elif profile == "classic" and r.linen_variant == 2:
            bk = classic_variant2_beds_label(r.linen_beds)
            extra = f", вар.2 — {bk} кров."
        elif profile == "classic" and r.linen_variant == 6:
            bk = classic_variant2_beds_label(r.linen_beds)
            extra = f", 109 разд. — {bk} кров."
        elif profile == "classic" and r.linen_variant == 5:
            extra = ", 109 соед."
        elif profile == "classic" and r.linen_variant == LINEN_VARIANT_CLASSIC_101_107:
            extra = ", 101/107 фикс."
        area0 = int(round(r.area))
        lines.append(f"  {i}. {r.name} — {area0} м² — {ct}{extra}")
        for ln in format_room_linen_detail_lines(r):
            lines.append(f"     {ln}")
    if comment and comment.strip():
        lines.extend(["", comment])
    return "\n".join(lines)
