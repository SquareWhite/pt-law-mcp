from __future__ import annotations

import re

from src.models import Article, AmbiguousReference, Reference

LAW_ALIASES: dict[str, str] = {
    "CIRS": "cirs",
    "CIRC": "circ",
    "CIVA": "civa",
    "Código do IRS": "cirs",
    "Código do IRC": "circ",
    "Código do IVA": "civa",
    "Lei Geral Tributária": "lgt",
    "LGT": "lgt",
    "Código de Procedimento e de Processo Tributário": "cppt",
    "CPPT": "cppt",
    "Estatuto dos Benefícios Fiscais": "ebf",
    "EBF": "ebf",
    "Código do Imposto do Selo": "cis",
    "CIS": "cis",
    "Código do Imposto Municipal sobre Imóveis": "cimi",
    "CIMI": "cimi",
    "Código do Imposto Municipal sobre as Transmissões Onerosas de Imóveis": "cimt",
    "CIMT": "cimt",
    "Código do Imposto Único de Circulação": "ciuc",
    "CIUC": "ciuc",
    "Código Fiscal do Investimento": "cfi",
    "CFI": "cfi",
    "Regime Geral das Infrações Tributárias": "rgit",
    "RGIT": "rgit",
    "Regime Complementar do Procedimento de Inspeção Tributária e Aduaneira": "rcpita",
    "RCPITA": "rcpita",
    "Regime Jurídico da Arbitragem em Matéria Tributária": "rjamt",
    "RJAMT": "rjamt",
}

# Alias pattern for use in regexes (longest first to avoid partial matches)
_LAW_PATTERN = "|".join(
    re.escape(k) for k in sorted(LAW_ALIASES, key=len, reverse=True)
)

# 1. Explicit cross-law: "artigo 22.º do CIRS", "artigos 22.º e 23.º do CIRC", "artigo 88.º-A do CIRC"
#    Also handles:
#    - "artigo 4.º ... artigo 5.º, ambos do Código do IRC"
#    - "artigo 63.º-D da Lei Geral Tributária"  (da/das/dos as well as do)
#    - "artigos 78.º-C a 78.º-E e 84.º"        (range separator "a")
_CROSS_LAW_RE = re.compile(
    r"artigos?\s+([\d]+\.º(?:-[A-Z])?(?:\s*[,ea]\s*[\d]+\.º(?:-[A-Z])?)*)"
    r"(?:\s*,\s*ambos)?\s+d[ao]s?\s+(" + _LAW_PATTERN + r")",
    re.IGNORECASE | re.UNICODE,
)

# 2. Internal reference (same law): "nos termos do artigo 22.º", "previsto no artigo 88.º-A"
_INTERNAL_RE = re.compile(
    r"(?:nos\s+termos|previsto|referido|mencionado|disposto)"
    r"\s+(?:no|na|nos|nas|do|da|dos|das)\s+(?:n\.º\s+\d+\s+do\s+)?"
    r"artigos?\s+([\d]+\.º(?:-[A-Z])?(?:\s*[,e]\s*[\d]+\.º(?:-[A-Z])?)*)",
    re.IGNORECASE | re.UNICODE,
)

# 3. Sub-article reference with full article number: "alínea b) do n.º 3 do artigo 22.º"
#    Also catches "n.º 2 do artigo 22.º"
_SUBART_RE = re.compile(
    r"(?:alínea\s+[a-z]\)\s+do\s+)?n\.º\s+(\d+)\s+do\s+artigo\s+([\d]+\.º(?:-[A-Z])?)",
    re.IGNORECASE | re.UNICODE,
)

# 4. Relative references
_RELATIVE_RE = re.compile(
    r"artigo\s+(anterior|seguinte)|(?:presente|mesmo)\s+(capítulo|secção|título)",
    re.IGNORECASE | re.UNICODE,
)

# 5. Full law name references (law-level, no specific article)
_LAW_LEVEL_RE = re.compile(r"(" + _LAW_PATTERN + r")", re.UNICODE)

