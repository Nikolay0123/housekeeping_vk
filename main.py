from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from vkbottle import Keyboard, KeyboardButtonColor, Text
from vkbottle.bot import Bot, Message

import config
import vk_wall
from domain import task_logic as TL
from domain.auto_task_bnovo import (
    BnovoWizardStep,
    ClassicBeds,
    Floor4Layout,
    Floor4PerBed,
    FloorChoice,
    PlannedRoom,
    build_bnovo_wizard_steps,
    empty_plan_message_for_floor,
    index_bookings_by_room,
    plan_first_floor,
    plan_fourth_floor,
    planned_to_queue_item,
    tomorrow_cleaning_date,
)
from domain.queue_item import QueueItem
from network.bnovo_client import BOOKINGS_DATE_FUTURE_DAYS, BOOKINGS_DATE_PAST_DAYS, BnovoClient
from storage.database import Database, RoomRow

bot = Bot(token=config.VK_GROUP_TOKEN)
db = Database(config.DB_PATH)
bnovo = BnovoClient()

# У VK inline-клавиатуры жёсткий лимит: не более 10 кнопок всего, не более 5 в ряду.
VK_INLINE_MAX_BUTTONS = 10
VK_INLINE_MAX_PER_ROW = 5
ROOM_PICK_PAGE = 6
EMP_PICK_PAGE = 6
BED_COUNT_PAGE = 6

SESSIONS: dict[int, UserSession] = {}


@dataclass
class UserSession:
    state: str = "idle"
    employee_key: str = ""
    queue: list[QueueItem] = field(default_factory=list)
    comment: Optional[str] = None
    task_for_date: Optional[date] = None
    pending_room_id: Optional[int] = None
    pending_linen_profile: Optional[str] = None
    pending_cleaning_type: Optional[str] = None
    pending_linen_variant: Optional[int] = None
    pending_linen_color: Optional[str] = None
    pending_floor4_max_beds: int = 4
    bnovo_planned: Optional[list[PlannedRoom]] = None
    bnovo_wizard_steps: list[BnovoWizardStep] = field(default_factory=list)
    bnovo_wizard_index: int = 0
    bnovo_layout_choices: dict[str, tuple[bool, int]] = field(default_factory=dict)
    bnovo_per_bed_choices: dict[str, tuple[str, int]] = field(default_factory=dict)
    bnovo_per_bed_color_draft: Optional[str] = None
    bnovo_await_classic_beds_for: Optional[str] = None
    bnovo_classic_variant_override: dict[str, int] = field(default_factory=dict)
    room_list_offset: int = 0
    employee_list_offset: int = 0
    floor4_beds_page: int = 0
    history_pick_task_id: Optional[int] = None


def sess_of(uid: int) -> UserSession:
    if uid not in SESSIONS:
        SESSIONS[uid] = UserSession()
    return SESSIONS[uid]


def reset_interaction_state(s: UserSession) -> None:
    """Сброс пошаговых сценариев (очередь и сотрудник не трогаем)."""
    s.state = "idle"
    s.pending_room_id = None
    s.pending_linen_profile = None
    s.pending_cleaning_type = None
    s.pending_linen_variant = None
    s.pending_linen_color = None
    s.room_list_offset = 0
    s.employee_list_offset = 0
    s.floor4_beds_page = 0
    s.bnovo_planned = None
    s.bnovo_wizard_steps = []
    s.bnovo_wizard_index = 0
    s.bnovo_layout_choices = {}
    s.bnovo_per_bed_choices = {}
    s.bnovo_per_bed_color_draft = None
    s.bnovo_await_classic_beds_for = None
    s.bnovo_classic_variant_override = {}


def main_keyboard() -> str:
    """Inline-кнопки под сообщением (не занимают место как постоянная клавиатура снизу)."""
    return (
        Keyboard(inline=True)
        .add(Text("Меню"), color=KeyboardButtonColor.PRIMARY)
        .add(Text("Сотрудник"), color=KeyboardButtonColor.SECONDARY)
        .row()
        .add(Text("Добавить помещение"))
        .add(Text("Очередь"))
        .row()
        .add(Text("Комментарий"))
        .add(Text("Bnovo"))
        .row()
        .add(Text("Отправить"))
        .add(Text("История"))
        .row()
        .add(Text("Помещения"))
        .add(Text("Сотрудники"))
        .get_json()
    )


def cancel_keyboard() -> str:
    return Keyboard(inline=True).add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE).get_json()


def task_date_keyboard() -> str:
    return (
        Keyboard(inline=True)
        .add(Text("Сегодня"))
        .add(Text("Завтра"))
        .add(Text("Послезавтра"))
        .row()
        .add(Text("Своя дата"))
        .add(Text("Сброс"))
        .row()
        .add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
        .get_json()
    )


def task_date_status_line(s: UserSession) -> str:
    if s.task_for_date:
        return f"День задания: {s.task_for_date.strftime('%d.%m.%Y')}"
    return "День задания: не указан — в тексте не будет блока «Дата уборки»."


def parse_task_date_input(text: str) -> Optional[date]:
    t = text.strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _add_many_text_buttons(k: Keyboard, labels: list[str], *, max_per_row: int = VK_INLINE_MAX_PER_ROW) -> None:
    for i, lab in enumerate(labels):
        k.add(Text(lab))
        if (i + 1) % max_per_row == 0:
            k.row()
    if len(labels) % max_per_row != 0:
        k.row()


def cleaning_keyboard() -> str:
    return (
        Keyboard(inline=True)
        .add(Text("1"))
        .add(Text("2"))
        .add(Text("3"))
        .row()
        .add(Text("4"))
        .add(Text("5"))
        .row()
        .add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
        .get_json()
    )


def bnovo_floor_keyboard() -> str:
    return (
        Keyboard(inline=True)
        .add(Text("1"))
        .add(Text("2"))
        .row()
        .add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
        .get_json()
    )


def layout_joined_split_keyboard() -> str:
    return (
        Keyboard(inline=True)
        .add(Text("Соединены"), color=KeyboardButtonColor.POSITIVE)
        .add(Text("Разъединены"), color=KeyboardButtonColor.SECONDARY)
        .row()
        .add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
        .get_json()
    )


