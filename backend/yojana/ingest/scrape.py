"""Polite scraper for public scheme pages.

It reads robots.txt before touching a host and obeys it (including Crawl-delay),
spaces requests to the same host by at least two seconds, identifies itself with a
descriptive User-Agent, and records every saved file in `data/raw/manifest.jsonl`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from yojana.config import ScraperConfig, Settings, SourceConfig, get_settings
from yojana.taxonomy import slugify

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.jsonl"
_MIN_STATIC_TEXT = 600


@dataclass(slots=True)
class ManifestEntry:
    url: str
    path: str
    sha256: str
    content_type: str
    status: int
    fetched_at: str
    rendered: bool = False
    source: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "url": self.url,
                "path": self.path,
                "sha256": self.sha256,
                "content_type": self.content_type,
                "status": self.status,
                "fetched_at": self.fetched_at,
                "rendered": self.rendered,
                "source": self.source,
            },
            ensure_ascii=False,
        )


class Manifest:
    """Append-only JSONL log of fetched files; the last entry per URL wins."""

    def __init__(self, raw_dir: Path) -> None:
        self.path = raw_dir / MANIFEST_NAME
        self._by_url: dict[str, ManifestEntry] = {}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = ManifestEntry(**json.loads(line))
                except (TypeError, json.JSONDecodeError):
                    continue
                self._by_url[entry.url] = entry

    def get(self, url: str) -> ManifestEntry | None:
        return self._by_url.get(url)

    def by_path(self) -> dict[str, ManifestEntry]:
        return {entry.path: entry for entry in self._by_url.values()}

    def add(self, entry: ManifestEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(entry.to_json() + "\n")
        self._by_url[entry.url] = entry

    def __len__(self) -> int:
        return len(self._by_url)


def normalize_url(url: str) -> str:
    """Drop fragments and trailing slashes so the same page is fetched once."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", parsed.query, ""))


def local_path_for(url: str, content_type: str) -> Path:
    parsed = urlparse(url)
    ext = ".pdf" if "pdf" in content_type or parsed.path.lower().endswith(".pdf") else ".html"
    path = parsed.path.strip("/")
    if path.lower().endswith((".pdf", ".html", ".htm")):
        path = path.rsplit(".", 1)[0]
    stem = slugify(path.replace("/", "-") or "index", max_length=120)
    if parsed.query:
        stem += "-" + hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
    return Path(parsed.netloc.lower()) / f"{stem}{ext}"


