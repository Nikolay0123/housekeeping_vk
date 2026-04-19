from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Optional

from network.bnovo_client import NormalizedBooking

from . import task_logic as TL
from .queue_item import QueueItem


class FloorChoice(Enum):
    FIRST = "first"
    FOURTH = "fourth"


@dataclass
class PlannedRoom:
    room_id: int
    name: str
    area: float
    cleaning_type: str
    needs_classic_bed_wizard: bool
    needs_floor4_layout_wizard: bool
    needs_floor4_per_bed_wizard: bool
    floor4_max_beds: int


@dataclass
class ClassicBeds:
    planned: PlannedRoom


@dataclass
class Floor4Layout:
    planned: PlannedRoom


@dataclass
class Floor4PerBed:
    planned: PlannedRoom
    max_beds: int


BnovoWizardStep = ClassicBeds | Floor4Layout | Floor4PerBed


FLOOR1_NUMBER_NAMES = [f"Номер {n}" for n in range(101, 110)]
FLOOR1_COMMON_NAMES = [
    "Кабинет администрации",
    "Кабинет директора",
    "Комната администраторов",
    "1 этаж",
    "Кухня",
]
FLOOR4_ORDER = [
    "Номер 401.1",
    "Номер 401.2",
    "Номер 401.3",
    "Номер 401.4",
    "Номер 402.1",
    "Номер 402.2",
    "Номер 402.3",
    "Номер 402.4",
    "Номер 403",
    "Номер 404.1",
    "Номер 404.2",
    "Номер 404.3",
    "Номер 404.4",
    "Номер 405.1",
    "Номер 405.2",
    "Номер 405.3",
    "Номер 405.4",
    "Блок 401",
    "Блок 402",
    "Кухня блока 401,402",
    "Блок 404",
    "Блок 405",
    "Кухня блока 404,405",
    "Холл 4 этаж",
    "Лестница до 5 этажа",
]


def tomorrow_cleaning_date() -> date:
    return date.fromordinal(date.today().toordinal() + 1)


def planned_rooms_for_floor(floor: FloorChoice) -> list[str]:
    if floor == FloorChoice.FIRST:
        return FLOOR1_NUMBER_NAMES + FLOOR1_COMMON_NAMES
    return list(FLOOR4_ORDER)


def empty_plan_message_for_floor(floor: FloorChoice, plan_date: date) -> str:
    ds = plan_date.strftime("%d.%m.%Y")
    if floor == FloorChoice.FIRST:
        return (
            f"По данным Bnovo на {ds} нет задач по номерам 101–109. "
            "Проверьте API и названия номеров."
        )
    return (
        f"По данным Bnovo на {ds} нет задач по выбранным помещениям 4 этажа. "
        "Проверьте API и названия номеров."
    )


def index_bookings_by_room(bookings: list[NormalizedBooking]) -> dict[str, list[NormalizedBooking]]:
    from network.bnovo_client import normalize_room_label as _norm

    m: dict[str, list[NormalizedBooking]] = {}
    for b in bookings:
        key = _norm(b.room_label)
        if not key or key.startswith("id:"):
            continue
        m.setdefault(key, []).append(b)
    return m


def _cleaning_type_queue_rank(cleaning_type: str) -> int:
    return {
        "departure_arrival": 0,
        "departure": 1,
        "current_linen": 2,
        "current": 3,
    }.get(cleaning_type, 4)


def guest_capacity_from_bookings(bookings: list[NormalizedBooking], cleaning_date: date) -> Optional[int]:
    C = cleaning_date
    bounded = [b for b in bookings if b.arrival <= b.departure and b.is_active_for_occupancy()]
    staying = [b for b in bounded if b.arrival < C and b.departure > C]
    leaving = [b for b in bounded if b.departure == C]
    pool = staying if staying else leaving if leaving else bounded
    best: Optional[int] = None
    for b in pool:
        cap = TL.guest_capacity_from_room_type_name(b.room_type_name)
        if cap is None:
            continue
        best = cap if best is None else max(best, cap)
    return best