def beds_12_keyboard() -> str:
    return (
        Keyboard(inline=True)
        .add(Text("1"))
        .add(Text("2"))
        .row()
        .add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
        .get_json()
    )


def color_keyboard(*, max_n: int) -> str:
    labels = [str(i) for i in range(1, max_n + 1)]
    k = Keyboard(inline=True)
    _add_many_text_buttons(k, labels)
    k.add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
    return k.get_json()


def linen_color_max_for_session(s: UserSession) -> int:
    if s.pending_linen_variant == TL.LINEN_VARIANT_FLOOR4_PER_BED:
        return 3
    return 4


def floor4_beds_keyboard(sess: UserSession, max_beds: int) -> str:
    mx = max(1, min(20, max_beds))
    nums = list(range(1, mx + 1))
    page = max(0, sess.floor4_beds_page)
    max_page = max(0, (len(nums) - 1) // BED_COUNT_PAGE)
    page = min(page, max_page)
    sess.floor4_beds_page = page
    start_i = page * BED_COUNT_PAGE
    labels = [str(n) for n in nums[start_i : start_i + BED_COUNT_PAGE]]
    has_prev = page > 0
    has_next = start_i + len(labels) < len(nums)
    k = Keyboard(inline=True)
    _add_many_text_buttons(k, labels)
    nav: list[Text] = []
    if has_prev:
        nav.append(Text("предыдущие"))
    if has_next:
        nav.append(Text("следующие"))
    for t in nav:
        k.add(t)
    if nav:
        k.row()
    k.add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
    return k.get_json()


def linen_classic_variant_keyboard(*, include_109: bool, include_103_105_sofa: bool = False) -> str:
    k = Keyboard(inline=True)
    for n in (1, 2, 3, 4):
        k.add(Text(str(n)))
    k.row()
    if include_109:
        k.add(Text("5")).add(Text("6")).row()
    elif include_103_105_sofa:
        k.add(Text("7")).add(Text("8")).row()
    k.add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
    return k.get_json()


def classic_beds_103105_bnovo_keyboard() -> str:
    return (
        Keyboard(inline=True)
        .add(Text("1"))
        .add(Text("2"))
        .row()
        .add(Text("3"))
        .add(Text("4"))
        .row()
        .add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
        .get_json()
    )


def linen_floor4_variant_keyboard() -> str:
    return (
        Keyboard(inline=True)
        .add(Text("10"))
        .add(Text("11"))
        .add(Text("12"))
        .row()
        .add(Text("1"))
        .add(Text("2"))
        .add(Text("3"))
        .row()
        .add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
        .get_json()
    )


def linen_variant_keyboard_for_session(s: UserSession) -> str:
    room = db.get_room_by_id(s.pending_room_id or -1)
    if not room:
        return cancel_keyboard()
    prof = s.pending_linen_profile
    if prof == "classic":
        return linen_classic_variant_keyboard(
            include_109=TL.is_room109(room.name),
            include_103_105_sofa=TL.is_room103_or105(room.name),
        )
    if prof == "floor4":
        return linen_floor4_variant_keyboard()
    return cancel_keyboard()


def employees_pick_keyboard(sess: UserSession) -> str:
    emps = db.get_employees()
    start = sess.employee_list_offset
    start = max(0, min(start, max(0, len(emps) - 1)))
    sess.employee_list_offset = start
    chunk = emps[start : start + EMP_PICK_PAGE]
    has_prev = start > 0
    has_next = start + len(chunk) < len(emps)
    labels = [str(start + i + 1) for i in range(len(chunk))]
    k = Keyboard(inline=True)
    _add_many_text_buttons(k, labels)
    nav: list[Text] = []
    if has_prev:
        nav.append(Text("предыдущие"))
    if has_next:
        nav.append(Text("следующие"))
    for t in nav:
        k.add(t)
    if nav:
        k.row()
    k.add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
    return k.get_json()


def rooms_pick_keyboard(sess: UserSession) -> str:
    rooms = TL.sort_rooms_for_picker(db.get_active_rooms())
    start = sess.room_list_offset
    start = max(0, min(start, max(0, len(rooms) - 1)))
    sess.room_list_offset = start
    chunk = rooms[start : start + ROOM_PICK_PAGE]
    labels = [str(start + i + 1) for i in range(len(chunk))]
    has_prev = start > 0
    has_next = start + len(chunk) < len(rooms)
    k = Keyboard(inline=True)
    _add_many_text_buttons(k, labels)
    nav: list[Text] = []
    if has_prev:
        nav.append(Text("предыдущие"))
    if has_next:
        nav.append(Text("следующие"))
    for t in nav:
        k.add(t)
    if nav:
        k.row()
    k.add(Text("Отмена"), color=KeyboardButtonColor.NEGATIVE)
    return k.get_json()


def cleaning_type_lines() -> str:
    lines = ["Выберите вид уборки (номер):"]
    opts = [
        ("current", "текущая"),
        ("current_linen", "текущая/смена белья"),
        ("departure", "выезд"),
        ("departure_arrival", "выезд/заезд"),
        ("general", "генеральная"),
    ]
    for i, (k, lab) in enumerate(opts, start=1):
        lines.append(f"{i}. {lab} ({k})")
    return "\n".join(lines)


def parse_cleaning_choice(num: int) -> Optional[str]:
    keys = ["current", "current_linen", "departure", "departure_arrival", "general"]
    if 1 <= num <= len(keys):
        return keys[num - 1]
    return None


async def send_chunks(message: Message, text: str, chunk: int = 3800) -> None:
    t = text
    while t:
        part = t[:chunk]
        t = t[chunk:]
        await message.answer(part)


def employees_text() -> str:
    lines = ["Сотрудники (ответьте номером или кодом):"]
    for i, e in enumerate(db.get_employees(), start=1):
        lines.append(f"{i}. {e.display_name} (код: {e.key})")
    lines.append("\nКоманда: сотрудник 2 или сотрудник lena")
    return "\n".join(lines)


def rooms_page(sess: UserSession) -> tuple[str, int]:
    rooms = TL.sort_rooms_for_picker(db.get_active_rooms())
    start = sess.room_list_offset
    start = max(0, min(start, max(0, len(rooms) - 1)))
    sess.room_list_offset = start
    chunk = rooms[start : start + ROOM_PICK_PAGE]
    total_pages = max(1, (len(rooms) + ROOM_PICK_PAGE - 1) // ROOM_PICK_PAGE) if rooms else 1
    page_no = start // ROOM_PICK_PAGE + 1 if rooms else 1
    if not rooms:
        lines = ["Нет активных помещений в базе."]
        return "\n".join(lines), 0
    last_n = start + len(chunk)
    lines = [f"Помещения (стр. {page_no}/{total_pages}), номера {start + 1}–{last_n}:"]
    for j, r in enumerate(chunk, start=start + 1):
        lines.append(f"{j}. {r.name} — {r.area} м²")
    nav = []
    if start > 0:
        nav.append("« предыдущие")
    if start + ROOM_PICK_PAGE < len(rooms):
        nav.append("следующие »")
    if nav:
        lines.append("\n" + " | ".join(nav))
    return "\n".join(lines), len(rooms)


@bot.on.message(text=["Меню", "меню", "старт", "Старт", "/start", "start", "Start"])
async def menu_handler(message: Message) -> None:
    s = sess_of(message.from_id)
    reset_interaction_state(s)
    await message.answer(
        "Добро пожаловать. Бот формирует задания для горничных: очередь номеров, виды уборки, "
        "комплекты белья, лимит площади и автоплан из Bnovo — как в мобильном приложении.\n\n"
        "Действия — встроенные кнопки под этим сообщением (inline). Напишите «Меню», чтобы снова показать их.\n"
        "Если снизу экрана осталась старая «постоянная» клавиатура — в приложении ВК её можно скрыть.\n"
        "День, на который составляется задание: напишите «дата» (пока не выберете — строка «Дата уборки» в текст задания не добавляется).\n\n"
        "Выберите действие:",
        keyboard=main_keyboard(),
    )


@bot.on.message(text="Сотрудник")
async def pick_employee_cmd(message: Message) -> None:
    s = sess_of(message.from_id)
    s.state = "pick_employee"
    s.employee_list_offset = 0
    await message.answer(employees_text(), keyboard=employees_pick_keyboard(s))


@bot.on.message(text="Отмена")
async def cancel_cmd(message: Message) -> None:
    s = sess_of(message.from_id)
    reset_interaction_state(s)
    await message.answer("Ок.", keyboard=main_keyboard())


@bot.on.message(text="Добавить помещение")
async def add_room_cmd(message: Message) -> None:
    s = sess_of(message.from_id)
    if not s.employee_key:
        await message.answer("Сначала выберите сотрудника (кнопка «Сотрудник»).")
        return
    s.state = "pick_room"
    s.room_list_offset = 0
    txt, _ = rooms_page(s)
    await message.answer(
        txt + "\n\nНомер помещения — кнопкой ниже; листание — «следующие» / «предыдущие».",
        keyboard=rooms_pick_keyboard(s),
    )


@bot.on.message(text="Очередь")
async def queue_cmd(message: Message) -> None:
    s = sess_of(message.from_id)
    if not s.queue:
        await message.answer("Очередь пуста.")
        return
    total = sum(x.area for x in s.queue)
    lines = [f"Очередь: {len(s.queue)} помещ., суммарно {total:.1f} м² (лимит {TL.AREA_LIMIT})"]
    for i, q in enumerate(s.queue, start=1):
        lines.append(f"{i}. {q.name} — {TL.format_cleaning_type(q.cleaning_type)}")
    lines.append("\nУдалить строку: удалить 3")
    lines.append("")
    lines.append(task_date_status_line(s))
    lines.append("Сменить день задания: напишите «дата».")
    await message.answer("\n".join(lines))


@bot.on.message(text=["Дата", "дата", "День задания", "день задания"])
async def task_date_cmd(message: Message) -> None:
    s = sess_of(message.from_id)
    s.state = "pick_task_date"
    await message.answer(
        "На какой день оформляем задание? Оно попадёт в текст при «Отправить», в историю и на стену (если настроена).\n\n"
        + task_date_status_line(s),
        keyboard=task_date_keyboard(),
    )


@bot.on.message(text="Комментарий")
async def comment_cmd(message: Message) -> None:
    s = sess_of(message.from_id)
    s.state = "enter_comment"
    await message.answer("Введите комментарий к заданию или «-» чтобы очистить.", keyboard=cancel_keyboard())


@bot.on.message(text="Bnovo")
async def bnovo_cmd(message: Message) -> None:
    if not config.BNOVO_ACCOUNT_ID or not config.BNOVO_API_KEY:
        await message.answer("В .env не заданы BNOVO_ACCOUNT_ID и BNOVO_API_KEY.")
        return
    s = sess_of(message.from_id)
    if not s.employee_key:
        await message.answer("Сначала выберите сотрудника.")
        return
    s.state = "bnovo_pick_floor"
    plan_day = s.task_for_date or tomorrow_cleaning_date()
    if s.task_for_date:
        intro = f"Автозадание по Bnovo на {plan_day.strftime('%d.%m.%Y')} — день из команды «дата».\n"
    else:
        intro = (
            f"Автозадание по Bnovo на {plan_day.strftime('%d.%m.%Y')} (завтра). "
            "Другой день — сначала «дата», затем снова «Bnovo».\n"
        )
    await message.answer(
        intro + "1 — 1 этаж (101–109 + общие)\n2 — 4 этаж (порядок как в приложении)",
        keyboard=bnovo_floor_keyboard(),
    )


@bot.on.message(text="Отправить")
async def send_cmd(message: Message) -> None:
    s = sess_of(message.from_id)
    if not s.employee_key:
        await message.answer("Выберите сотрудника.")
        return
    if not s.queue:
        await message.answer("Очередь пуста.")
        return
    names = db.employee_name_by_key()
    total = sum(x.area for x in s.queue)
    text = TL.format_channel_message(
        s.employee_key,
        s.queue,
        total,
        s.comment,
        s.task_for_date,
        names,
    )

    def save() -> int:
        return db.insert_task(
            int(time.time() * 1000),
            s.employee_key,
            list(s.queue),
            total,
            s.comment,
            message_id=None,
            task_for_date=s.task_for_date,
        )

    try:
        tid = await asyncio.to_thread(save)
        wall_note = ""
        if config.VK_WALL_TOKEN and config.VK_GROUP_ID_FOR_WALL:
            oid = f"-{config.VK_GROUP_ID_FOR_WALL.strip().lstrip('-')}"

            def post() -> None:
                vk_wall.post_wall(access_token=config.VK_WALL_TOKEN, owner_id=oid, message=text)

            try:
                await asyncio.to_thread(post)
                wall_note = "\nДубликат опубликован на стене группы."
            except Exception as e:
                wall_note = f"\nСтена ВК: {e}"
        await send_chunks(message, f"{text}\n\n— Сохранено как задание #{tid}.{wall_note}")
        s.queue = []
        s.comment = None
        s.task_for_date = None
        s.state = "idle"
    except Exception as e:
        await message.answer(f"Ошибка сохранения: {e}")


@bot.on.message(text="История")
async def history_cmd(message: Message) -> None:
    tasks = db.get_last_tasks(15)
    if not tasks:
        await message.answer("История пуста.")
        return
    lines = ["Последние задания. Подробно: задание 123"]
    for t in tasks:
        due = ""
        if t.task_for_date_iso:
            try:
                due = date.fromisoformat(t.task_for_date_iso).strftime("%d.%m") + " — "
            except ValueError:
                pass
        lines.append(
            f"#{t.id} — {due}{TL.format_time_hhmm_ms(t.created_at_ms)} — {t.employee_key} — {t.total_area:.0f} м²"
        )
    await message.answer("\n".join(lines))


@bot.on.message(text="Помещения")
async def rooms_admin_cmd(message: Message) -> None:
    s = sess_of(message.from_id)
    s.state = "rooms_admin"
    lines = ["Помещения: площадь ID новая_площадь | вкл ID | выкл ID | добавить Имя площадь"]
    for r in db.get_all_rooms():
        st = "вкл" if r.is_active else "выкл"
        lines.append(f"{r.id}. [{st}] {r.name} — {r.area} м²")
    await message.answer("\n".join(lines), keyboard=cancel_keyboard())


@bot.on.message(text="Сотрудники")
async def emp_admin_cmd(message: Message) -> None:
    s = sess_of(message.from_id)
    s.state = "emp_admin"
    lines = ["Сотрудники: добавить Имя [код] | удалить ID"]
    for e in db.get_employees():
        lines.append(f"{e.id}. {e.display_name} — {e.key}")
    await message.answer("\n".join(lines), keyboard=cancel_keyboard())


@bot.on.message()
async def dispatcher(message: Message) -> None:
    uid = message.from_id
    s = sess_of(uid)
    text = (message.text or "").strip()
    low = text.lower()

    if s.state == "pick_employee":
        if low.startswith("следующие"):
            s.employee_list_offset += EMP_PICK_PAGE
            await message.answer(employees_text(), keyboard=employees_pick_keyboard(s))
            return
        if "предыдущ" in low:
            s.employee_list_offset = max(0, s.employee_list_offset - EMP_PICK_PAGE)
            await message.answer(employees_text(), keyboard=employees_pick_keyboard(s))
            return
        m = re.match(r"сотрудник\s+(\w+)", low)
        if m:
            key = m.group(1)
            for e in db.get_employees():
                if e.key.lower() == key.lower():
                    s.employee_key = e.key
                    s.state = "idle"
                    await message.answer(f"Исполнитель: {e.display_name}", keyboard=main_keyboard())
                    return
        if text.isdigit():
            n = int(text)
            emps = db.get_employees()
            if 1 <= n <= len(emps):
                e = emps[n - 1]
                s.employee_key = e.key
                s.state = "idle"
                await message.answer(f"Исполнитель: {e.display_name}", keyboard=main_keyboard())
                return
        await message.answer("Не понял. " + employees_text(), keyboard=employees_pick_keyboard(s))
        return

    if s.state == "enter_comment":
        s.comment = None if text in ("-", "") else text
        s.state = "idle"
        await message.answer(f"Комментарий: {s.comment or 'нет'}", keyboard=main_keyboard())
        return

    if s.state == "enter_task_date":
        d = parse_task_date_input(text)
        if not d:
            await message.answer(
                "Не распознано. Введите дату как ДД.ММ.ГГГГ (например 15.04.2026).",
                keyboard=cancel_keyboard(),
            )
            return
        today = date.today()
        if d < today - timedelta(days=60) or d > today + timedelta(days=800):
            await message.answer(
                "Дата слишком далеко от сегодня. Укажите другую.",
                keyboard=cancel_keyboard(),
            )
            return
        s.task_for_date = d
        s.state = "idle"
        await message.answer(
            f"День задания: {d.strftime('%d.%m.%Y')}",
            keyboard=main_keyboard(),
        )
        return

    if s.state == "pick_task_date":
        if text == "Своя дата":
            s.state = "enter_task_date"
            await message.answer(
                "Введите дату в формате ДД.ММ.ГГГГ (например 18.04.2026).",
                keyboard=cancel_keyboard(),
            )
            return
        if text == "Сброс":
            s.task_for_date = None
            s.state = "idle"
            await message.answer(
                "День задания сброшен. При «Отправить» блок «Дата уборки» в текст не войдёт.",
                keyboard=main_keyboard(),
            )
            return
        if text == "Сегодня":
            s.task_for_date = date.today()
        elif text == "Завтра":
            s.task_for_date = date.today() + timedelta(days=1)
        elif text == "Послезавтра":
            s.task_for_date = date.today() + timedelta(days=2)
        else:
            await message.answer(
                "Выберите вариант кнопкой или «Отмена».",
                keyboard=task_date_keyboard(),
            )
            return
        s.state = "idle"
        td = s.task_for_date
        await message.answer(
            f"День задания: {td.strftime('%d.%m.%Y')}" if td else "Готово.",
            keyboard=main_keyboard(),
        )
        return

    if s.state == "pick_room":
        if low.startswith("следующие"):
            s.room_list_offset += ROOM_PICK_PAGE
            txt, _ = rooms_page(s)
            await message.answer(txt, keyboard=rooms_pick_keyboard(s))
            return
        if "предыдущ" in low:
            s.room_list_offset = max(0, s.room_list_offset - ROOM_PICK_PAGE)
            txt, _ = rooms_page(s)
            await message.answer(txt, keyboard=rooms_pick_keyboard(s))
            return
        if text.isdigit():
            n = int(text)
            rooms = TL.sort_rooms_for_picker(db.get_active_rooms())
            if 1 <= n <= len(rooms):
                r = rooms[n - 1]
                await start_add_room_flow(message, s, r)
                return
        txt, _ = rooms_page(s)
        await message.answer("Укажите номер из списка или нажмите кнопку.\n\n" + txt, keyboard=rooms_pick_keyboard(s))
        return

    if s.state == "pick_cleaning":
        if text.isdigit():
            ct = parse_cleaning_choice(int(text))
            if ct:
                await apply_cleaning_choice(message, s, ct)
                return
        await message.answer(cleaning_type_lines(), keyboard=cleaning_keyboard())
        return

    if s.state == "pick_linen_variant":
        if text.isdigit():
            v = int(text)
            prof = s.pending_linen_profile
            room = db.get_room_by_id(s.pending_room_id or -1)
            if not room:
                await message.answer("Ошибка помещения.")
                return
            if prof == "floor4":
                s.pending_linen_variant = v
                s.state = "pick_linen_color"
                n_col = 3 if v == TL.LINEN_VARIANT_FLOOR4_PER_BED else 4
                hint = (
                    "Цвет белья:\n1 голубое\n2 серое\n3 полоска"
                    if n_col == 3
                    else "Цвет белья:\n1 голубое\n2 серое\n3 полоска\n4 белое"
                )
                await message.answer(hint, keyboard=color_keyboard(max_n=n_col))
                return
            if prof == "classic":
                if TL.is_room103_or105(room.name):
                    if v == 7:
                        await finalize_add_room(
                            message,
                            s,
                            room,
                            TL.LINEN_VARIANT_CLASSIC_103_105_JOINED_SOFA,
                        )
                        return
                    if v == 8:
                        await finalize_add_room(
                            message,
                            s,
                            room,
                            TL.LINEN_VARIANT_CLASSIC_103_105_SPLIT_SOFA,
                        )
                        return
                if v == 2:
                    s.pending_linen_variant = 2
                    s.state = "pick_variant2_beds"
                    await message.answer(
                        "Вариант 2: сколько кроватей застелить?",
                        keyboard=beds_12_keyboard(),
                    )
                    return
                await finalize_add_room(message, s, room, v)
                return
        await message.answer("Выберите вариант кнопкой или введите номер.", keyboard=linen_variant_keyboard_for_session(s))
        return

    if s.state == "pick_variant2_beds":
        if text in ("1", "2"):
            room = db.get_room_by_id(s.pending_room_id or -1)
            if room:
                await finalize_add_room(message, s, room, 2, linen_beds=int(text))
                return
        await message.answer("Выберите 1 или 2 кровати.", keyboard=beds_12_keyboard())
        return

    if s.state == "pick_linen_color":
        mx_col = linen_color_max_for_session(s)
        cmap = {"1": "blue", "2": "gray", "3": "stripe", "4": "white"}
        allowed = {k: v for k, v in cmap.items() if int(k) <= mx_col}
        if text in allowed:
            s.pending_linen_color = allowed[text]
            room = db.get_room_by_id(s.pending_room_id or -1)
            if not room:
                return
            v = s.pending_linen_variant
            if v == TL.LINEN_VARIANT_FLOOR4_PER_BED:
                s.state = "pick_floor4_beds"
                s.floor4_beds_page = 0
                mx = max(1, min(20, s.pending_floor4_max_beds))
                await message.answer(
                    f"Сколько кроватей (1–{mx})? Если кроватей больше шести — «следующие» под кнопками.",
                    keyboard=floor4_beds_keyboard(s, mx),
                )
                return
            await finalize_floor4_manual(message, s, room)
            return
        await message.answer(f"Выберите цвет: 1–{mx_col}.", keyboard=color_keyboard(max_n=mx_col))
        return

    if s.state == "pick_floor4_beds":
        mx = max(1, min(20, s.pending_floor4_max_beds))
        max_page = max(0, (mx - 1) // BED_COUNT_PAGE)
        if low.startswith("следующие"):
            s.floor4_beds_page = min(max_page, s.floor4_beds_page + 1)
            await message.answer(
                f"Сколько кроватей (1–{mx})? Стр. {s.floor4_beds_page + 1}/{max_page + 1}.",
                keyboard=floor4_beds_keyboard(s, mx),
            )
            return
        if "предыдущ" in low:
            s.floor4_beds_page = max(0, s.floor4_beds_page - 1)
            await message.answer(
                f"Сколько кроватей (1–{mx})? Стр. {s.floor4_beds_page + 1}/{max_page + 1}.",
                keyboard=floor4_beds_keyboard(s, mx),
            )
            return
        if not text.isdigit():
            await message.answer(
                f"Введите число кроватей от 1 до {mx} или нажмите кнопку.",
                keyboard=floor4_beds_keyboard(s, mx),
            )
            return
        n = int(text)
        room = db.get_room_by_id(s.pending_room_id or -1)
        if not (room and s.pending_linen_color and s.pending_linen_variant is not None):
            s.state = "idle"
            await message.answer("Сессия добавления прервана. Начните добавление помещения снова.", keyboard=main_keyboard())
            return
        mx = max(1, min(20, s.pending_floor4_max_beds))
        beds = max(1, min(mx, n))
        s.queue.append(
            QueueItem(
                id=room.id,
                name=room.name,
                area=room.area,
                cleaning_type=s.pending_cleaning_type or "current",
                linen_profile="floor4",
                linen_variant=s.pending_linen_variant,
                linen_color=s.pending_linen_color,
                linen_beds=beds,
            )
        )
        s.state = "idle"
        s.pending_room_id = None
        await message.answer(f"Добавлено: {room.name}", keyboard=main_keyboard())
        return

    if s.state == "pick_floor4_layout":
        if low in ("1", "соед", "соединены"):
            joined = True
        elif low in ("2", "разъед", "разъединены"):
            joined = False
        else:
            await message.answer("Выберите раскладку кроватей:", keyboard=layout_joined_split_keyboard())
            return
        room = db.get_room_by_id(s.pending_room_id or -1)
        if room:
            v = TL.LINEN_VARIANT_FLOOR4_JOINED if joined else TL.LINEN_VARIANT_FLOOR4_SPLIT
            s.queue.append(
                QueueItem(
                    id=room.id,
                    name=room.name,
                    area=room.area,
                    cleaning_type=s.pending_cleaning_type or "current",
                    linen_profile="floor4",
                    linen_variant=v,
                )
            )
            s.state = "idle"
            s.pending_room_id = None
            await message.answer(f"Добавлено: {room.name}", keyboard=main_keyboard())
        return

    if s.state == "bnovo_pick_floor":
        if text == "1":
            await run_bnovo(message, s, FloorChoice.FIRST)
            return
        if text == "2":
            await run_bnovo(message, s, FloorChoice.FOURTH)
            return
        await message.answer("Выберите этаж кнопкой или введите 1 / 2.", keyboard=bnovo_floor_keyboard())
        return

    if s.state == "bnovo_wizard":
        await handle_bnovo_wizard(message, s, text, low)
        return

    if s.state == "rooms_admin":
        m = re.match(r"площадь\s+(\d+)\s+([\d.,]+)", low)
        if m:
            rid = int(m.group(1))
            area = float(m.group(2).replace(",", "."))
            await asyncio.to_thread(db.set_room_area, rid, area)
            await message.answer("Площадь обновлена.")
            return
        m = re.match(r"(вкл|выкл)\s+(\d+)", low)
        if m:
            rid = int(m.group(2))
            r = db.get_room_by_id(rid)
            if r:
                want_on = m.group(1) == "вкл"
                if bool(r.is_active) != want_on:
                    await asyncio.to_thread(db.toggle_room_active, rid)
            await message.answer("Готово.")
            return
        m = re.match(r"добавить\s+(.+?)\s+([\d.,]+)\s*$", text, re.I)
        if m:
            name = m.group(1).strip()
            area = float(m.group(2).replace(",", "."))
            try:
                await asyncio.to_thread(db.add_room, name, area)
                await message.answer("Помещение добавлено.")
            except Exception as e:
                await message.answer(str(e))
            return
        await message.answer("Команда не распознана. Примеры: площадь 5 12,5 | вкл 3 | добавить Имя 10.5")
        return

    if s.state == "emp_admin":
        m = re.match(r"добавить\s+(.+?)(?:\s+([a-z0-9_]+))?\s*$", text, re.I)
        if m:
            name = m.group(1).strip()
            key = m.group(2)
            try:
                await asyncio.to_thread(db.add_employee, name, key)
                await message.answer("Сотрудник добавлен.")
            except Exception as e:
                await message.answer(str(e))
            return
        m = re.match(r"удалить\s+(\d+)", low)
        if m:
            try:
                await asyncio.to_thread(db.delete_employee, int(m.group(1)))
                await message.answer("Удалено.")
            except Exception as e:
                await message.answer(str(e))
            return
        await message.answer("Команда не распознана. Примеры: добавить Мария | удалить 2")
        return

    m = re.match(r"удалить\s+(\d+)", low)
    if m:
        if s.queue:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(s.queue):
                s.queue.pop(idx)
                await message.answer("Строка удалена.")
                return
        return

    m = re.match(r"задание\s+(\d+)", low)
    if m:
        tid = int(m.group(1))
        got = db.get_task(tid)
        if got:
            task, rooms = got
            due: Optional[date] = None
            if task.task_for_date_iso:
                try:
                    due = date.fromisoformat(task.task_for_date_iso)
                except ValueError:
                    due = None
            detail = TL.format_history_detail_text(
                task.id,
                task.created_at_ms,
                task.employee_key,
                rooms,
                task.total_area,
                task.comment,
                db.employee_name_by_key(),
                task_for_date=due,
            )
            await send_chunks(message, detail)
        else:
            await message.answer("Не найдено.")
        return

    await message.answer("Используйте кнопки меню или «Меню».", keyboard=main_keyboard())


async def start_add_room_flow(message: Message, s: UserSession, r: RoomRow) -> None:
    s.pending_room_id = r.id
    s.pending_linen_profile = TL.room_linen_profile(r.name)
    s.pending_floor4_max_beds = 4
    s.state = "pick_cleaning"
    await message.answer(f"{r.name}\n{cleaning_type_lines()}", keyboard=cleaning_keyboard())


async def apply_cleaning_choice(message: Message, s: UserSession, ct: str) -> None:
    room = db.get_room_by_id(s.pending_room_id or -1)
    if not room:
        return
    s.pending_cleaning_type = ct
    prof = s.pending_linen_profile
    name = room.name

    if prof == "floor4" and ct != "current":
        if TL.is_floor4_layout_bnovo_room(name):
            s.state = "pick_floor4_layout"
            await message.answer(
                "Кровати на 4 этаже:\n1 — соединены\n2 — разъединены\nили кнопки ниже.",
                keyboard=layout_joined_split_keyboard(),
            )
            return
        if TL.is_floor4_per_bed_bnovo_room(name):
            s.pending_linen_variant = TL.LINEN_VARIANT_FLOOR4_PER_BED
            s.state = "pick_linen_color"
            await message.answer(
                "Цвет (per-bed номера):\n1 голубое\n2 серое\n3 полоска",
                keyboard=color_keyboard(max_n=3),
            )
            return

    if prof == "classic" and ct != "current" and TL.is_room101_or107(name):
        s.queue.append(
            QueueItem(
                id=room.id,
                name=room.name,
                area=room.area,
                cleaning_type=ct,
                linen_variant=TL.LINEN_VARIANT_CLASSIC_101_107,
            )
        )
        s.state = "idle"
        s.pending_room_id = None
        await message.answer("Добавлено.", keyboard=main_keyboard())
        return

    if prof is not None and ct != "current":
        s.state = "pick_linen_variant"
        if prof == "classic":
            opts = "Вариант белья (classic):\n1 — вар.1\n2 — вар.2 (две 1,5)\n3 — люкс\n4 — люкс+двусп. пододеяльник"
            if TL.is_room109(name):
                opts += "\n5 — 109 соединены\n6 — 109 разъединены"
            elif TL.is_room103_or105(name):
                opts += "\n7 — соединены + диван\n8 — разъединены + диван"
            await message.answer(
                opts,
                keyboard=linen_classic_variant_keyboard(
                    include_109=TL.is_room109(name),
                    include_103_105_sofa=TL.is_room103_or105(name),
                ),
            )
        else:
            await message.answer(
                "Вариант белья (4 этаж):\n10 — на кровать\n11 — соединены\n12 — разъединены\n1–3 устар. база2/3/4 гостя",
                keyboard=linen_floor4_variant_keyboard(),
            )
        return

    s.queue.append(QueueItem(id=room.id, name=room.name, area=room.area, cleaning_type=ct))
    s.state = "idle"
    s.pending_room_id = None
    await message.answer("Добавлено (без комплекта белья).", keyboard=main_keyboard())


async def finalize_add_room(
    message: Message,
    s: UserSession,
    room: RoomRow,
    variant: int,
    linen_beds: Optional[int] = None,
) -> None:
    s.queue.append(
        QueueItem(
            id=room.id,
            name=room.name,
            area=room.area,
            cleaning_type=s.pending_cleaning_type or "current",
            linen_variant=variant,
            linen_beds=linen_beds,
        )
    )
    s.state = "idle"
    s.pending_room_id = None
    await message.answer("Добавлено.", keyboard=main_keyboard())


async def finalize_floor4_manual(message: Message, s: UserSession, room: RoomRow) -> None:
    s.queue.append(
        QueueItem(
            id=room.id,
            name=room.name,
            area=room.area,
            cleaning_type=s.pending_cleaning_type or "current",
            linen_profile="floor4",
            linen_variant=s.pending_linen_variant,
            linen_color=s.pending_linen_color,
        )
    )
    s.state = "idle"
    s.pending_room_id = None
    await message.answer("Добавлено.", keyboard=main_keyboard())


async def run_bnovo(message: Message, s: UserSession, floor: FloorChoice) -> None:
    cleaning_day = s.task_for_date or tomorrow_cleaning_date()
    try:

        def work() -> tuple[list[PlannedRoom], date]:
            token = bnovo.fetch_access_token(config.BNOVO_ACCOUNT_ID, config.BNOVO_API_KEY)
            cdate = cleaning_day
            df = date.fromordinal(cdate.toordinal() - BOOKINGS_DATE_PAST_DAYS)
            dt = date.fromordinal(cdate.toordinal() + BOOKINGS_DATE_FUTURE_DAYS)
            raw = bnovo.fetch_bookings_normalized(token, df, dt)
            by_room = index_bookings_by_room(raw)
            active = db.rooms_by_name()
            if floor == FloorChoice.FIRST:
                plan = plan_first_floor(active, by_room, cdate)
            else:
                plan = plan_fourth_floor(active, by_room, cdate)
            return plan, cdate

        planned, cdate = await asyncio.to_thread(work)
        if not planned:
            await message.answer(empty_plan_message_for_floor(floor, cleaning_day), keyboard=main_keyboard())
            s.state = "idle"
            return
        steps = build_bnovo_wizard_steps(planned)
        if not steps:
            s.queue = [
                planned_to_queue_item(p, True, 2, None, None) for p in planned
            ]
            s.task_for_date = cdate
            s.state = "idle"
            await message.answer(
                f"План Bnovo загружен на {cdate.isoformat()}, шагов мастера нет. Проверьте очередь.",
                keyboard=main_keyboard(),
            )
            return
        s.bnovo_planned = planned
        s.bnovo_wizard_steps = steps
        s.bnovo_wizard_index = 0
        s.bnovo_layout_choices = {}
        s.bnovo_per_bed_choices = {}
        s.bnovo_per_bed_color_draft = None
        s.bnovo_await_classic_beds_for = None
        s.bnovo_classic_variant_override = {}
        s.floor4_beds_page = 0
        s.task_for_date = cdate
        s.state = "bnovo_wizard"
        await prompt_bnovo_step(message, s)
    except Exception as e:
        s.state = "idle"
        await message.answer(f"Bnovo: {e}", keyboard=main_keyboard())


def _current_bnovo_step(s: UserSession) -> Optional[BnovoWizardStep]:
    if not s.bnovo_wizard_steps or s.bnovo_wizard_index >= len(s.bnovo_wizard_steps):
        return None
    return s.bnovo_wizard_steps[s.bnovo_wizard_index]


async def prompt_bnovo_step(message: Message, s: UserSession) -> None:
    step = _current_bnovo_step(s)
    if not step:
        await apply_full_bnovo(message, s)
        return
    if isinstance(step, ClassicBeds):
        p = step.planned
        if TL.is_room103_or105(p.name):
            await message.answer(
                f"{p.name}: вариант раскладки и комплекта белья\n"
                "1 — соединены (вариант 1)\n"
                "2 — разъединены (вариант 2, затем 1–2 кровати)\n"
                "3 — соединены + диван\n"
                "4 — разъединены + диван",
                keyboard=classic_beds_103105_bnovo_keyboard(),
            )
            return
        await message.answer(
            f"{p.name}: кровати\n1 — соединены\n2 — разъединены (затем уточним 1–2 кровати)\nили кнопки ниже.",
            keyboard=layout_joined_split_keyboard(),
        )
        return
    if isinstance(step, Floor4Layout):
        p = step.planned
        await message.answer(
            f"{p.name}: раскладка\n1 — соединены\n2 — разъединены\nили кнопки ниже.",
            keyboard=layout_joined_split_keyboard(),
        )
        return
    if isinstance(step, Floor4PerBed):
        p = step.planned
        await message.answer(
            f"{p.name}: цвет комплекта (per-bed), затем число кроватей до {step.max_beds}.\n"
            "1 голубое\n2 серое\n3 полоска",
            keyboard=color_keyboard(max_n=3),
        )


async def handle_bnovo_wizard(message: Message, s: UserSession, text: str, low: str) -> None:
    step = _current_bnovo_step(s)
    if not step or s.bnovo_planned is None:
        s.state = "idle"
        await message.answer("Сессия Bnovo сброшена.", keyboard=main_keyboard())
        return
    if isinstance(step, ClassicBeds):
        name = step.planned.name
        if TL.is_room103_or105(name):
            if s.bnovo_await_classic_beds_for == name:
                if text not in ("1", "2"):
                    await message.answer("Сколько кроватей застелить?", keyboard=beds_12_keyboard())
                    return
                beds = max(1, min(2, int(text)))
                s.bnovo_layout_choices[name] = (False, beds)
                s.bnovo_await_classic_beds_for = None
                s.bnovo_wizard_index += 1
                await prompt_bnovo_step(message, s)
                return
            if text == "1":
                s.bnovo_layout_choices[name] = (True, 2)
                s.bnovo_wizard_index += 1
                await prompt_bnovo_step(message, s)
                return
            if text == "2":
                s.bnovo_await_classic_beds_for = name
                await message.answer("Сколько кроватей застелить?", keyboard=beds_12_keyboard())
                return
            if text == "3":
                s.bnovo_classic_variant_override[name] = TL.LINEN_VARIANT_CLASSIC_103_105_JOINED_SOFA
                s.bnovo_layout_choices[name] = (True, 2)
                s.bnovo_wizard_index += 1
                await prompt_bnovo_step(message, s)
                return
            if text == "4":
                s.bnovo_classic_variant_override[name] = TL.LINEN_VARIANT_CLASSIC_103_105_SPLIT_SOFA
                s.bnovo_layout_choices[name] = (False, 2)
                s.bnovo_wizard_index += 1
                await prompt_bnovo_step(message, s)
                return
            await message.answer(
                "Выберите 1–4 кнопкой.",
                keyboard=classic_beds_103105_bnovo_keyboard(),
            )
            return
        if s.bnovo_await_classic_beds_for == name:
            if text not in ("1", "2"):
                await message.answer("Сколько кроватей застелить?", keyboard=beds_12_keyboard())
                return
            beds = max(1, min(2, int(text)))
            s.bnovo_layout_choices[name] = (False, beds)
            s.bnovo_await_classic_beds_for = None
            s.bnovo_wizard_index += 1
            await prompt_bnovo_step(message, s)
            return
        if low in ("1", "соед", "соединены"):
            s.bnovo_layout_choices[name] = (True, 2)
            s.bnovo_wizard_index += 1
            await prompt_bnovo_step(message, s)
            return
        if low in ("2", "разъед", "разъединены"):
            s.bnovo_await_classic_beds_for = name
            await message.answer("Сколько кроватей застелить?", keyboard=beds_12_keyboard())
            return
        await message.answer("Выберите раскладку кроватей:", keyboard=layout_joined_split_keyboard())
        return

    if isinstance(step, Floor4Layout):
        if low in ("1", "соед", "соединены"):
            s.bnovo_layout_choices[step.planned.name] = (True, 2)
        elif low in ("2", "разъед", "разъединены"):
            s.bnovo_layout_choices[step.planned.name] = (False, 2)
        else:
            await message.answer("Выберите раскладку кроватей:", keyboard=layout_joined_split_keyboard())
            return
        s.bnovo_wizard_index += 1
        await prompt_bnovo_step(message, s)
        return

    if isinstance(step, Floor4PerBed):
        cmap = {"1": "blue", "2": "gray", "3": "stripe"}
        mx = max(1, min(20, step.max_beds))
        max_page = max(0, (mx - 1) // BED_COUNT_PAGE)
        if s.bnovo_per_bed_color_draft is None:
            if text in cmap:
                s.bnovo_per_bed_color_draft = cmap[text]
                s.floor4_beds_page = 0
                await message.answer(
                    f"Число кроватей 1–{mx}. При большом числе — «следующие» под кнопками.",
                    keyboard=floor4_beds_keyboard(s, mx),
                )
            else:
                await message.answer(
                    "Выберите цвет: 1 — голубое, 2 — серое, 3 — полоска.",
                    keyboard=color_keyboard(max_n=3),
                )
            return
        if low.startswith("следующие"):
            s.floor4_beds_page = min(max_page, s.floor4_beds_page + 1)
            await message.answer(
                f"Число кроватей 1–{mx}. Стр. {s.floor4_beds_page + 1}/{max_page + 1}.",
                keyboard=floor4_beds_keyboard(s, mx),
            )
            return
        if "предыдущ" in low:
            s.floor4_beds_page = max(0, s.floor4_beds_page - 1)
            await message.answer(
                f"Число кроватей 1–{mx}. Стр. {s.floor4_beds_page + 1}/{max_page + 1}.",
                keyboard=floor4_beds_keyboard(s, mx),
            )
            return
        if text.isdigit():
            beds = max(1, min(mx, int(text)))
            s.bnovo_per_bed_choices[step.planned.name] = (s.bnovo_per_bed_color_draft, beds)
            s.bnovo_per_bed_color_draft = None
            s.floor4_beds_page = 0
            s.bnovo_wizard_index += 1
            await prompt_bnovo_step(message, s)
        else:
            await message.answer(
                f"Введите число кроватей от 1 до {mx} или нажмите кнопку.",
                keyboard=floor4_beds_keyboard(s, mx),
            )
        return


async def apply_full_bnovo(message: Message, s: UserSession) -> None:
    planned = s.bnovo_planned or []
    cdate = s.task_for_date or tomorrow_cleaning_date()
    queue: list[QueueItem] = []
    for p in planned:
        lo = s.bnovo_layout_choices.get(p.name)
        pb = s.bnovo_per_bed_choices.get(p.name)
        override = s.bnovo_classic_variant_override.get(p.name)
        queue.append(
            planned_to_queue_item(
                p,
                lo[0] if lo else None,
                lo[1] if lo else 2,
                pb[0] if pb else None,
                pb[1] if pb else None,
                classic_variant_override=override,
            )
        )
    s.queue = queue
    s.state = "idle"
    s.bnovo_planned = None
    s.bnovo_wizard_steps = []
    s.bnovo_wizard_index = 0
    s.bnovo_layout_choices = {}
    s.bnovo_per_bed_choices = {}
    s.bnovo_per_bed_color_draft = None
    s.bnovo_await_classic_beds_for = None
    s.bnovo_classic_variant_override = {}
    s.floor4_beds_page = 0
    await message.answer(
        f"Очередь из Bnovo на {cdate.isoformat()} готова ({len(queue)} поз.). Проверьте и нажмите «Отправить».",
        keyboard=main_keyboard(),
    )


def main() -> None:
    if not config.VK_GROUP_TOKEN:
        raise SystemExit("Задайте VK_GROUP_TOKEN в .env (токен сообщества с Long Poll).")
    bot.run_forever()


if __name__ == "__main__":
    main()
