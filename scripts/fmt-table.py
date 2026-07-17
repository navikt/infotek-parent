#!/usr/bin/env python3
"""Formatter for make git-status — leser tab-separert input og skriver Unicode-justerte kolonner."""
import sys
import unicodedata


def vlen(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


rows = [line.rstrip("\n").split("\t") for line in sys.stdin if line.strip()]
if not rows:
    sys.exit(0)

cols = len(rows[0])
widths = [max(vlen(r[i]) for r in rows) + 2 for i in range(cols - 1)]

for row in rows:
    parts = [row[i] + " " * (widths[i] - vlen(row[i])) for i in range(cols - 1)]
    print("  " + "".join(parts) + row[-1])
