"""네트워크·LLM 없이 실행되는 핵심 로직 테스트.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import storage  # noqa: E402
from crawler import Crawler, extract_page, is_allowed, normalize_url  # noqa: E402

RULES = config.ALLOWED_RULES

K8S_HTML = """
<html><head><title>Pods | Kubernetes</title></head><body>
<header><a href="/">logo</a></header>
<aside class="td-sidebar"><a href="/docs/concepts/workloads/">Workloads</a></aside>
<main><div class="td-content">
  <h1>Pods</h1>
  <p>A Pod is the smallest deployable unit.</p>
  <h2>Using Pods</h2>
  <ul><li>First item</li><li>Second item</li></ul>
  <pre><code>kubectl get pods
  -o wide</code></pre>
  <a href="/docs/concepts/workloads/controllers/deployment/#intro">Deployment</a>
  <a href="https://example.com/evil">external</a>
  <a href="/ko/docs/home/">Korean</a>
  <a href="/docs/assets/guide.pdf">pdf</a>
  <a href="mailto:a@b.c">mail</a>
</div></main>
<footer>Footer text that must not appear</footer>
</body></html>
"""


class UrlRuleTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(
            normalize_url("http://Kubernetes.io//docs/home/?x=1#top"),
            "https://kubernetes.io/docs/home/",
        )
        self.assertIsNone(normalize_url("ftp://kubernetes.io/docs/"))
        self.assertIsNone(normalize_url("not a url"))

    def test_allowed(self):
        ok = [
            "https://kubernetes.io/docs/home/",
            "https://kubernetes.io/docs",
            "https://docs.redhat.com/en",
            "https://docs.redhat.com/en/documentation/openshift_container_platform/latest",
        ]
        bad = [
            "https://kubernetes.io/blog/2024/",
            "https://kubernetes.io/ko/docs/home/",
            "https://kubernetes.io/docsx/",
            "https://docs.redhat.com/ko/documentation/x",
            "https://docs.redhat.com/entry",
            "https://access.redhat.com/en/solutions/1",
            "https://example.com/docs/",
            "https://kubernetes.io/docs/guide.pdf",
        ]
        for u in ok:
            self.assertTrue(is_allowed(u, RULES), u)
        for u in bad:
            self.assertFalse(is_allowed(u, RULES), u)


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.title, self.text, self.links = extract_page(K8S_HTML, "https://kubernetes.io/docs/concepts/workloads/pods/")

    def test_title_and_body(self):
        self.assertEqual(self.title, "Pods")
        self.assertIn("A Pod is the smallest deployable unit.", self.text)
        self.assertIn("## Using Pods", self.text)
        self.assertIn("- First item", self.text)
        self.assertNotIn("Footer text", self.text)
        self.assertNotIn("logo", self.text)

    def test_code_block_keeps_indent(self):
        self.assertIn("```\nkubectl get pods\n  -o wide\n```", self.text)

    def test_links(self):
        self.assertIn("https://kubernetes.io/docs/concepts/workloads/", self.links)  # 사이드바 링크도 수집
        self.assertIn("https://kubernetes.io/docs/concepts/workloads/controllers/deployment/", self.links)
        self.assertNotIn("mailto:a@b.c", self.links)
        self.assertTrue(all(not l.startswith("mailto") for l in self.links))


class FakeResponse:
    def __init__(self, url: str, html: str = "", status: int = 200, ctype: str = "text/html; charset=utf-8"):
        self.url = url
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        self.content = html.encode("utf-8")
        self.text = html


class FakeSession:
    """requests.Session 대체. 요청한 URL 을 기록합니다."""

    def __init__(self, pages: dict[str, str], robots: str = ""):
        self.pages = pages
        self.robots = robots
        self.requested: list[str] = []

    def get(self, url, **kwargs):
        if url.endswith("/robots.txt"):
            return FakeResponse(url, self.robots, 200 if self.robots else 404, "text/plain")
        self.requested.append(url)
        if url in self.pages:
            return FakeResponse(url, self.pages[url])
        return FakeResponse(url, "", 404)


def page(title: str, links: list[str], body: str = "lorem ipsum " * 40) -> str:
    anchors = "".join(f'<a href="{l}">x</a>' for l in links)
    return f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1><p>{body}</p>{anchors}</main></body></html>"


class CrawlerTests(unittest.TestCase):
    def make(self, pages, tmp, robots="", **kw):
        sess = FakeSession(pages, robots)
        crawler = Crawler(
            seeds=["https://kubernetes.io/docs/home/", "https://docs.redhat.com/en"],
            rules=RULES,
            cache_dir=Path(tmp),
            delay=0,
            log=lambda *_: None,
            session=sess,
            **kw,
        )
        return crawler, sess

    def test_only_allowed_urls_are_fetched(self):
        pages = {
            "https://kubernetes.io/docs/home/": page("Home", [
                "/docs/concepts/", "https://example.com/x", "/ko/docs/home/", "/docs/file.pdf",
            ]),
            "https://kubernetes.io/docs/concepts/": page("Concepts", ["/docs/tasks/"]),
            "https://kubernetes.io/docs/tasks/": page("Tasks", []),
            "https://docs.redhat.com/en": page("Red Hat", ["/en/documentation/rhel/9"]),
            "https://docs.redhat.com/en/documentation/rhel/9": page("RHEL 9", []),
        }
        with tempfile.TemporaryDirectory() as tmp:
            crawler, sess = self.make(pages, tmp)
            result = crawler.crawl()
        titles = sorted(p.title for p in result)
        self.assertEqual(titles, ["Concepts", "Home", "RHEL 9", "Red Hat", "Tasks"])
        for url in sess.requested:
            self.assertTrue(is_allowed(url, RULES), f"허용되지 않은 URL 요청: {url}")

    def test_depth_and_host_limits(self):
        pages = {
            "https://kubernetes.io/docs/home/": page("A", ["/docs/b/"]),
            "https://kubernetes.io/docs/b/": page("B", ["/docs/c/"]),
            "https://kubernetes.io/docs/c/": page("C", []),
            "https://docs.redhat.com/en": page("R", []),
        }
        with tempfile.TemporaryDirectory() as tmp:
            crawler, _ = self.make(pages, tmp, max_depth=1)
            titles = sorted(p.title for p in crawler.crawl())
        self.assertEqual(titles, ["A", "B", "R"])  # 깊이 1 까지만

        with tempfile.TemporaryDirectory() as tmp:
            crawler, _ = self.make(pages, tmp, max_depth=5, max_pages_per_host=2)
            titles = sorted(p.title for p in crawler.crawl())
        self.assertEqual(titles, ["A", "B", "R"])  # 호스트당 2페이지

    def test_robots_txt_is_respected(self):
        pages = {
            "https://kubernetes.io/docs/home/": page("Home", ["/docs/private/"]),
            "https://kubernetes.io/docs/private/": page("Private", []),
            "https://docs.redhat.com/en": page("R", []),
        }
        robots = "User-agent: *\nDisallow: /docs/private/\n"
        with tempfile.TemporaryDirectory() as tmp:
            crawler, sess = self.make(pages, tmp, robots=robots)
            titles = sorted(p.title for p in crawler.crawl())
        self.assertNotIn("Private", titles)
        self.assertNotIn("https://kubernetes.io/docs/private/", sess.requested)

    def test_cache_prevents_refetch(self):
        pages = {
            "https://kubernetes.io/docs/home/": page("Home", []),
            "https://docs.redhat.com/en": page("R", []),
        }
        with tempfile.TemporaryDirectory() as tmp:
            first, sess1 = self.make(pages, tmp)
            first.crawl()
            self.assertEqual(len(sess1.requested), 2)
            second, sess2 = self.make(pages, tmp)
            result = second.crawl()
            self.assertEqual(len(result), 2)
            self.assertEqual(sess2.requested, [])  # 캐시만 사용


    def test_redirect_outside_allowed_range_is_dropped(self):
        class RedirectSession(FakeSession):
            def get(self, url, **kwargs):
                if url.endswith("/robots.txt"):
                    return super().get(url, **kwargs)
                self.requested.append(url)
                if url == "https://kubernetes.io/docs/home/":
                    # 허용 범위 밖(다른 도메인)으로 리다이렉트된 응답
                    return FakeResponse("https://example.com/landing", page("Evil", []))
                return FakeResponse(url, page("R", []))

        with tempfile.TemporaryDirectory() as tmp:
            crawler = Crawler(
                seeds=["https://kubernetes.io/docs/home/", "https://docs.redhat.com/en"],
                rules=RULES, cache_dir=Path(tmp), delay=0, log=lambda *_: None,
                session=RedirectSession({}),
            )
            titles = [p.title for p in crawler.crawl()]
        self.assertEqual(titles, ["R"])


class StorageTests(unittest.TestCase):
    def test_roundtrip_list_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            s = storage.new_session()
            s["title"] = storage.title_from("Pod가 CrashLoopBackOff 일 때 어떻게 하나요? " * 3)
            s["messages"] = [
                {"role": "user", "content": "안녕"},
                {"role": "assistant", "content": "반갑습니다", "sources": [{"n": 1, "title": "t", "url": "u"}]},
            ]
            storage.save_session(s, base)

            loaded = storage.load_session(s["id"], base)
            self.assertEqual(loaded["messages"], s["messages"])
            self.assertLessEqual(len(loaded["title"]), storage.TITLE_MAX)

            self.assertEqual([x["id"] for x in storage.list_sessions(base)], [s["id"]])
            self.assertTrue(storage.delete_session(s["id"], base))
            self.assertEqual(storage.list_sessions(base), [])
            self.assertIsNone(storage.load_session(s["id"], base))

    def test_recent_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            a, b = storage.new_session(), storage.new_session()
            a["title"], b["title"] = "A", "B"
            storage.save_session(a, base)
            storage.save_session(b, base)
            a["updated_at"], b["updated_at"] = "2020-01-01T00:00:00", "2030-01-01T00:00:00"
            for s in (a, b):  # save_session 이 시각을 덮어쓰므로 파일을 직접 갱신
                (base / f"{s['id']}.json").write_text(
                    __import__("json").dumps(s, ensure_ascii=False), encoding="utf-8"
                )
            self.assertEqual([x["title"] for x in storage.list_sessions(base)], ["B", "A"])

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertIsNone(storage.load_session("../../etc/passwd", base))
            self.assertFalse(storage.delete_session("../x", base))
            with self.assertRaises(ValueError):
                storage.save_session({"id": "../evil", "messages": []}, base)


class RagHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import rag  # noqa: F401
        except ImportError as exc:  # langchain-core 미설치 환경
            raise unittest.SkipTest(f"langchain-core 가 필요합니다: {exc}")
        cls.rag = rag

    def test_build_context_groups_by_url(self):
        from langchain_core.documents import Document

        docs = [
            Document(page_content="chunk A1", metadata={"source": "https://x/a", "title": "A"}),
            Document(page_content="chunk B1", metadata={"source": "https://x/b", "title": "B"}),
            Document(page_content="chunk A2", metadata={"source": "https://x/a", "title": "A"}),
        ]
        context, sources = self.rag.build_context(docs)
        self.assertEqual([s["n"] for s in sources], [1, 2])
        self.assertEqual([s["url"] for s in sources], ["https://x/a", "https://x/b"])
        self.assertIn("chunk A1", context.split("=====")[0])
        self.assertIn("chunk A2", context.split("=====")[0])

    def test_to_messages_limits_turns(self):
        history = []
        for i in range(10):
            history += [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]
        msgs = self.rag.to_messages(history, max_turns=2)
        self.assertEqual([m.content for m in msgs], ["q8", "a8", "q9", "a9"])
        self.assertEqual(self.rag.to_messages(history, max_turns=0), [])


if __name__ == "__main__":
    unittest.main()
