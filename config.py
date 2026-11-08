"""프로젝트 전역 설정.

- 경로, 크롤링 허용 규칙(공식문서만), 검색/청크 파라미터를 한곳에서 관리합니다.
- 값은 환경변수(.env)로 덮어쓸 수 있습니다.
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv 가 없어도 동작하도록
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"  # 크롤링 캐시
INDEX_DIR = DATA_DIR / "faiss_index"  # FAISS 인덱스
INDEX_META_PATH = INDEX_DIR / "meta.json"
SESSION_DIR = DATA_DIR / "sessions"  # 채팅 세션 JSON


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 크롤링: 아래 규칙에 맞는 URL만 수집합니다 (공식문서만 사용).
#   host        : 정확히 일치해야 하는 호스트명
#   path_prefix : 이 경로 아래의 페이지만 허용
# ---------------------------------------------------------------------------
ALLOWED_RULES: list[dict[str, str]] = [
    {"host": "kubernetes.io", "path_prefix": "/docs"},
    {"host": "docs.redhat.com", "path_prefix": "/en"},
]

DEFAULT_SEEDS: list[str] = [
    "https://kubernetes.io/docs/home/",
    "https://docs.redhat.com/en",
]

# .env 의 EXTRA_SEEDS="url1,url2" 로 시작 URL을 더 추가할 수 있습니다.
EXTRA_SEEDS: list[str] = [
    s.strip() for s in os.getenv("EXTRA_SEEDS", "").split(",") if s.strip()
]

MAX_PAGES_PER_HOST = _int("MAX_PAGES_PER_HOST", 200)
MAX_DEPTH = _int("MAX_DEPTH", 3)
CRAWL_DELAY_SEC = _float("CRAWL_DELAY_SEC", 0.5)
REQUEST_TIMEOUT_SEC = _int("REQUEST_TIMEOUT_SEC", 20)
MIN_PAGE_CHARS = 200  # 이보다 짧은 페이지는 목차/빈 페이지로 보고 제외
USER_AGENT = os.getenv(
    "CRAWLER_USER_AGENT",
    "DocsRagChatbot/1.0 (educational project; respects robots.txt)",
)

# ---------------------------------------------------------------------------
# 청크 분할 / 검색
# ---------------------------------------------------------------------------
CHUNK_SIZE = _int("CHUNK_SIZE", 1000)
CHUNK_OVERLAP = _int("CHUNK_OVERLAP", 150)
EMBED_BATCH_SIZE = _int("EMBED_BATCH_SIZE", 100)

RETRIEVE_K = _int("RETRIEVE_K", 5)  # 최종 반환 청크 수
RETRIEVE_FETCH_K = _int("RETRIEVE_FETCH_K", 20)  # MMR 후보 수
MAX_HISTORY_TURNS = _int("MAX_HISTORY_TURNS", 6)  # LLM에 넘기는 최근 대화 왕복 수

# ---------------------------------------------------------------------------
# 모델 선택
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()  # openai | anthropic
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano")  # 2일차.ipynb 의 RAG 체인과 동일
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai").lower()  # openai | huggingface
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
HF_EMBEDDING_MODEL = os.getenv("HF_EMBEDDING_MODEL", "BAAI/bge-m3")
