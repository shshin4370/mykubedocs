"""허용된 공식문서 도메인만 수집하는 크롤러와 HTML→텍스트 변환기.

- 시작 URL에서 출발해 문서 안의 링크를 따라가되, config.ALLOWED_RULES 에 맞는 URL만 방문합니다.
- robots.txt 를 확인하고, 요청 사이에 지연을 두며, 받은 페이지는 디스크에 캐시합니다.
- 이 모듈은 LangChain 에 의존하지 않으므로 네트워크 없이도 단위 테스트할 수 있습니다.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib import robotparser
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, FeatureNotFound

# 문서가 아닌 파일은 건너뜁니다.
SKIP_EXTENSIONS = {
    ".pdf", ".zip", ".gz", ".tgz", ".tar", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".webp", ".ico", ".css", ".js", ".json", ".yaml", ".yml", ".xml", ".txt", ".mp4",
    ".webm", ".woff", ".woff2", ".ttf", ".eot", ".rss", ".atom",
}

# 본문 후보 (앞에 있을수록 우선). 사이트 구조가 바뀌어도 main/body 로 폴백합니다.
CONTENT_SELECTORS = [
    "div.td-content",  # kubernetes.io (Docsy 테마)
    "main",
    "article",
    "div#main-content",
    "div[role=main]",
    "body",
]

# 본문 안에서 제거할 잡음 요소
REMOVE_SELECTORS = [
    "script", "style", "noscript", "svg", "nav", "aside", "footer", "form",
    "button", "iframe", "header",
    ".td-page-meta", ".td-sidebar", ".td-toc", ".feedback--prompt", ".breadcrumb",
]

_TITLE_SUFFIX = re.compile(r"\s*[|\-–]\s*(Kubernetes|Red Hat.*|Red Hat Documentation)\s*$", re.I)


# ---------------------------------------------------------------------------
# URL 유틸
# ---------------------------------------------------------------------------
def normalize_url(url: str) -> str | None:
    """fragment/query 를 제거하고 https 로 통일합니다. 유효하지 않으면 None."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    path = re.sub(r"/{2,}", "/", p.path or "/")
    return urlunparse(("https", p.hostname.lower(), path, "", "", ""))


def is_allowed(url: str, rules: Iterable[dict[str, str]]) -> bool:
    """URL 이 허용 규칙(호스트 + 경로 접두사)에 맞고 문서 파일 형식인지 확인합니다."""
    norm = normalize_url(url)
    if not norm:
        return False
    p = urlparse(norm)
    last = p.path.rsplit("/", 1)[-1]
    if "." in last and "." + last.rsplit(".", 1)[-1].lower() in SKIP_EXTENSIONS:
        return False
    for rule in rules:
        prefix = rule["path_prefix"].rstrip("/")
        if p.hostname == rule["host"] and (p.path == prefix or p.path.startswith(prefix + "/")):
            return True
    return False


# ---------------------------------------------------------------------------
# HTML → 텍스트
# ---------------------------------------------------------------------------
def _make_soup(html: str | bytes) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        return BeautifulSoup(html, "html.parser")


def _clean_text(raw: str) -> str:
    """공백 정리. 코드 블록(```) 안의 들여쓰기는 보존합니다."""
    out: list[str] = []
    in_code = False
    for line in raw.replace("\xa0", " ").splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append(line.strip())
            continue
        out.append(line.rstrip() if in_code else re.sub(r"[ \t]+", " ", line).strip())
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_page(html: str | bytes, base_url: str) -> tuple[str, str, list[str]]:
    """HTML 에서 (제목, 본문 텍스트, 링크 목록)을 추출합니다.

    링크는 사이드바 등 페이지 전체에서 모으고(문서 탐색용),
    본문 텍스트는 잡음을 제거한 본문 영역에서만 만듭니다.
    """
    soup = _make_soup(html)

    # 1) 링크: 잡음 제거 전에 전체에서 수집
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "javascript:", "tel:", "#")):
            continue
        norm = normalize_url(urljoin(base_url, href))
        if norm:
            links.append(norm)

    # 2) 제목
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(" ", strip=True)
    elif soup.title and soup.title.string:
        title = _TITLE_SUFFIX.sub("", soup.title.string.strip())
    else:
        title = base_url

    # 3) 본문 영역 선택
    root = None
    for sel in CONTENT_SELECTORS:
        root = soup.select_one(sel)
        if root is not None:
            break
    if root is None:
        return title, "", links

    # 4) 잡음 제거
    for sel in REMOVE_SELECTORS:
        for el in root.select(sel):
            try:
                el.decompose()
            except Exception:  # 이미 제거된 하위 요소 등
                pass

    # 5) 구조를 보존하는 텍스트 변환 (코드 블록, 제목, 목록)
    for pre in root.find_all("pre"):
        code = pre.get_text().strip("\n")
        pre.replace_with(f"\n```\n{code}\n```\n")
    for level in range(1, 7):
        for h in root.find_all(f"h{level}"):
            h.replace_with(f"\n\n{'#' * level} {h.get_text(' ', strip=True)}\n")
    for br in root.find_all("br"):
        br.replace_with("\n")
    for li in root.find_all("li"):
        li.insert_before("\n- ")
    for cell in root.find_all(["td", "th"]):
        cell.append(" | ")
    for block in root.find_all(["p", "div", "section", "tr", "ul", "ol", "dt", "dd", "blockquote", "table"]):
        block.append("\n")

    text = _clean_text(root.get_text())
    if text and not text.lstrip().startswith("#"):
        text = f"# {title}\n\n{text}"
    return title, text, links


