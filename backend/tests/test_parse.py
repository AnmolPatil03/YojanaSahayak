from __future__ import annotations

from pathlib import Path

import pymupdf

from yojana.ingest.parse import parse_file, parse_html, urlslug
from yojana.taxonomy import canonical_section, find_states, guess_category

HTML = """
<html><head><title>Test Scheme Alpha | myScheme</title><script>var x=1</script></head>
<body>
<nav>Home | Login</nav>
<main>
  <h1>Test Scheme Alpha</h1>
  <p>Ministry of Fictional Education Affairs</p>
  <h2>Details</h2>
  <p>An   invented    scholarship.</p>
  <h2>Benefits</h2>
  <ul><li>Fictional grant of 100 test-rupees.</li></ul>
  <h3>Additional support</h3>
  <p>Fictional mentoring.</p>
  <h2>Eligibility Criteria</h2>
  <ul><li>Must be a student.</li><li>Age 17 to 25.</li></ul>
  <h2>Documents Required</h2>
  <table><tr><th>Document</th><th>Note</th></tr><tr><td>Aadhaar card</td><td>Copy</td></tr></table>
  <h2>Application Process</h2>
  <ol><li>Register online.</li></ol>
</main>
<footer>Copyright</footer>
</body></html>
"""


def test_html_sections_are_mapped_to_canonical_names() -> None:
    title, sections, _ = parse_html(HTML)
    assert title == "Test Scheme Alpha"
    assert [s.name for s in sections] == [
        "overview",
        "benefits",
        "eligibility",
        "documents",
        "application",
    ]
    benefits = next(s for s in sections if s.name == "benefits")
    assert "Additional support" in benefits.text
    assert "Fictional mentoring." in benefits.text
    eligibility = next(s for s in sections if s.name == "eligibility")
    assert eligibility.text == "- Must be a student.\n- Age 17 to 25."


def test_html_whitespace_noise_and_tables() -> None:
    _, sections, plain = parse_html(HTML)
    overview = sections[0]
    assert "An invented scholarship." in overview.text
    assert "Login" not in plain and "var x" not in plain and "Copyright" not in plain
    documents = next(s for s in sections if s.name == "documents")
    assert "Aadhaar card | Copy" in documents.text


def test_hindi_headings_are_recognised() -> None:
    html = (
        "<h1>परीक्षण योजना</h1><h2>लाभ</h2><p>काल्पनिक लाभ।</p>"
        "<h2>पात्रता</h2><p>आवेदक किसान हो।</p><h2>आवश्यक दस्तावेज़</h2><p>आधार कार्ड</p>"
    )
    _, sections, _ = parse_html(html)
    assert [s.name for s in sections] == ["benefits", "eligibility", "documents"]


def test_canonical_section_mapping() -> None:
    assert canonical_section("Documents Required") == "documents"
    assert canonical_section("Who is not eligible?") == "exclusions"
    assert canonical_section("Eligibility") == "eligibility"
    assert canonical_section("How to Apply") == "application"
    assert canonical_section("आवेदन प्रक्रिया") == "application"
    assert canonical_section("Scheme Details") == "overview"
    assert canonical_section("Random words") is None


def _make_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 72), "Test Scheme Omega", fontsize=20, fontname="hebo")
    page.insert_text((60, 120), "Eligibility", fontsize=14, fontname="hebo")
    page.insert_text((60, 150), "- The applicant must be a fictional farmer.", fontsize=10)
    page = doc.new_page()
    page.insert_text((60, 72), "Documents Required", fontsize=14, fontname="hebo")
    page.insert_text((60, 100), "- Fictional land record.", fontsize=10)
    doc.save(path)


def test_pdf_sections_keep_page_numbers(tmp_path: Path) -> None:
    pdf = tmp_path / "omega.pdf"
    _make_pdf(pdf)
    doc = parse_file(pdf, relative_to=tmp_path)
    assert doc.meta.scheme_name == "Test Scheme Omega"
    by_name = {s.name: s for s in doc.sections}
    assert by_name["eligibility"].first_page == 1
    assert by_name["documents"].first_page == 2
    assert "fictional land record" in by_name["documents"].text.lower()
    assert doc.kind == "pdf"


def test_sidecar_metadata_overrides_inference(tmp_path: Path) -> None:
    page = tmp_path / "x.html"
    page.write_text(HTML, encoding="utf-8")
    (tmp_path / "x.html.meta.yaml").write_text(
        "scheme_id: alpha\nstate: Goa\ncategory: education\nsource_url: https://example.org/a\n",
        encoding="utf-8",
    )
    doc = parse_file(page, relative_to=tmp_path)
    assert doc.meta.scheme_id == "alpha"
    assert doc.meta.state == "Goa"
    assert doc.meta.source_url == "https://example.org/a"
    assert doc.meta.ministry == "Ministry of Fictional Education Affairs"


def test_scheme_id_comes_from_url_slug(tmp_path: Path) -> None:
    page = tmp_path / "y.html"
    page.write_text(HTML, encoding="utf-8")
    doc = parse_file(page, relative_to=tmp_path, source_url="https://site.test/hi/schemes/abc-1")
    assert doc.meta.scheme_id == "abc-1"
    assert urlslug("https://site.test/schemes/abc-1/") == "abc-1"


def test_state_and_category_helpers() -> None:
    assert find_states("Farmers in Tamil Nadu and Kerala") == ["Tamil Nadu", "Kerala"]
    assert find_states("महाराष्ट्र के किसान") == ["Maharashtra"]
    assert find_states("goal setting") == []
    assert guess_category("A scholarship for college students") == "education"
    assert guess_category("Seed grant for startup founders") == "business"
