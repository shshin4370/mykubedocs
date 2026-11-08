"""공식문서를 수집해 FAISS 인덱스를 만드는 스크립트.

사용 예:
    python ingest.py                         # 기본 설정으로 수집 + 인덱싱
    python ingest.py --max-pages 50          # 호스트당 최대 50페이지 (빠른 시험용)
    python ingest.py --seed https://docs.redhat.com/en/documentation/openshift_container_platform/latest
    python ingest.py --refresh               # 캐시를 무시하고 다시 다운로드
    python ingest.py --reindex-only          # 크롤링 없이 캐시된 페이지로 인덱스만 다시 생성
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime

import config
from crawler import Crawler, Page, is_allowed, normalize_url


def load_cached_pages() -> list[Page]:
    """data/raw 의 캐시에서 페이지를 읽습니다 (--reindex-only 용)."""
    pages: list[Page] = []
    seen: set[str] = set()
    if not config.RAW_DIR.exists():
        return pages
    for path in sorted(config.RAW_DIR.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        url = d.get("url", "")
        if (
            url
            and url not in seen
            and is_allowed(url, config.ALLOWED_RULES)
            and len(d.get("text", "")) >= config.MIN_PAGE_CHARS
        ):
            seen.add(url)
            pages.append(Page(url, d.get("title", url), d["text"]))
    return pages


def build_index(pages: list[Page]) -> None:
    # LangChain 은 여기서 불러옵니다 (크롤러 단위 테스트가 패키지 없이도 돌도록).
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
    from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

    from rag import get_embeddings

    splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.MARKDOWN,
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    chunks: list[Document] = []
    for page in pages:
        base = Document(page_content=page.text, metadata={"source": page.url, "title": page.title})
        for piece in splitter.split_documents([base]):
            # 제목을 앞에 붙여 검색 단서를 늘립니다.
            piece.page_content = f"[{page.title}]\n{piece.page_content}"
            chunks.append(piece)
    print(f"청크 {len(chunks)}개 생성 (페이지 {len(pages)}개)")
    if not chunks:
        sys.exit("인덱싱할 청크가 없습니다. 크롤링 결과를 확인하세요.")

    embeddings = get_embeddings()
    bs = config.EMBED_BATCH_SIZE
    store = None
    start = time.time()
    for i in range(0, len(chunks), bs):
        batch = chunks[i : i + bs]
        if store is None:
            store = FAISS.from_documents(batch, embeddings)
        else:
            store.add_documents(batch)
        done = min(i + bs, len(chunks))
        print(f"  임베딩 {done}/{len(chunks)} ({time.time() - start:.0f}s)")

    # 새 인덱스를 완성한 뒤에 기존 인덱스를 교체합니다.
    if config.INDEX_DIR.exists():
        shutil.rmtree(config.INDEX_DIR)
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    store.save_local(str(config.INDEX_DIR))

    hosts: dict[str, int] = {}
    for p in pages:
        host = normalize_url(p.url).split("/")[2]
        hosts[host] = hosts.get(host, 0) + 1
    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "num_pages": len(pages),
        "num_chunks": len(chunks),
        "pages_by_host": hosts,
        "embedding_provider": config.EMBEDDING_PROVIDER,
        "embedding_model": (
            config.OPENAI_EMBEDDING_MODEL
            if config.EMBEDDING_PROVIDER == "openai"
            else config.HF_EMBEDDING_MODEL
        ),
    }
    config.INDEX_META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"인덱스 저장 완료: {config.INDEX_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description="공식문서 수집 및 FAISS 인덱스 생성")
    ap.add_argument("--max-pages", type=int, default=config.MAX_PAGES_PER_HOST, help="호스트당 최대 페이지 수")
    ap.add_argument("--max-depth", type=int, default=config.MAX_DEPTH, help="시작 URL로부터의 최대 링크 깊이")
    ap.add_argument("--seed", action="append", default=[], help="시작 URL 추가 (여러 번 지정 가능)")
    ap.add_argument("--refresh", action="store_true", help="캐시를 무시하고 다시 다운로드")
    ap.add_argument("--reindex-only", action="store_true", help="크롤링 없이 캐시로 인덱스만 재생성")
    args = ap.parse_args()

    if args.reindex_only:
        pages = load_cached_pages()
        print(f"캐시에서 {len(pages)}페이지 로드")
    else:
        seeds = config.DEFAULT_SEEDS + config.EXTRA_SEEDS + args.seed
        crawler = Crawler(
            seeds=seeds,
            rules=config.ALLOWED_RULES,
            cache_dir=config.RAW_DIR,
            max_pages_per_host=args.max_pages,
            max_depth=args.max_depth,
            delay=config.CRAWL_DELAY_SEC,
            timeout=config.REQUEST_TIMEOUT_SEC,
            user_agent=config.USER_AGENT,
            min_chars=config.MIN_PAGE_CHARS,
            refresh=args.refresh,
        )
        try:
            pages = crawler.crawl()
        except KeyboardInterrupt:
            pages = crawler.pages
            print(f"\n중단됨 — 지금까지 수집한 {len(pages)}페이지로 계속 진행합니다.")
        print(f"수집 완료: {len(pages)}페이지")

    if not pages:
        sys.exit("수집된 페이지가 없습니다. 네트워크 연결과 시작 URL을 확인하세요.")
    build_index(pages)


if __name__ == "__main__":
    main()