# Ref-type classifiers
_EXCECAO_RE = re.compile(r"exceç[ãa]o|exceto|salvo", re.IGNORECASE)
_APLICACAO_RE = re.compile(r"aplic[aá]", re.IGNORECASE)


def _get_context(text: str, match: re.Match) -> str:
    """Return the sentence containing the match."""
    start, end = match.span()
    # Expand left to sentence boundary
    left = text.rfind(".", 0, start)
    left = left + 1 if left != -1 else 0
    # Expand right to sentence boundary
    right = text.find(".", end)
    right = right + 1 if right != -1 else len(text)
    return text[left:right].strip()


def _classify_ref_type(context: str) -> str:
    if _EXCECAO_RE.search(context):
        return "exceção"
    if _APLICACAO_RE.search(context):
        return "aplicação"
    return "remissão"


def _parse_article_numbers(raw: str) -> list[str]:
    """Extract article numbers from a raw match group like '22.º, 23.º e 24.º-A'."""
    numbers: list[str] = []
    for m in re.finditer(r"(\d+)\.º(?:-([A-Z]))?", raw):
        num = m.group(1)
        suffix = m.group(2)
        numbers.append(f"{num}-{suffix}" if suffix else num)
    return numbers


def extract_refs(
    article: Article,
) -> tuple[list[Reference], list[AmbiguousReference]]:
    refs: list[Reference] = []
    ambiguous: list[AmbiguousReference] = []
    text = article.text or ""
    seen: set[tuple[str, str]] = set()

    def add_ref(target_id: str, context: str, fragment: str | None = None) -> None:
        key = (article.id, target_id)
        if key in seen:
            return
        seen.add(key)
        refs.append(
            Reference(
                source_id=article.id,
                target_id=target_id,
                context=context,
                ref_type=_classify_ref_type(context),
                target_fragment=fragment,
            )
        )

    # 1. Explicit cross-law references
    for m in _CROSS_LAW_RE.finditer(text):
        raw_nums, law_alias = m.group(1), m.group(2)
        law_id = LAW_ALIASES.get(law_alias, LAW_ALIASES.get(law_alias.upper()))
        if not law_id:
            continue
        context = _get_context(text, m)
        for num in _parse_article_numbers(raw_nums):
            add_ref(f"{law_id}:art:{num}", context)

    # 2. Internal references
    for m in _INTERNAL_RE.finditer(text):
        raw_nums = m.group(1)
        context = _get_context(text, m)
        for num in _parse_article_numbers(raw_nums):
            add_ref(f"{article.law_id}:art:{num}", context)

    # 3. Sub-article references (with explicit article number)
    for m in _SUBART_RE.finditer(text):
        fragment_num, art_raw = m.group(1), m.group(2)
        art_nums = _parse_article_numbers(art_raw)
        if not art_nums:
            continue
        context = _get_context(text, m)
        fragment = f"n.º {fragment_num}"
        for num in art_nums:
            add_ref(f"{article.law_id}:art:{num}", context, fragment)

    # 4. Relative references → ambiguous
    for m in _RELATIVE_RE.finditer(text):
        raw = m.group(0)
        ambiguous.append(
            AmbiguousReference(
                source_id=article.id,
                raw_text=raw,
                reason="relative reference",
                candidates=[],
            )
        )

    # 5. Law-level references → ambiguous
    # Collect spans already covered by cross-law refs so we don't double-report
    cross_law_spans = {m.span() for m in _CROSS_LAW_RE.finditer(text)}

    for m in _LAW_LEVEL_RE.finditer(text):
        alias = m.group(1)
        # Skip if this law name is part of an already-captured cross-law reference
        if any(cs <= m.start() and m.end() <= ce for cs, ce in cross_law_spans):
            continue
        # Skip parenthetical abbreviations like "(CIRS)" — not a reference
        if m.start() > 0 and text[m.start() - 1] == "(":
            continue
        ambiguous.append(
            AmbiguousReference(
                source_id=article.id,
                raw_text=alias,
                reason="law-level reference",
                candidates=[LAW_ALIASES.get(alias, "")],
            )
        )

    return refs, ambiguous
