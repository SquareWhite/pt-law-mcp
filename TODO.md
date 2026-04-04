# TODO

## Data / Corpus

- Ingest Segurança Social laws (e.g. DL 110/2009 / CRCSPSS and related)
- Ingest the Portaria referenced by CIRS art. 151 (activity code table, likely Portaria n.º 1011/2001) — needed to correctly classify IRS Categoria B coefficients
- Ingest CAE (Classificação das Atividades Económicas) codes from INE

## Server

- On startup, log which laws are referenced in the DB (via REFERENCES edges) but have no corresponding Law node — surfaces missing corpus coverage
