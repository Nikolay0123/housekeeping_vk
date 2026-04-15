from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from domain.queue_item import QueueItem
from domain.seed_data import INITIAL_ROOMS


@dataclass
class RoomRow:
    id: int
    name: str
    area: float
    is_active: bool


@dataclass
class EmployeeRow:
    id: int
    key: str
    display_name: str


@dataclass
class TaskRow:
    id: int
    created_at_ms: int
    employee_key: str
    rooms_json: str
    total_area: float
    comment: Optional[str]
    message_id: Optional[int]


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._seed()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                area REAL NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_ms INTEGER NOT NULL,
                employee_key TEXT NOT NULL,
                rooms_json TEXT NOT NULL,
                total_area REAL NOT NULL,
                comment TEXT,
                message_id INTEGER
            );
            """
        )
        self._conn.commit()

    def _seed(self) -> None:
        cur = self._conn.execute("SELECT COUNT(*) FROM rooms")
        if cur.fetchone()[0] > 0:
            return
        for name, area in INITIAL_ROOMS:
            self._conn.execute(
                "INSERT INTO rooms (name, area, is_active) VALUES (?, ?, 1)",
                (name, area),
            )
        self._conn.execute(
            "INSERT INTO employees (key, display_name) VALUES (?, ?)",
            ("dina", "ДИНА"),
        )
        self._conn.execute(
            "INSERT INTO employees (key, display_name) VALUES (?, ?)",
            ("lena", "ЛЕНА"),
        )
        self._conn.execute(
            "INSERT INTO employees (key, display_name) VALUES (?, ?)",
            ("olya", "ОЛЯ"),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- rooms ---
    def get_active_rooms(self) -> list[RoomRow]:
        rows = self._conn.execute(
            "SELECT id, name, area, is_active FROM rooms WHERE is_active = 1 ORDER BY name"
        ).fetchall()
        return [RoomRow(int(r["id"]), str(r["name"]), float(r["area"]), bool(r["is_active"])) for r in rows]

    def get_all_rooms(self) -> list[RoomRow]:
        rows = self._conn.execute("SELECT id, name, area, is_active FROM rooms ORDER BY name").fetchall()
        return [RoomRow(int(r["id"]), str(r["name"]), float(r["area"]), bool(r["is_active"])) for r in rows]

    def get_room_by_id(self, room_id: int) -> Optional[RoomRow]:
        r = self._conn.execute(
            "SELECT id, name, area, is_active FROM rooms WHERE id = ?", (room_id,)
        ).fetchone()
        if not r:
            return None
        return RoomRow(int(r["id"]), str(r["name"]), float(r["area"]), bool(r["is_active"]))

    def rooms_by_name(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in self.get_active_rooms():
            out[row.name] = {"id": row.id, "name": row.name, "area": row.area}
        return out

    def add_room(self, name: str, area: float) -> None:
        self._conn.execute(
            "INSERT INTO rooms (name, area, is_active) VALUES (?, ?, 1)",
            (name.strip(), area),
        )
        self._conn.commit()

    def set_room_area(self, room_id: int, area: float) -> None:
        self._conn.execute("UPDATE rooms SET area = ? WHERE id = ?", (area, room_id))
        self._conn.commit()

    def toggle_room_active(self, room_id: int) -> None:
        self._conn.execute(
            "UPDATE rooms SET is_active = CASE is_active WHEN 1 THEN 0 ELSE 1 END WHERE id = ?",
            (room_id,),
        )
        self._conn.commit()

    # --- employees ---
    def get_employees(self) -> list[EmployeeRow]:
        rows = self._conn.execute("SELECT id, key, display_name FROM employees ORDER BY display_name").fetchall()
        return [EmployeeRow(int(r["id"]), str(r["key"]), str(r["display_name"])) for r in rows]

    def employee_name_by_key(self) -> dict[str, str]:
        return {e.key.lower(): e.display_name for e in self.get_employees()}

    def add_employee(self, display_name: str, key: Optional[str] = None) -> EmployeeRow:
        dn = display_name.strip()
        if not dn:
            raise ValueError("Введите имя сотрудника.")
        k = (key or f"emp_{uuid.uuid4().hex[:10]}").strip().lower()
        import re

        if not re.match(r"^[a-z0-9_]{2,40}$", k):
            raise ValueError("Код: 2–40 символов латиницы, цифры и подчёркивание.")
        try:
            cur = self._conn.execute(
                "INSERT INTO employees (key, display_name) VALUES (?, ?)",
                (k, dn),
            )
            self._conn.commit()
            return EmployeeRow(int(cur.lastrowid), k, dn)
        except sqlite3.IntegrityError as e:
            raise ValueError("Такой код уже занят.") from e

    def delete_employee(self, emp_id: int) -> None:
        cnt = self._conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        if cnt <= 1:
            raise ValueError("Нельзя удалить последнего сотрудника.")
        cur = self._conn.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
        self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError("Сотрудник не найден.")

    # --- tasks ---
    def insert_task(
        self,
        created_at_ms: int,
        employee_key: str,
        rooms: list[QueueItem],
        total_area: float,
        comment: Optional[str],
        message_id: Optional[int] = None,
    ) -> int:
        payload = [asdict(qi) for qi in rooms]
        rooms_json = json.dumps(payload, ensure_ascii=False)
        cur = self._conn.execute(
            """
            INSERT INTO tasks (created_at_ms, employee_key, rooms_json, total_area, comment, message_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (created_at_ms, employee_key, rooms_json, total_area, comment, message_id),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get_last_tasks(self, limit: int = 50) -> list[TaskRow]:
        rows = self._conn.execute(
            f"""
            SELECT id, created_at_ms, employee_key, rooms_json, total_area, comment, message_id
            FROM tasks ORDER BY id DESC LIMIT {int(limit)}
            """
        ).fetchall()
        return [
            TaskRow(
                int(r["id"]),
                int(r["created_at_ms"]),
                str(r["employee_key"]),
                str(r["rooms_json"]),
                float(r["total_area"]),
                r["comment"],
                int(r["message_id"]) if r["message_id"] is not None else None,
            )
            for r in rows
        ]

    def get_task(self, task_id: int) -> Optional[tuple[TaskRow, list[QueueItem]]]:
        r = self._conn.execute(
            """
            SELECT id, created_at_ms, employee_key, rooms_json, total_area, comment, message_id
            FROM tasks WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
        if not r:
            return None
        task = TaskRow(
            int(r["id"]),
            int(r["created_at_ms"]),
            str(r["employee_key"]),
            str(r["rooms_json"]),
            float(r["total_area"]),
            r["comment"],
            int(r["message_id"]) if r["message_id"] is not None else None,
        )
        raw = json.loads(task.rooms_json)
        rooms = [QueueItem.from_dict(x) for x in raw]
        return task, rooms
