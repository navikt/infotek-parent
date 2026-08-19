#!/usr/bin/env python3
"""
Render en Markdown-fil til en enkel, lesbar HTML-fil uten tredjepartsavhengigheter.

Verktøyet er laget for etterlevelsesrapporter og lignende dokumenter der Markdown
er kilden til sannhet, mens HTML er et generert visningsformat for ikke-tekniske lesere.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


def escape_inline(text: str) -> str:
    text = html.escape(text, quote=False)

    def code_replace(match: re.Match[str]) -> str:
        return f"<code>{match.group(1)}</code>"

    text = re.sub(r"`([^`]+)`", code_replace, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def infer_title(markdown_text: str, fallback: str) -> str:
    for line in markdown_text.splitlines():
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return fallback


def is_raw_html(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("<") and not stripped.startswith("<!--")


def render_paragraph(lines: list[str]) -> str:
    text = " ".join(part.strip() for part in lines if part.strip())
    if not text:
        return ""
    return f"<p>{escape_inline(text)}</p>"


def render_blockquote(lines: list[str]) -> str:
    content = " ".join(re.sub(r"^\s*>\s?", "", line).strip() for line in lines)
    return f"<blockquote><p>{escape_inline(content)}</p></blockquote>"


def render_list(items: list[tuple[str, str]], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    body = "".join(f"<li>{escape_inline(text)}</li>" for _, text in items)
    return f"<{tag}>{body}</{tag}>"


def parse_table(lines: list[str], start: int) -> tuple[str, int]:
    header = [part.strip() for part in lines[start].strip().strip("|").split("|")]
    index = start + 2
    rows: list[list[str]] = []

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or not stripped.startswith("|") or "|" not in stripped:
            break
        rows.append([part.strip() for part in stripped.strip("|").split("|")])
        index += 1

    thead = "".join(f"<th>{escape_inline(cell)}</th>" for cell in header)
    tbody_rows = []
    for row in rows:
        cells = "".join(f"<td>{escape_inline(cell)}</td>" for cell in row)
        tbody_rows.append(f"<tr>{cells}</tr>")

    table = (
        '<table class="table">'
        f"<thead><tr>{thead}</tr></thead>"
        f"<tbody>{''.join(tbody_rows)}</tbody>"
        "</table>"
    )
    return table, index


def render_markdown(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    blockquote: list[str] = []
    list_items: list[tuple[str, str]] = []
    list_ordered = False
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    i = 0

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            rendered = render_paragraph(paragraph)
            if rendered:
                output.append(rendered)
            paragraph = []

    def flush_blockquote() -> None:
        nonlocal blockquote
        if blockquote:
            output.append(render_blockquote(blockquote))
            blockquote = []

    def flush_list() -> None:
        nonlocal list_items, list_ordered
        if list_items:
            output.append(render_list(list_items, list_ordered))
            list_items = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if in_code:
            if stripped.startswith("```"):
                escaped = html.escape("\n".join(code_lines), quote=False)
                cls = f' class="language-{html.escape(code_lang, quote=True)}"' if code_lang else ""
                output.append(f"<pre><code{cls}>{escaped}</code></pre>")
                in_code = False
                code_lang = ""
                code_lines = []
            else:
                code_lines.append(line)
            i += 1
            continue

        if not stripped:
            flush_paragraph()
            flush_blockquote()
            flush_list()
            i += 1
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            flush_blockquote()
            flush_list()
            in_code = True
            code_lang = stripped[3:].strip()
            code_lines = []
            i += 1
            continue

        if is_raw_html(line):
            flush_paragraph()
            flush_blockquote()
            flush_list()
            output.append(line)
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            flush_blockquote()
            flush_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{escape_inline(heading.group(2).strip())}</h{level}>")
            i += 1
            continue

        if stripped == "---":
            flush_paragraph()
            flush_blockquote()
            flush_list()
            output.append("<hr/>")
            i += 1
            continue

        if re.match(r"^\|.*\|$", stripped) and i + 1 < len(lines) and re.match(r"^\|?[\s:-]+\|[\s|:-]*\|?$", lines[i + 1].strip()):
            flush_paragraph()
            flush_blockquote()
            flush_list()
            table_html, next_index = parse_table(lines, i)
            output.append(table_html)
            i = next_index
            continue

        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            flush_paragraph()
            flush_list()
            blockquote.append(quote.group(1))
            i += 1
            continue

        unordered = re.match(r"^\s*[-*+]\s+(.+)$", line)
        ordered = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            flush_blockquote()
            current_ordered = bool(ordered)
            if list_items and list_ordered != current_ordered:
                flush_list()
            list_ordered = current_ordered
            list_items.append(("ol" if current_ordered else "ul", (ordered or unordered).group(1)))
            i += 1
            continue

        flush_blockquote()
        flush_list()
        paragraph.append(line)
        i += 1

    flush_paragraph()
    flush_blockquote()
    flush_list()

    return "\n".join(output)


def build_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="no">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
      color: #1f2937;
      background: #f7f7f8;
      margin: 0;
      padding: 32px 20px 48px;
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      background: #fff;
      padding: 32px;
      border-radius: 16px;
      box-shadow: 0 1px 6px rgba(0, 0, 0, 0.08);
    }}
    h1, h2, h3, h4, h5, h6 {{
      line-height: 1.2;
      margin: 1.4em 0 0.6em;
    }}
    h1 {{ margin-top: 0; }}
    p, ul, ol, blockquote, table, pre {{
      margin: 0 0 1rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      border: 1px solid #d1d5db;
      padding: 0.55rem 0.7rem;
      vertical-align: top;
      text-align: left;
    }}
    th {{
      background: #f3f4f6;
    }}
    pre {{
      background: #111827;
      color: #f9fafb;
      padding: 1rem;
      border-radius: 12px;
      overflow-x: auto;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.95em;
    }}
    p code, li code, td code, th code {{
      background: #eef2ff;
      padding: 0.1rem 0.3rem;
      border-radius: 4px;
    }}
    blockquote {{
      border-left: 4px solid #cbd5e1;
      padding: 0.25rem 0 0.25rem 1rem;
      color: #475569;
    }}
    details {{
      margin: 1rem 0;
      border: 1px solid #d1d5db;
      border-radius: 12px;
      padding: 0.75rem 1rem;
      background: #fafafa;
    }}
    summary {{
      cursor: pointer;
      font-weight: 600;
    }}
    hr {{
      border: 0;
      border-top: 1px solid #e5e7eb;
      margin: 1.5rem 0;
    }}
    a {{
      color: #0f62fe;
    }}
  </style>
</head>
<body>
  <main>
{body}
  </main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Markdown til HTML")
    parser.add_argument("--input", required=True, help="Markdown-fil")
    parser.add_argument("--output", required=True, help="HTML-fil")
    parser.add_argument("--title", help="Tittel i HTML-dokumentet")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    markdown_text = input_path.read_text(encoding="utf-8")
    title = args.title or infer_title(markdown_text, input_path.stem)
    body = render_markdown(markdown_text)
    html_doc = build_html(title, body)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
