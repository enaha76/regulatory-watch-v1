"""Tests for web content cleaning helpers (pure / no network)."""

from __future__ import annotations

from app.ingestion.web_extractor import (
    clean_markdown,
    clean_soup,
    normalize_for_hash,
)


class TestCleanMarkdown:
    def test_drops_us_gov_banner_chrome(self):
        md = (
            "An official website of the United States government\n"
            "Here's how you know\n"
            "Real regulatory content begins here.\n"
            "More content."
        )
        out = clean_markdown(md)
        assert "official website" not in out.lower()
        assert "Real regulatory content" in out

    def test_drops_image_only_lines(self):
        md = (
            "[![](logo.png)](https://example.com)\n"
            "The actual policy is here.\n"
        )
        out = clean_markdown(md)
        assert "logo.png" not in out
        assert "actual policy" in out

    def test_collapses_multiple_blank_lines(self):
        md = "Para A\n\n\n\n\nPara B"
        out = clean_markdown(md)
        assert "Para A" in out and "Para B" in out
        # Only one blank between them.
        assert "\n\n\n" not in out

    def test_drops_rulers(self):
        md = "Header\n\n---\n\n***\n\n___\n\nBody"
        out = clean_markdown(md)
        for ruler in ("---", "***", "___"):
            assert ruler not in out

    def test_strips_leading_breadcrumb(self):
        md = (
            "1. [Home](/home)\n"
            "2. [Section](/home/section)\n"
            "3. [Current page](/home/section/current)\n"
            "\n"
            "# Real Title\n"
            "\n"
            "The body of the document."
        )
        out = clean_markdown(md)
        assert "Home" not in out
        assert "Real Title" in out


class TestNormalizeForHash:
    def test_collapses_whitespace(self):
        assert normalize_for_hash("a\n\n  b\t  c") == "a b c"

    def test_strips_markdown_image(self):
        assert "logo.png" not in normalize_for_hash("![alt](logo.png) hello")

    def test_keeps_link_text(self):
        out = normalize_for_hash("Read the [policy](https://x.com/policy).")
        assert "policy" in out
        assert "https" not in out

    def test_drops_table_separator_lines(self):
        out = normalize_for_hash("real text\n| --- | --- |\nmore")
        assert "real text" in out
        assert "more" in out
        assert "---" not in out


class TestCleanSoup:
    def test_strips_nav_and_footer(self):
        from bs4 import BeautifulSoup
        html = """
        <html><body>
          <nav>Menu items</nav>
          <header>Logo</header>
          <main>The real regulation.</main>
          <footer>Cookie banner</footer>
        </body></html>
        """
        soup = clean_soup(BeautifulSoup(html, "html.parser"))
        text = soup.get_text(separator=" ", strip=True)
        assert "real regulation" in text
        assert "Menu items" not in text
        assert "Cookie banner" not in text

    def test_strips_javascript_anchor(self):
        from bs4 import BeautifulSoup
        html = '<div><a href="javascript:void(0)">click</a><p>real</p></div>'
        soup = clean_soup(BeautifulSoup(html, "html.parser"))
        assert soup.find("a") is None
        assert "real" in soup.get_text()

    def test_strips_class_named_sidebar(self):
        from bs4 import BeautifulSoup
        html = '<div><aside class="sidebar">junk</aside><p>main</p></div>'
        soup = clean_soup(BeautifulSoup(html, "html.parser"))
        assert "junk" not in soup.get_text()
        assert "main" in soup.get_text()