def cleaning_type_for_room(bookings: list[NormalizedBooking], cleaning_date: date) -> Optional[str]:
    C = cleaning_date
    bounded = [b for b in bookings if b.arrival <= b.departure and b.is_active_for_occupancy()]
    leaving = [b for b in bounded if b.departure == C]
    arriving = [b for b in bounded if b.arrival == C]
    staying = [b for b in bounded if b.arrival < C and b.departure > C]
    if leaving:
        return "departure_arrival" if arriving else "departure"
    if staying:
        b = min(staying, key=lambda x: x.arrival)
        day_num = (C.toordinal() - b.arrival.toordinal()) + 1
        # Смена белья каждые 3 суток; цикл сдвинут на +2 дня относительно (day_num-1)%3==0 (было 4,7,10… → 6,9,12…).
        if day_num >= 6 and (day_num - 3) % 3 == 0:
            return "current_linen"
        if day_num >= 2:
            return "current"
        return None
    if arriving and not staying and not leaving:
        return None
    return None


def needs_bed_configuration_first_floor(room_name: str, cleaning_type: str) -> bool:
    if room_name not in FLOOR1_NUMBER_NAMES:
        return False
    if TL.is_room108(room_name):
        return False
    if TL.is_room101_or107(room_name):
        return False
    if TL.room_linen_profile(room_name) != "classic":
        return False
    return cleaning_type != "current"


def planned_room_for(
    floor_choice: FloorChoice,
    room_id: int,
    name: str,
    area: float,
    cleaning_type: str,
    bookings: list[NormalizedBooking],
    cleaning_date: date,
) -> PlannedRoom:
    cap_raw = guest_capacity_from_bookings(bookings, cleaning_date)
    cap = max(1, min(20, cap_raw)) if cap_raw is not None else 4
    classic = TL.room_linen_profile(name) == "classic"
    needs_classic = (
        floor_choice == FloorChoice.FIRST and classic and needs_bed_configuration_first_floor(name, cleaning_type)
    )
    per_bed = TL.is_floor4_per_bed_bnovo_room(name)
    layout = TL.is_floor4_layout_bnovo_room(name)
    needs_f4_layout = floor_choice == FloorChoice.FOURTH and layout and cleaning_type != "current"
    needs_f4_per_bed = floor_choice == FloorChoice.FOURTH and per_bed and cleaning_type != "current"
    return PlannedRoom(
        room_id=room_id,
        name=name,
        area=area,
        cleaning_type=cleaning_type,
        needs_classic_bed_wizard=needs_classic,
        needs_floor4_layout_wizard=needs_f4_layout,
        needs_floor4_per_bed_wizard=needs_f4_per_bed,
        floor4_max_beds=cap,
    )


def _plan_ordered_rooms(
    room_names: list[str],
    common_names: list[str],
    active_rooms_by_name: dict[str, dict[str, Any]],
    bookings_by_room: dict[str, list[NormalizedBooking]],
    cleaning_date: date,
    floor_choice: FloorChoice,
) -> list[PlannedRoom]:
    queue: list[PlannedRoom] = []
    running_area = 0.0
    limit = TL.AREA_LIMIT
    numbered: list[PlannedRoom] = []
    room_index_by_name = {n: i for i, n in enumerate(room_names)}
    for name in room_names:
        ent = active_rooms_by_name.get(name)
        if not ent:
            continue
        key = cleaning_type_for_room(bookings_by_room.get(name, []), cleaning_date)
        if not key:
            continue
        numbered.append(
            planned_room_for(
                floor_choice,
                ent["id"],
                ent["name"],
                float(ent["area"]),
                key,
                bookings_by_room.get(name, []),
                cleaning_date,
            )
        )
    numbered.sort(
        key=lambda pr: (_cleaning_type_queue_rank(pr.cleaning_type), room_index_by_name.get(pr.name, 0)),
    )
    for p in numbered:
        queue.append(p)
        running_area += p.area
    for name in common_names:
        ent = active_rooms_by_name.get(name)
        if not ent:
            continue
        if running_area + float(ent["area"]) > limit:
            break
        queue.append(
            PlannedRoom(
                room_id=ent["id"],
                name=ent["name"],
                area=float(ent["area"]),
                cleaning_type="current",
                needs_classic_bed_wizard=False,
                needs_floor4_layout_wizard=False,
                needs_floor4_per_bed_wizard=False,
                floor4_max_beds=4,
            )
        )
        running_area += float(ent["area"])
    return queue


def plan_first_floor(
    active_rooms_by_name: dict[str, dict[str, Any]],
    bookings_by_room: dict[str, list[NormalizedBooking]],
    cleaning_date: date,
) -> list[PlannedRoom]:
    return _plan_ordered_rooms(
        FLOOR1_NUMBER_NAMES,
        FLOOR1_COMMON_NAMES,
        active_rooms_by_name,
        bookings_by_room,
        cleaning_date,
        FloorChoice.FIRST,
    )


