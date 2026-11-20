# File: scripts/build_spec_docx.py
# Version: 0.1.0
# Last modified: 2026-11-20 (Track B)
# Change: Build the spec sheet .docx (for Google Docs) from the Markdown, styled like the proposal.
"""Build docs/SeqSeec_SpecSheet.docx from docs/SeqSeec_SpecSheet.md.

The Markdown file is the source; this .docx is for uploading to Google Docs
(File > Open > Upload, or drag into Drive and "Open with Google Docs") so the
team can edit and comment together. The layout follows our proposal: Arial
12 pt in dark grey, a title page, numbered bold section and subsection
headings ("1.1 App name and link."), 1-inch margins on US Letter, and Google
Docs' link blue.

What the script changes on the way (the Markdown itself is not modified):
  * the "# ..." title and byline line become a title page, followed by a page break;
  * "## Section" headings are numbered 1., 2., 3.; the Appendix keeps its name;
  * a paragraph that opens with a bold label ("**App name and link.** text")
    becomes a numbered subsection heading ("1.1 App name and link.") followed by the text.

Needs pandoc (tested with 3.1). Usage (repo root):  python scripts/build_spec_docx.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "SeqSeec_SpecSheet.md")
DST = os.path.join(ROOT, "docs", "SeqSeec_SpecSheet.docx")

INK = "333333"       # proposal body text colour
LINK = "1155CC"      # Google Docs link blue
SMALL_WORDS = {"a", "an", "and", "or", "of", "the", "to", "in", "on", "for", "by", "with"}
PAGE_BREAK = '```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```'


# ---------- Markdown -> pandoc input ----------

def title_case(text):
    """'App name and link.' -> 'App Name and Link.' (the course template's capitalisation)."""
    words = text.split(" ")
    return " ".join(w if (i and w.lower() in SMALL_WORDS) or w[:1].isupper() else w[:1].upper() + w[1:]
                    for i, w in enumerate(words))


def restructure(md):
    lines = md.split("\n")
    title = lines[0].lstrip("# ").strip()
    byline = lines[2].strip() if len(lines) > 2 else ""
    body = "\n".join(lines[3:])

    parts = [p.strip() for p in byline.split("·")]
    authors = parts[1] if len(parts) > 1 else ""
    version = parts[2] if len(parts) > 2 else ""
    front = (f"---\ntitle: \"{title.replace(' — ', ': ')}\"\n"
             f"author:\n  - \"{authors}\"\n  - \"BIOINF535 group project, 2026 Fall\"\n"
             f"date: \"{version}\"\n---\n\n{PAGE_BREAK}\n")

    out, section, sub = [], 0, 0
    for block in re.split(r"\n{2,}", body):
        stripped = block.strip()
        m_sec = re.match(r"^## (.+)$", stripped)
        if m_sec and "\n" not in stripped:
            name = m_sec.group(1)
            if name.lower().startswith("appendix"):
                out.append("# Appendix. " + title_case(name.split(":", 1)[1].strip()) if ":" in name else f"# {name}")
            else:
                section, sub = section + 1, 0
                out.append(f"# {section}. {name}")
            continue
        m_lead = re.match(r"^\*\*([^*]+?\.)\*\*\s*(.*)$", stripped, re.S)
        if m_lead and section:
            sub += 1
            out.append(f"## {section}.{sub} {title_case(m_lead.group(1))}")
            rest = m_lead.group(2).strip()
            if rest:
                # pandoc needs a blank line between a paragraph and a list that follows it
                rest = re.sub(r"^((?!- ).+)\n- ", r"\1\n\n- ", rest, count=1, flags=re.M)
                out.append(rest)
            continue
        m_h3 = re.match(r"^### (.+)$", stripped)
        if m_h3 and "\n" not in stripped:
            out.append(f"## {m_h3.group(1)}")
            continue
        out.append(block.strip("\n"))
    return front + "\n\n".join(out) + "\n"


# ---------- reference document (styles) ----------

def _rpr(size_pt, bold=False, italic=False, color=INK, font="Arial"):
    return (f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:eastAsia="{font}" w:cs="{font}"/>'
            + ("<w:b/><w:bCs/>" if bold else "") + ("<w:i/><w:iCs/>" if italic else "")
            + f'<w:color w:val="{color}"/><w:sz w:val="{int(size_pt * 2)}"/><w:szCs w:val="{int(size_pt * 2)}"/></w:rPr>')


def _pstyle(sid, name, ppr, rpr, based="Normal", nxt="BodyText", extra=""):
    return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>'
            + (f'<w:basedOn w:val="{based}"/>' if based else "") + f'<w:next w:val="{nxt}"/>{extra}'
            + f"<w:qFormat/><w:pPr>{ppr}</w:pPr>{rpr}</w:style>")


