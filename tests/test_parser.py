from pathlib import Path

from src.parser.article_splitter import split_articles

FIXTURE = Path(__file__).parent / "fixtures" / "sample_article.html"


def _chapters():
    html = FIXTURE.read_text(encoding="utf-8")
    return [("Test Chapter", html)]


def test_article_count():
    articles = split_articles(_chapters(), "cirs")
    # Fixture has: 1,2,3,4,5,6,7,8,88-A,12-B = 10
    assert len(articles) == 10


def test_article_ids():
    articles = split_articles(_chapters(), "cirs")
    ids = {a.id for a in articles}
    assert "cirs:art:1" in ids
    assert "cirs:art:88-A" in ids
    assert "cirs:art:12-B" in ids
    assert "cirs:art:6" in ids  # revoked article still present


def test_article_titles():
    articles = split_articles(_chapters(), "cirs")
    by_id = {a.id: a for a in articles}

    assert by_id["cirs:art:1"].title == "Incidência"
    assert by_id["cirs:art:3"].title == "Rendimentos da categoria B"
    assert by_id["cirs:art:88-A"].title == "Tributação autónoma"


def test_revoked_article():
    articles = split_articles(_chapters(), "cirs")
    by_id = {a.id: a for a in articles}
    art6 = by_id["cirs:art:6"]
    assert art6.title is None or "Abatimentos" in (art6.title or "")
    assert "(Revogado)" in art6.text or art6.title is None


def test_chapter_tracking():
    articles = split_articles(_chapters(), "cirs")
    by_id = {a.id: a for a in articles}

    assert by_id["cirs:art:1"].chapter == "Capítulo I - Incidência"
    assert by_id["cirs:art:4"].chapter == "Capítulo II - Determinação do rendimento coletável"


def test_section_tracking():
    articles = split_articles(_chapters(), "cirs")
    by_id = {a.id: a for a in articles}

    assert by_id["cirs:art:1"].section == "Secção I - Incidência real"
    assert by_id["cirs:art:7"].section == "Secção II - Deduções especiais"


def test_article_text_preserved():
    articles = split_articles(_chapters(), "cirs")
    by_id = {a.id: a for a in articles}

    art1 = by_id["cirs:art:1"]
    assert "sujeitos passivos" in art1.text

    art2 = by_id["cirs:art:2"]
    assert "alínea b)" in art2.text
