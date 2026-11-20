# File: seqseec/retrieve.py
# Version: 0.1.2
# Last modified: 2026-11-20 (Track B)
# Change: Removed references to the retired team plan document (comments only).
"""Step 2: find the kit-registry entries that the notes may refer to.

The library is library/kit_registry.csv (hand-curated; every orientation has a
vendor source and a verbatim quote) and library/aliases.csv (names and catalog
numbers -> kit_id, several ids for a family name such as "NEBNext Ultra II").

retrieve(notes, fields) returns candidate entries as payload "chunks":
  1. Alias match. Every alias found in the notes (or in the extracted kit name)
     as whole words, case- and punctuation-insensitive. A match inside a longer
     match is dropped, so "NEBNext Ultra II Directional RNA" does not also count
     as the family name "NEBNext Ultra II". Kit entries win over chemistry entries
     ("dUTP"); a chemistry entry is used only when no kit is named.
  2. Keyword fallback, only when no alias matches: registry entries that share
     enough distinctive words with the notes (e.g. "KAPA HyperPrep stranded mRNA"
     written in another order). These are offered to step 3 as weaker candidates.

This is a lightweight, deterministic retriever over registry entries and their
vendor quotes, not a vector store over full manuals (see the spec sheet's
limitations).
"""
import csv
import os
import re

LIBRARY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "library")
REGISTRY_PATH = os.path.join(LIBRARY_DIR, "kit_registry.csv")
ALIASES_PATH = os.path.join(LIBRARY_DIR, "aliases.csv")

ORIENTATIONS = ("FR", "RF", "UNSTRANDED")
EVIDENCE_TYPES = ("explicit", "inferred_from_chemistry")
KEYWORD_MIN_SHARED = 2
KEYWORD_TOP_K = 3

# Words too common in lab notes to identify a kit.
_STOPWORDS = frozenset("""a an and the of for with to in on by from was were is are kit kits library libraries
prep preparation sample samples rna mrna total illumina seq sequencing sequenced protocol according
manufacturer instructions using used reads read paired single end strand stranded""".split())


def _norm(text):
    """Lower-case, punctuation to spaces, single spaces, padded so ' x ' finds whole words."""
    return " " + re.sub(r"[^a-z0-9]+", " ", str(text).casefold()).strip() + " "


def _tokens(text):
    return {t for t in _norm(text).split() if t not in _STOPWORDS and len(t) > 1}


def load_registry(path=REGISTRY_PATH):
    """Return {kit_id: row} and check every row: known orientation and evidence type, a source and a quote."""
    with open(path, newline="", encoding="utf8") as f:
        rows = list(csv.DictReader(f))
    registry = {}
    for row in rows:
        kid = row["kit_id"].strip()
        if kid in registry:
            raise ValueError(f"duplicate kit_id in registry: {kid}")
        if row["orientation"] not in ORIENTATIONS:
            raise ValueError(f"{kid}: orientation must be one of {ORIENTATIONS}")
        if row["evidence"] not in EVIDENCE_TYPES:
            raise ValueError(f"{kid}: evidence must be one of {EVIDENCE_TYPES}")
        if not (row["source_url"].startswith("https://") and row["source_quote"].strip()):
            raise ValueError(f"{kid}: every entry needs an https source_url and a verbatim source_quote")
        registry[kid] = row
    return registry


def load_aliases(registry, path=ALIASES_PATH):
    """Return [(normalized alias, original alias, (kit_ids...))], longest first."""
    with open(path, newline="", encoding="utf8") as f:
        rows = list(csv.DictReader(f))
    aliases = []
    for row in rows:
        ids = tuple(k.strip() for k in row["kit_ids"].split(";") if k.strip())
        unknown = [k for k in ids if k not in registry]
        if unknown:
            raise ValueError(f"alias {row['alias']!r} points to unknown kit_id(s) {unknown}")
        aliases.append((_norm(row["alias"]), row["alias"], ids))
    return sorted(aliases, key=lambda a: -len(a[0]))


def chunk_for(row, matched_by, matched_alias=None, score=None):
    """Registry row -> payload chunk. The text holds the vendor quote verbatim, so citations can be checked."""
    text = (f"{row['kit_name']} ({row['vendor'] or 'any vendor'}). Chemistry: {row['chemistry']}. "
            f"Source ({row['source_title']}, {row['source_version']}): \"{row['source_quote']}\""
            + (f" Note: {row['evidence_note']}" if row.get("evidence_note") else ""))
    chunk = {"chunk_id": row["kit_id"], "text": text, "kit": row["kit_name"], "vendor": row["vendor"] or None,
             "source": row["source_url"], "version": row["source_version"], "date": row["accessed"]}
    if score is not None:
        chunk["score"] = score
    return chunk, {"kit_id": row["kit_id"], "matched_by": matched_by, "alias": matched_alias,
                   "orientation": row["orientation"], "evidence": row["evidence"], "kind": row["kind"]}


def _alias_matches(text, aliases):
    """Return [(start, end, alias, ids)] with matches contained in a longer match removed."""
    found = []
    for norm_alias, alias, ids in aliases:
        start = text.find(norm_alias)
        while start != -1:
            found.append((start, start + len(norm_alias), alias, ids))
            start = text.find(norm_alias, start + 1)
    kept = [m for m in found
            if not any(o is not m and o[0] <= m[0] and m[1] <= o[1] and (o[1] - o[0]) > (m[1] - m[0])
                       for o in found)]
    return kept


def retrieve(notes, fields=None, *, registry=None, aliases=None):
    """Return {"chunks": [...], "candidates": [...], "method": "alias" | "keyword" | "none"}.

    candidates[i] describes chunks[i]: kit_id, matched_by, alias, orientation, evidence, kind.
    """
    registry = registry or load_registry()
    aliases = aliases or load_aliases(registry)
    fields = fields or {}
    text = _norm(" ".join(str(x) for x in (notes, fields.get("kit_name"), fields.get("chemistry")) if x))

    matches = _alias_matches(text, aliases)
    ids = []
    for _, _, alias, kit_ids in sorted(matches):
        for kid in kit_ids:
            if kid not in ids:
                ids.append(kid)
    if any(registry[k]["kind"] == "kit" for k in ids):
        ids = [k for k in ids if registry[k]["kind"] == "kit"]
    if ids:
        alias_of = {}
        for _, _, alias, kit_ids in matches:
            for kid in kit_ids:
                alias_of.setdefault(kid, alias)
        pairs = [chunk_for(registry[k], "alias", alias_of.get(k)) for k in ids]
        return {"chunks": [c for c, _ in pairs], "candidates": [m for _, m in pairs], "method": "alias"}

    note_tokens = _tokens(text)
    scored = []
    for kid, row in registry.items():
        if row["kind"] != "kit":
            continue
        shared = note_tokens & _tokens(f"{row['kit_name']} {row['vendor']} {row['catalog']}")
        if len(shared) >= KEYWORD_MIN_SHARED:
            scored.append((len(shared), kid))
    scored.sort(key=lambda s: (-s[0], s[1]))
    pairs = [chunk_for(registry[k], "keyword", score=n) for n, k in scored[:KEYWORD_TOP_K]]
    return {"chunks": [c for c, _ in pairs], "candidates": [m for _, m in pairs],
            "method": "keyword" if pairs else "none"}