SPACING_BODY = '<w:spacing w:before="0" w:after="160" w:line="276" w:lineRule="auto"/>'
STYLES = {
    "Normal": _pstyle("Normal", "Normal", SPACING_BODY, _rpr(12), based=None, nxt="Normal"),
    "BodyText": _pstyle("BodyText", "Body Text", SPACING_BODY, _rpr(12)),
    "FirstParagraph": _pstyle("FirstParagraph", "First Paragraph", SPACING_BODY, _rpr(12), based="BodyText"),
    "Compact": _pstyle("Compact", "Compact", '<w:spacing w:before="0" w:after="60" w:line="276" w:lineRule="auto"/>',
                       _rpr(12), based="BodyText"),
    "Title": _pstyle("Title", "Title", '<w:spacing w:before="1440" w:after="360" w:line="276" w:lineRule="auto"/>',
                     _rpr(14, bold=True), nxt="Author"),
    "Author": _pstyle("Author", "Author", '<w:spacing w:before="0" w:after="160" w:line="276" w:lineRule="auto"/>',
                      _rpr(12), nxt="Author"),
    "Date": _pstyle("Date", "Date", '<w:spacing w:before="0" w:after="160" w:line="276" w:lineRule="auto"/>',
                    _rpr(12)),
    "Heading1": _pstyle("Heading1", "heading 1",
                        '<w:keepNext/><w:keepLines/><w:spacing w:before="360" w:after="160"/><w:outlineLvl w:val="0"/>',
                        _rpr(14, bold=True)),
    "Heading2": _pstyle("Heading2", "heading 2",
                        '<w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="1"/>',
                        _rpr(12, bold=True)),
    "Heading3": _pstyle("Heading3", "heading 3",
                        '<w:keepNext/><w:keepLines/><w:spacing w:before="200" w:after="100"/><w:outlineLvl w:val="2"/>',
                        _rpr(12, bold=True, italic=True)),
    "SourceCode": _pstyle("SourceCode", "Source Code",
                          '<w:wordWrap/><w:shd w:val="clear" w:color="auto" w:fill="F3F3F3"/>'
                          '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>',
                          _rpr(9, font="Courier New", color="222222"), nxt="SourceCode"),
}
CHAR_STYLES = {
    "Hyperlink": ('<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>'
                  '<w:basedOn w:val="BodyTextChar"/><w:rPr>'
                  f'<w:color w:val="{LINK}"/><w:u w:val="single"/></w:rPr></w:style>'),
    "VerbatimChar": ('<w:style w:type="character" w:customStyle="1" w:styleId="VerbatimChar">'
                     '<w:name w:val="Verbatim Char"/><w:basedOn w:val="BodyTextChar"/><w:rPr>'
                     '<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/>'
                     '<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>'),
}
TABLE_STYLE = ('<w:style w:type="table" w:default="1" w:styleId="Table"><w:name w:val="Table"/>'
               '<w:basedOn w:val="TableNormal"/><w:pPr><w:spacing w:before="40" w:after="40" w:line="240" '
               'w:lineRule="auto"/></w:pPr>' + _rpr(10.5) +
               '<w:tblPr><w:tblBorders>'
               '<w:top w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:left w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:right w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
               '</w:tblBorders><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="100" w:type="dxa"/>'
               '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>'
               '<w:tblStylePr w:type="firstRow"><w:rPr><w:b/><w:bCs/></w:rPr>'
               '<w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="EFEFEF"/></w:tcPr></w:tblStylePr></w:style>')
SECT_PR = ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
           '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
           '</w:sectPr>')


