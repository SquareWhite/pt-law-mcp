from src.models import Article
from src.parser.ref_extractor import extract_refs


def _article(text: str, law_id: str = "cirs", number: str = "3") -> Article:
    return Article(
        id=f"{law_id}:art:{number}",
        law_id=law_id,
        number=number,
        text=text,
    )


def test_cross_law_reference():
    a = _article("Os rendimentos previstos no artigo 22.º do CIRS são tributados.")
    refs, _ = extract_refs(a)
    ids = [r.target_id for r in refs]
    assert "cirs:art:22" in ids


def test_cross_law_bis_variant():
    a = _article("Aplica-se o disposto no artigo 88.º-A do CIRC.")
    refs, _ = extract_refs(a)
    assert any(r.target_id == "circ:art:88-A" for r in refs)


def test_cross_law_multiple_articles():
    a = _article("Os artigos 22.º e 23.º do CIRC são aplicáveis.")
    refs, _ = extract_refs(a)
    ids = {r.target_id for r in refs}
    assert "circ:art:22" in ids
    assert "circ:art:23" in ids


def test_internal_reference():
    a = _article("Nos termos do artigo 1.º, considera-se rendimento todo o ganho.", law_id="cirs")
    refs, _ = extract_refs(a)
    ids = [r.target_id for r in refs]
    assert "cirs:art:1" in ids


def test_subarticle_reference():
    a = _article("A importância referida na alínea b) do n.º 3 do artigo 1.º aplica-se aqui.")
    refs, _ = extract_refs(a)
    matching = [r for r in refs if r.target_id == "cirs:art:1"]
    assert matching
    assert matching[0].target_fragment == "n.º 3"


def test_relative_reference_is_ambiguous():
    a = _article("Sem prejuízo do artigo anterior, aplica-se o seguinte.")
    _, ambiguous = extract_refs(a)
    reasons = [amb.reason for amb in ambiguous]
    assert "relative reference" in reasons


def test_law_level_reference_is_ambiguous():
    a = _article("Os rendimentos previstos na Lei Geral Tributária são excluídos.")
    _, ambiguous = extract_refs(a)
    assert any(amb.reason == "law-level reference" for amb in ambiguous)


def test_ref_type_excecao():
    a = _article("Com exceção do previsto no artigo 22.º do CIRS, aplica-se.")
    refs, _ = extract_refs(a)
    matching = [r for r in refs if r.target_id == "cirs:art:22"]
    assert matching
    assert matching[0].ref_type == "exceção"


def test_ref_type_aplicacao():
    a = _article("Aplica-se o disposto no artigo 22.º do CIRS.")
    refs, _ = extract_refs(a)
    matching = [r for r in refs if r.target_id == "cirs:art:22"]
    assert matching
    assert matching[0].ref_type == "aplicação"


def test_no_duplicate_refs():
    a = _article(
        "Nos termos do artigo 22.º do CIRS e nos termos do artigo 22.º do CIRS novamente."
    )
    refs, _ = extract_refs(a)
    ids = [r.target_id for r in refs]
    assert ids.count("cirs:art:22") == 1


def test_context_extracted():
    a = _article("O imposto incide. Nos termos do artigo 22.º do CIRS, considera-se rendimento.")
    refs, _ = extract_refs(a)
    ref = next(r for r in refs if r.target_id == "cirs:art:22")
    assert "artigo 22" in ref.context
