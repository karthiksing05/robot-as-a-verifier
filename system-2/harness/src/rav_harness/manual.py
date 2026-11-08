"""A product's manual, for the model to read a page at a time or search. Plain text, or a PDF through pdftotext."""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

PAGE_LINES = 60


class Manual:
    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path)
        self.pages = self._pages()

    def _pages(self) -> list[str]:
        if self.path.suffix.lower() == ".pdf":
            if not shutil.which("pdftotext"):
                raise RuntimeError("reading a PDF manual needs pdftotext (poppler)")
            text = subprocess.run(["pdftotext", "-layout", str(self.path), "-"], capture_output=True, text=True, check=True).stdout
            pages = text.split("\f")
        else:
            lines = self.path.read_text().splitlines()
            pages = ["\n".join(lines[i:i + PAGE_LINES]) for i in range(0, len(lines), PAGE_LINES)]
        return [re.sub(r"[ \t]{3,}", "   ", p).strip() for p in pages if p.strip()]

    def read(self, page: int | None = None, query: str | None = None) -> dict:
        if query:
            words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2] or [query.lower()]
            hits = []
            for n, text in enumerate(self.pages, 1):
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    score = sum(w in line.lower() for w in words)
                    if score:
                        hits.append((score, n, " ".join(s.strip() for s in lines[max(0, i - 1):i + 2])))
            hits.sort(key=lambda h: (-h[0], h[1]))
            return {"query": query, "pages": len(self.pages), "hits": [{"page": n, "text": t} for _, n, t in hits[:8]]}
        n = page or 1
        if not 1 <= n <= len(self.pages):
            raise ValueError(f"page {n} doesn't exist: this manual has {len(self.pages)} pages")
        return {"page": n, "pages": len(self.pages), "text": self.pages[n - 1]}