def make_reference(path):
    default = os.path.join(os.path.dirname(path), "default.docx")
    with open(default, "wb") as f:
        f.write(subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"],
                               check=True, capture_output=True).stdout)
    zin = zipfile.ZipFile(default)
    styles = zin.read("word/styles.xml").decode("utf8")
    styles = re.sub(r"<w:docDefaults>.*?</w:docDefaults>",
                    "<w:docDefaults><w:rPrDefault>" + _rpr(12) + "</w:rPrDefault><w:pPrDefault><w:pPr>"
                    + SPACING_BODY + "</w:pPr></w:pPrDefault></w:docDefaults>", styles, flags=re.S)
    for sid, xml in {**STYLES, **CHAR_STYLES, "Table": TABLE_STYLE}.items():
        pat = re.compile(rf'<w:style [^>]*w:styleId="{sid}"[^>]*>.*?</w:style>', re.S)
        styles = pat.sub(lambda _: xml, styles, count=1) if pat.search(styles) else styles.replace("</w:styles>", xml + "</w:styles>")
    document = zin.read("word/document.xml").decode("utf8")
    if "<w:sectPr" not in document:
        document = document.replace("</w:body>", SECT_PR + "</w:body>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/styles.xml":
                data = styles.encode("utf8")
            elif item.filename == "word/document.xml":
                data = document.encode("utf8")
            zout.writestr(item, data)


# ---------- post-processing for Google Docs ----------

TEXT_WIDTH = 9360  # 6.5 in in twentieths of a point


BULLETS = ("\u25cf", "\u25cb", "\u25a0")  # Google Docs' default bullets: filled circle, circle, square


def fix_bullets(xml):
    """pandoc's default bullet glyph is a space; use visible bullets in Arial."""
    def lvl(m):
        block = m.group(0)
        if 'w:val="bullet"' not in block:
            return block
        char = BULLETS[int(m.group(1)) % 3]
        block = re.sub(r'<w:lvlText w:val="[^"]*"\s*/>', f'<w:lvlText w:val="{char}"/>', block)
        if "<w:rPr>" not in block:
            block = block.replace("</w:lvl>", '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/></w:rPr></w:lvl>')
        return block
    return re.sub(r'<w:lvl w:ilvl="(\d+)".*?</w:lvl>', lvl, xml, flags=re.S)


def fix_tables(docx_path):
    """Fixed table widths in DXA (Google Docs mishandles percentage widths) and visible bullets."""
    tmp = docx_path + ".tmp"
    with zipfile.ZipFile(docx_path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename.endswith("/"):
                continue  # no folder entries
            data = zin.read(item.filename)
            if item.filename == "word/numbering.xml":
                data = fix_bullets(data.decode("utf8")).encode("utf8")
            if item.filename == "word/document.xml":
                xml = data.decode("utf8")

                def one_table(m):
                    t = m.group(0)
                    cols = re.findall(r'<w:gridCol w:w="(\d+)"\s*/>', t)
                    if not cols:
                        return t
                    # width by content: longest cell text per column, clamped so no column is starved
                    longest = [8] * len(cols)
                    for r in re.findall(r"<w:tr[ >].*?</w:tr>", t, flags=re.S):
                        for i, c in enumerate(re.findall(r"<w:tc>.*?</w:tc>", r, flags=re.S)[:len(cols)]):
                            longest[i] = max(longest[i], len("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", c))))
                    weights = [min(max(n, 8), 34) for n in longest]
                    total = sum(weights)
                    widths = [max(700, round(w * TEXT_WIDTH / total)) for w in weights]
                    widths[-1] += TEXT_WIDTH - sum(widths)
                    t = re.sub(r"<w:tblW [^>]*/>", f'<w:tblW w:w="{TEXT_WIDTH}" w:type="dxa"/>', t, count=1)
                    it = iter(widths)
                    t = re.sub(r'<w:gridCol w:w="\d+"\s*/>', lambda _: f'<w:gridCol w:w="{next(it)}"/>', t)
                    # cell widths, row by row
                    def row(rm):
                        it2 = iter(widths)
                        return re.sub(r"<w:tcW [^>]*/>", lambda _: f'<w:tcW w:w="{next(it2, widths[-1])}" w:type="dxa"/>',
                                      rm.group(0))
                    return re.sub(r"<w:tr[ >].*?</w:tr>", row, t, flags=re.S)
                xml = re.sub(r"<w:tbl>.*?</w:tbl>", one_table, xml, flags=re.S)
                data = xml.encode("utf8")
            zout.writestr(item, data)
    os.replace(tmp, docx_path)


def main():
    if not shutil.which("pandoc"):
        sys.exit("pandoc not found; install it from https://pandoc.org")
    md = open(SRC, encoding="utf8").read()
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "spec.md")
        with open(src, "w", encoding="utf8") as f:
            f.write(restructure(md))
        ref = os.path.join(tmp, "reference.docx")
        make_reference(ref)
        subprocess.run(["pandoc", src, "-f", "markdown+pipe_tables+raw_attribute+autolink_bare_uris", "-t", "docx",
                        "--reference-doc", ref, "--no-highlight", "-o", DST], check=True)
    fix_tables(DST)
    print(f"Wrote {os.path.relpath(DST, ROOT)}")


if __name__ == "__main__":
    main()