class PoliteScraper:
    """Fetches pages while respecting robots.txt and per-host rate limits."""

    def __init__(
        self,
        config: ScraperConfig,
        raw_dir: Path,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        renderer: Callable[[str], str] | None = None,
    ) -> None:
        self.config = config
        self.raw_dir = raw_dir
        self.manifest = Manifest(raw_dir)
        self._client = client or httpx.Client(
            timeout=config.timeout_s,
            follow_redirects=True,
            headers={"User-Agent": config.user_agent},
        )
        self._client.headers["User-Agent"] = config.user_agent
        self._sleep = sleep
        self._clock = clock
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}
        self._renderer = renderer

    def close(self) -> None:
        self._client.close()

    def _wait_for_host(self, host: str) -> None:
        delay = max(self.config.min_delay_s, self._crawl_delay(host))
        last = self._last_request.get(host)
        if last is not None:
            remaining = delay - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()

    def _robots_for(self, url: str) -> RobotFileParser | None:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        parser = RobotFileParser()
        robots_url = origin + "/robots.txt"
        parser.set_url(robots_url)
        self._wait_for_host(parsed.netloc)
        try:
            response = self._client.get(robots_url)
        except httpx.HTTPError as exc:
            logger.warning("Could not read %s (%s); treating host as disallowed", robots_url, exc)
            self._robots[origin] = None
            return None
        if response.status_code in (401, 403):
            parser.disallow_all = True
        elif response.status_code >= 500:
            logger.warning(
                "robots.txt at %s returned %s; skipping host", robots_url, response.status_code
            )
            self._robots[origin] = None
            return None
        elif response.status_code >= 400:
            parser.allow_all = True
        else:
            parser.parse(response.text.splitlines())
        self._robots[origin] = parser
        return parser

    def _crawl_delay(self, host: str) -> float:
        for origin, parser in self._robots.items():
            if parser is not None and urlparse(origin).netloc == host:
                delay = parser.crawl_delay(self.config.user_agent)
                if delay:
                    return float(delay)
        return 0.0

    def allowed(self, url: str) -> bool:
        """True when robots.txt permits fetching `url` with our User-Agent."""
        parser = self._robots_for(url)
        return parser is not None and parser.can_fetch(self.config.user_agent, url)

    def _get(self, url: str) -> httpx.Response:
        self._wait_for_host(urlparse(url).netloc)
        return self._client.get(url)

    def fetch(self, url: str, *, source: str = "", render_js: bool = False) -> ManifestEntry | None:
        """Download one URL into `data/raw/` and record it in the manifest."""
        url = normalize_url(url)
        if not self.allowed(url):
            logger.info("robots.txt disallows %s", url)
            return None
        try:
            response = self._get(url)
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return None
        if response.status_code != 200:
            logger.warning("Skipping %s: HTTP %s", url, response.status_code)
            return None

        content_type = response.headers.get("content-type", "text/html").split(";")[0].strip()
        body = response.content
        rendered = False
        if (
            "html" in content_type
            and render_js
            and _visible_text_length(response.text) < _MIN_STATIC_TEXT
        ):
            html = self._render(url)
            if html:
                body, rendered = html.encode("utf-8"), True

        relative = local_path_for(url, content_type)
        target = self.raw_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        entry = ManifestEntry(
            url=url,
            path=relative.as_posix(),
            sha256=hashlib.sha256(body).hexdigest(),
            content_type=content_type,
            status=response.status_code,
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
            rendered=rendered,
            source=source,
        )
        self.manifest.add(entry)
        return entry

    def _render(self, url: str) -> str | None:
        renderer = self._renderer or _playwright_renderer(self.config.user_agent)
        if renderer is None:
            return None
        self._wait_for_host(urlparse(url).netloc)
        try:
            return renderer(url)
        except Exception as exc:
            logger.warning("Rendering %s failed: %s", url, exc)
            return None

    def sitemap_urls(self, sitemap_url: str, depth: int = 0) -> Iterator[str]:
        """Yield page URLs from a sitemap, following sitemap indexes two levels deep."""
        if depth > 2 or not self.allowed(sitemap_url):
            return
        try:
            response = self._get(sitemap_url)
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch sitemap %s: %s", sitemap_url, exc)
            return
        if response.status_code != 200:
            return
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            return
        namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        if root.tag.endswith("sitemapindex"):
            for loc in root.iter(f"{namespace}loc"):
                if loc.text:
                    yield from self.sitemap_urls(loc.text.strip(), depth + 1)
            return
        for loc in root.iter(f"{namespace}loc"):
            if loc.text:
                yield loc.text.strip()

    def crawl(self, source: SourceConfig, *, refresh_days: float = 7.0) -> list[ManifestEntry]:
        """Fetch up to `source.max_pages` pages matching the source's allow patterns."""
        patterns = [re.compile(p) for p in source.allow_patterns]

        def matches(url: str) -> bool:
            return not patterns or any(p.search(url) for p in patterns)

        queue: deque[str] = deque()
        seen: set[str] = set()
        if source.sitemap:
            queue.extend(u for u in self.sitemap_urls(source.sitemap) if matches(u))
        queue.extend(source.start_urls)

        cutoff = datetime.now(UTC) - timedelta(days=refresh_days)
        fetched: list[ManifestEntry] = []
        while queue and len(fetched) < source.max_pages:
            url = normalize_url(queue.popleft())
            if url in seen:
                continue
            seen.add(url)
            previous = self.manifest.get(url)
            if previous and datetime.fromisoformat(previous.fetched_at) > cutoff:
                continue
            is_seed = url in {normalize_url(u) for u in source.start_urls}
            if not matches(url) and not is_seed:
                continue
            entry = self.fetch(url, source=source.name, render_js=source.render_js)
            if entry is None:
                continue
            if matches(url):
                fetched.append(entry)
            if entry.path.endswith(".html"):
                html = (self.raw_dir / entry.path).read_text(encoding="utf-8", errors="replace")
                queue.extend(u for u in extract_links(html, url) if matches(u) and u not in seen)
        return fetched


def extract_links(html: str, base_url: str) -> Iterable[str]:
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base_url).netloc
    for anchor in soup.find_all("a", href=True):
        url = normalize_url(urljoin(base_url, str(anchor["href"])))
        if urlparse(url).netloc == host and url.startswith(("http://", "https://")):
            yield url


def _visible_text_length(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    return len(soup.get_text(" ", strip=True))


def _playwright_renderer(user_agent: str) -> Callable[[str], str] | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning(
            "This page needs JavaScript. Install the 'render' extra "
            "(scripts\\setup.ps1 -Render) to render it; saving the static HTML instead."
        )
        return None

    def render(url: str) -> str:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=user_agent)
                page.goto(url, wait_until="networkidle", timeout=45_000)
                return page.content()
            finally:
                browser.close()

    return render


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch public scheme pages into data/raw/.")
    parser.add_argument("--source", help="Only crawl the source with this name")
    parser.add_argument("--max-pages", type=int, help="Override max_pages for each source")
    parser.add_argument("--refresh-days", type=float, default=7.0)
    parser.add_argument("--url", action="append", default=[], help="Fetch a single URL")
    args = parser.parse_args(argv)
    run(get_settings(), args.source, args.max_pages, args.refresh_days, args.url)


def run(
    settings: Settings,
    source_name: str | None = None,
    max_pages: int | None = None,
    refresh_days: float = 7.0,
    urls: list[str] | None = None,
) -> list[ManifestEntry]:
    config = settings.scraper()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    scraper = PoliteScraper(config, settings.raw_dir)
    fetched: list[ManifestEntry] = []
    try:
        for url in urls or []:
            entry = scraper.fetch(url, source="manual")
            if entry:
                fetched.append(entry)
        if urls:
            return fetched
        for source in config.sources:
            if not source.enabled or (source_name and source.name != source_name):
                continue
            if max_pages is not None:
                source = source.model_copy(update={"max_pages": max_pages})
            logger.info("Crawling %s (up to %d pages)", source.name, source.max_pages)
            fetched.extend(scraper.crawl(source, refresh_days=refresh_days))
    finally:
        scraper.close()
    logger.info("Fetched %d pages", len(fetched))
    return fetched


if __name__ == "__main__":
    main()