def plan_fourth_floor(
    active_rooms_by_name: dict[str, dict[str, Any]],
    bookings_by_room: dict[str, list[NormalizedBooking]],
    cleaning_date: date,
) -> list[PlannedRoom]:
    numbered = [n for n in FLOOR4_ORDER if n.startswith("Номер ")]
    common = [n for n in FLOOR4_ORDER if not n.startswith("Номер ")]
    return _plan_ordered_rooms(
        numbered,
        common,
        active_rooms_by_name,
        bookings_by_room,
        cleaning_date,
        FloorChoice.FOURTH,
    )


def build_bnovo_wizard_steps(planned: list[PlannedRoom]) -> list[BnovoWizardStep]:
    out: list[BnovoWizardStep] = []
    for p in planned:
        if p.needs_classic_bed_wizard:
            out.append(ClassicBeds(p))
        elif p.needs_floor4_layout_wizard:
            out.append(Floor4Layout(p))
        elif p.needs_floor4_per_bed_wizard:
            out.append(Floor4PerBed(p, max(1, min(20, p.floor4_max_beds))))
    return out


def planned_to_queue_item(
    planned: PlannedRoom,
    beds_joined: Optional[bool],
    split_beds: int,
    floor4_per_bed_color: Optional[str],
    floor4_per_bed_count: Optional[int],
    classic_variant_override: Optional[int] = None,
) -> QueueItem:
    room_id = planned.room_id
    ct = planned.cleaning_type
    name = planned.name
    if TL.is_floor4_layout_bnovo_room(name) and ct != "current":
        joined = beds_joined if beds_joined is not None else True
        return QueueItem(
            id=room_id,
            name=name,
            area=planned.area,
            cleaning_type=ct,
            linen_profile="floor4",
            linen_variant=TL.LINEN_VARIANT_FLOOR4_JOINED if joined else TL.LINEN_VARIANT_FLOOR4_SPLIT,
        )
    if TL.is_floor4_per_bed_bnovo_room(name) and ct != "current":
        color = floor4_per_bed_color if floor4_per_bed_color in TL.LINEN_COLOR_ORDER_FLOOR4_PER_BED else "blue"
        max_b = max(1, min(20, planned.floor4_max_beds))
        beds = max(1, min(max_b, floor4_per_bed_count or 1))
        return QueueItem(
            id=room_id,
            name=name,
            area=planned.area,
            cleaning_type=ct,
            linen_profile="floor4",
            linen_variant=TL.LINEN_VARIANT_FLOOR4_PER_BED,
            linen_color=color,
            linen_beds=beds,
        )
    classic = TL.room_linen_profile(name)
    needs_linen = classic is not None and ct != "current"
    if not needs_linen:
        return QueueItem(id=room_id, name=name, area=planned.area, cleaning_type=ct)
    if TL.is_room108(name):
        return QueueItem(id=room_id, name=name, area=planned.area, cleaning_type=ct, linen_variant=3)
    if TL.is_room101_or107(name):
        return QueueItem(
            id=room_id,
            name=name,
            area=planned.area,
            cleaning_type=ct,
            linen_variant=TL.LINEN_VARIANT_CLASSIC_101_107,
        )
    if (
        classic_variant_override is not None
        and TL.is_room103_or105(name)
        and classic_variant_override
        in (
            TL.LINEN_VARIANT_CLASSIC_103_105_JOINED_SOFA,
            TL.LINEN_VARIANT_CLASSIC_103_105_SPLIT_SOFA,
        )
    ):
        return QueueItem(
            id=room_id,
            name=name,
            area=planned.area,
            cleaning_type=ct,
            linen_variant=classic_variant_override,
        )
    joined = beds_joined if beds_joined is not None else True
    beds = max(1, min(2, split_beds))
    if TL.is_room109(name):
        if joined:
            return QueueItem(id=room_id, name=name, area=planned.area, cleaning_type=ct, linen_variant=5)
        return QueueItem(
            id=room_id,
            name=name,
            area=planned.area,
            cleaning_type=ct,
            linen_variant=6,
            linen_beds=beds,
        )
    if joined:
        return QueueItem(id=room_id, name=name, area=planned.area, cleaning_type=ct, linen_variant=1)
    return QueueItem(
        id=room_id,
        name=name,
        area=planned.area,
        cleaning_type=ct,
        linen_variant=2,
        linen_beds=beds,
    )
