"""채팅 세션 저장소 (JSON 파일).

세션 하나 = data/sessions/<id>.json
    {"id", "title", "created_at", "updated_at",
     "messages": [{"role": "user"|"assistant", "content": str, "sources": [...]}]}

앱을 껐다 켜도 과거 대화가 유지됩니다.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import config

_ID_RE = re.compile(r"^[a-f0-9]{12}$")
TITLE_MAX = 30


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dir(base: Path | None) -> Path:
    d = Path(base) if base else config.SESSION_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(session_id: str, base: Path | None) -> Path:
    # 경로 조작 방지: 12자리 16진수 id 만 허용
    if not _ID_RE.match(session_id or ""):
        raise ValueError(f"잘못된 세션 id: {session_id!r}")
    return _dir(base) / f"{session_id}.json"


def new_session() -> dict:
    """메모리에만 있는 빈 세션을 만듭니다 (첫 메시지가 생기면 저장)."""
    now = _now()
    return {
        "id": uuid.uuid4().hex[:12],
        "title": "새 채팅",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


def title_from(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= TITLE_MAX else one_line[: TITLE_MAX - 1] + "…"


def save_session(session: dict, base: Path | None = None) -> None:
    """원자적으로 저장합니다 (쓰는 도중 중단돼도 기존 파일이 깨지지 않음)."""
    session["updated_at"] = _now()
    path = _path(session["id"], base)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_session(session_id: str, base: Path | None = None) -> dict | None:
    try:
        return json.loads(_path(session_id, base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete_session(session_id: str, base: Path | None = None) -> bool:
    try:
        _path(session_id, base).unlink()
        return True
    except (OSError, ValueError):
        return False


def list_sessions(base: Path | None = None) -> list[dict]:
    """최근 대화 순으로 (id, title, updated_at) 목록을 돌려줍니다."""
    items: list[dict] = []
    for p in _dir(base).glob("*.json"):
        if not _ID_RE.match(p.stem):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append(
            {
                "id": d.get("id", p.stem),
                "title": d.get("title", "새 채팅"),
                "updated_at": d.get("updated_at", ""),
            }
        )
    return sorted(items, key=lambda x: x["updated_at"], reverse=True)