# ---------------------------------------------------------------------------
# 크롤러
# ---------------------------------------------------------------------------
@dataclass
class Page:
    url: str
    title: str
    text: str


class Crawler:
    def __init__(
        self,
        seeds: Iterable[str],
        rules: list[dict[str, str]],
        cache_dir: Path,
        max_pages_per_host: int = 200,
        max_depth: int = 3,
        delay: float = 0.5,
        timeout: int = 20,
        user_agent: str = "DocsRagChatbot/1.0",
        min_chars: int = 200,
        refresh: bool = False,
        log: Callable[[str], None] = print,
        session: requests.Session | None = None,
    ) -> None:
        self.seeds = list(seeds)
        self.rules = rules
        self.cache_dir = Path(cache_dir)
        self.max_pages_per_host = max_pages_per_host
        self.max_depth = max_depth
        self.delay = delay
        self.timeout = timeout
        self.user_agent = user_agent
        self.min_chars = min_chars
        self.refresh = refresh
        self.log = log
        self.session = session or requests.Session()
        self.pages: list[Page] = []  # 중간에 중단해도 지금까지 수집한 결과를 쓸 수 있음
        self._robots: dict[str, robotparser.RobotFileParser] = {}

    # -- robots.txt ---------------------------------------------------------
    def _robots_ok(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        if host not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.session.get(
                    f"https://{host}/robots.txt",
                    timeout=self.timeout,
                    headers={"User-Agent": self.user_agent},
                )
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])  # 확인 불가 시 허용
            self._robots[host] = rp
        return self._robots[host].can_fetch(self.user_agent, url)

    # -- 캐시 ---------------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")

    def _load_cache(self, url: str) -> dict | None:
        path = self._cache_path(url)
        if self.refresh or not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _save_cache(self, url: str, data: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(url).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # -- 다운로드 -------------------------------------------------------------
    def _fetch(self, url: str) -> tuple[str, bytes] | None:
        """(최종 URL, HTML 바이트). 실패하거나 허용 범위를 벗어나면 None."""
        for attempt in range(2):
            try:
                resp = self.session.get(
                    url,
                    timeout=self.timeout,
                    headers={"User-Agent": self.user_agent, "Accept": "text/html"},
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                self.log(f"  ! 요청 실패({exc.__class__.__name__}): {url}")
                time.sleep(1 + attempt)
                continue
            if resp.status_code >= 500:
                time.sleep(1 + attempt)
                continue
            if resp.status_code != 200:
                return None
            if "html" not in resp.headers.get("Content-Type", "").lower():
                return None
            final = normalize_url(resp.url)
            if not final or not is_allowed(final, self.rules):
                return None  # 리다이렉트로 허용 범위를 벗어남
            return final, resp.content
        return None

    # -- 메인 루프 ------------------------------------------------------------
    def crawl(self) -> list[Page]:
        queue: deque[tuple[str, int]] = deque()
        seen: set[str] = set()
        for s in self.seeds:
            n = normalize_url(s)
            if n and is_allowed(n, self.rules) and n not in seen:
                seen.add(n)
                queue.append((n, 0))

        counts: dict[str, int] = defaultdict(int)
        stored: set[str] = set()

        while queue:
            url, depth = queue.popleft()
            host = urlparse(url).hostname or ""
            if counts[host] >= self.max_pages_per_host:
                continue

            data = self._load_cache(url)
            if data is None:
                if not self._robots_ok(url):
                    self.log(f"  - robots.txt 로 제외: {url}")
                    continue
                time.sleep(self.delay)
                fetched = self._fetch(url)
                if fetched is None:
                    continue
                final_url, html = fetched
                title, text, links = extract_page(html, final_url)
                links = sorted({l for l in links if is_allowed(l, self.rules)})
                data = {"url": final_url, "title": title, "text": text, "links": links}
                self._save_cache(url, data)

            if data["url"] not in stored and len(data["text"]) >= self.min_chars:
                stored.add(data["url"])
                counts[host] += 1
                self.pages.append(Page(data["url"], data["title"], data["text"]))
                self.log(f"[{len(self.pages):>4}] depth={depth} {data['url']}")

            if depth < self.max_depth:
                for link in data["links"]:
                    if link not in seen and is_allowed(link, self.rules):
                        seen.add(link)
                        queue.append((link, depth + 1))

        return self.pages
