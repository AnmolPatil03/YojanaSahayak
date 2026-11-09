from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from yojana.config import ScraperConfig, SourceConfig
from yojana.ingest.scrape import Manifest, PoliteScraper, local_path_for, normalize_url

ROBOTS = "User-agent: *\nDisallow: /private\n"
PAGE = "<html><body><h1>Test Scheme Alpha</h1>" + "<p>Fictional text.</p>" * 200 + "</body></html>"


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_scraper(tmp_path: Path, fake: FakeTime, **kwargs) -> PoliteScraper:
    config = ScraperConfig(user_agent="TestBot/1.0", min_delay_s=2.0)
    return PoliteScraper(
        config, tmp_path, client=httpx.Client(), sleep=fake.sleep, clock=fake.clock, **kwargs
    )


@respx.mock
def test_robots_disallow_is_obeyed(tmp_path: Path) -> None:
    respx.get("https://site.test/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    private = respx.get("https://site.test/private/page").mock(
        return_value=httpx.Response(200, text=PAGE)
    )
    scraper = make_scraper(tmp_path, FakeTime())

    assert scraper.fetch("https://site.test/private/page") is None
    assert private.call_count == 0


@respx.mock
def test_requests_to_same_host_are_spaced_and_identified(tmp_path: Path) -> None:
    respx.get("https://site.test/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    page = respx.get(url__regex=r"https://site\.test/schemes/.*").mock(
        return_value=httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})
    )
    fake = FakeTime()
    scraper = make_scraper(tmp_path, fake)

    scraper.fetch("https://site.test/schemes/a")
    scraper.fetch("https://site.test/schemes/b")

    assert page.call_count == 2
    assert all(call.request.headers["user-agent"] == "TestBot/1.0" for call in page.calls)
    assert len(fake.sleeps) == 2
    assert all(s >= 2.0 for s in fake.sleeps)


@respx.mock
def test_crawl_delay_from_robots_is_respected(tmp_path: Path) -> None:
    respx.get("https://site.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 7\n")
    )
    respx.get(url__regex=r"https://site\.test/p/.*").mock(
        return_value=httpx.Response(200, text=PAGE)
    )
    fake = FakeTime()
    scraper = make_scraper(tmp_path, fake)

    scraper.fetch("https://site.test/p/1")
    scraper.fetch("https://site.test/p/2")

    assert max(fake.sleeps) >= 7.0


@respx.mock
def test_unreachable_robots_means_no_fetch(tmp_path: Path) -> None:
    respx.get("https://down.test/robots.txt").mock(side_effect=httpx.ConnectError("nope"))
    page = respx.get("https://down.test/x").mock(return_value=httpx.Response(200, text=PAGE))
    assert make_scraper(tmp_path, FakeTime()).fetch("https://down.test/x") is None
    assert page.call_count == 0


@respx.mock
def test_missing_robots_allows_everything_and_manifest_is_written(tmp_path: Path) -> None:
    respx.get("https://site.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://site.test/docs/guide.pdf").mock(
        return_value=httpx.Response(
            200, content=b"%PDF-1.4 fake", headers={"content-type": "application/pdf"}
        )
    )
    scraper = make_scraper(tmp_path, FakeTime())

    entry = scraper.fetch("https://site.test/docs/guide.pdf")

    assert entry is not None and entry.path == "site.test/docs-guide.pdf"
    assert (tmp_path / entry.path).read_bytes() == b"%PDF-1.4 fake"
    lines = (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["url"] == "https://site.test/docs/guide.pdf"
    assert Manifest(tmp_path).get("https://site.test/docs/guide.pdf") is not None


@respx.mock
def test_crawl_reads_sitemap_and_filters_patterns(tmp_path: Path) -> None:
    respx.get("https://site.test/robots.txt").mock(return_value=httpx.Response(200, text=""))
    sitemap = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://site.test/schemes/one</loc></url>"
        "<url><loc>https://site.test/about</loc></url>"
        "<url><loc>https://site.test/schemes/two</loc></url>"
        "</urlset>"
    )
    respx.get("https://site.test/sitemap.xml").mock(return_value=httpx.Response(200, text=sitemap))
    pages = respx.get(url__regex=r"https://site\.test/schemes/.*").mock(
        return_value=httpx.Response(200, text=PAGE)
    )
    about = respx.get("https://site.test/about").mock(return_value=httpx.Response(200, text=PAGE))
    source = SourceConfig(
        name="test",
        sitemap="https://site.test/sitemap.xml",
        allow_patterns=[r"^https://site\.test/schemes/"],
        max_pages=5,
    )
    scraper = make_scraper(tmp_path, FakeTime())

    fetched = scraper.crawl(source)
    again = scraper.crawl(source)

    assert sorted(e.url for e in fetched) == [
        "https://site.test/schemes/one",
        "https://site.test/schemes/two",
    ]
    assert about.call_count == 0
    assert again == []
    assert pages.call_count == 2


@respx.mock
def test_js_shell_pages_are_rendered_when_enabled(tmp_path: Path) -> None:
    respx.get("https://site.test/robots.txt").mock(return_value=httpx.Response(200, text=""))
    respx.get("https://site.test/schemes/js").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><div id='app'></div></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    rendered_html = "<html><body><h1>Rendered</h1></body></html>"
    scraper = make_scraper(tmp_path, FakeTime(), renderer=lambda url: rendered_html)

    entry = scraper.fetch("https://site.test/schemes/js", render_js=True)

    assert entry is not None and entry.rendered
    assert (tmp_path / entry.path).read_text(encoding="utf-8") == rendered_html


def test_url_helpers() -> None:
    assert normalize_url("https://Site.test/a/b/#frag") == "https://site.test/a/b"
    assert local_path_for("https://site.test/schemes/x", "text/html").as_posix() == (
        "site.test/schemes-x.html"
    )
