from __future__ import annotations

from typing import Any

import requests


def post_wall(*, access_token: str, owner_id: str, message: str, api_version: str = "5.199") -> int:
    """owner_id вида -123456789 для группы. Возвращает post_id или 0."""
    r = requests.post(
        "https://api.vk.com/method/wall.post",
        data={
            "access_token": access_token,
            "owner_id": owner_id,
            "from_group": "1",
            "message": message,
            "v": api_version,
        },
        timeout=60,
    )
    data: dict[str, Any] = r.json()
    err = data.get("error")
    if err:
        raise RuntimeError(f"VK error {err.get('error_code')}: {err.get('error_msg')}")
    resp = data.get("response") or {}
    return int(resp.get("post_id") or 0)
