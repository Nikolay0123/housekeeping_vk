from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class QueueItem:
    """Элемент очереди уборки (структура как в Android / legacy Python-боте)."""

    id: int
    name: str
    area: float
    cleaning_type: str
    linen_variant: Optional[int] = None
    linen_profile: Optional[str] = None
    linen_color: Optional[str] = None
    linen_beds: Optional[int] = None

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None or k in ("id", "name", "area", "cleaning_type")}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> QueueItem:
        return cls(
            id=int(d["id"]),
            name=str(d["name"]),
            area=float(d["area"]),
            cleaning_type=str(d.get("cleaning_type") or d.get("cleaningType", "")),
            linen_variant=d.get("linen_variant") if d.get("linen_variant") is not None else d.get("linenVariant"),
            linen_profile=d.get("linen_profile") if d.get("linen_profile") is not None else d.get("linenProfile"),
            linen_color=d.get("linen_color") if d.get("linen_color") is not None else d.get("linenColor"),
            linen_beds=d.get("linen_beds") if d.get("linen_beds") is not None else d.get("linenBeds"),
        )
