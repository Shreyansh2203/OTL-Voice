"""Validate relative links and heading anchors across the repository's Markdown.

The docs here are extensive (README plus a dozen files under docs/) and every claim they
make is load-bearing, so a link that rots is a silent defect. The other repositories in
this portfolio already assert their own links; this closes the same gap here.
"""

import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_ROOTS = (REPO_ROOT, REPO_ROOT / "docs", REPO_ROOT / "frontend")

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*$")


def _markdown_files() -> list[Path]:
    seen: dict[Path, None] = {}
    for root in DOC_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            if any(
                part
                in {
                    "node_modules",
                    ".venv",
                    ".git",
                    "test-results",
                    "playwright-report",
                }
                for part in path.parts
            ):
                continue
            seen.setdefault(path, None)
    return sorted(seen)


def _slugify(heading: str) -> str:
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"[\s]+", "-", slug)


def _anchors_in(path: Path) -> set[str]:
    anchors: set[str] = set()
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING.match(line)
        if match:
            anchors.add(_slugify(match.group(1)))
    return anchors


class TestDocumentationLinks(unittest.TestCase):
    def test_the_suite_actually_finds_the_documents(self) -> None:
        # Without this, a bad glob would make every assertion below pass on zero files.
        self.assertGreaterEqual(len(_markdown_files()), 5)

    def test_relative_links_resolve_to_a_file_that_exists(self) -> None:
        broken: list[str] = []
        for source in _markdown_files():
            text = source.read_text(encoding="utf-8")
            for target in MARKDOWN_LINK.findall(text):
                parsed = urlparse(target)
                if parsed.scheme or target.startswith(("#", "mailto:")):
                    continue
                path_part = unquote(parsed.path)
                if not path_part:
                    continue
                resolved = (source.parent / path_part).resolve()
                if not resolved.exists():
                    broken.append(f"{source.relative_to(REPO_ROOT)} -> {target}")
        self.assertEqual(broken, [], "broken relative links:\n" + "\n".join(broken))

    def test_fragment_links_point_at_a_heading_that_exists(self) -> None:
        broken: list[str] = []
        for source in _markdown_files():
            for target in MARKDOWN_LINK.findall(source.read_text(encoding="utf-8")):
                parsed = urlparse(target)
                if parsed.scheme or not parsed.fragment:
                    continue
                if parsed.path:
                    destination = (source.parent / unquote(parsed.path)).resolve()
                else:
                    destination = source
                if not destination.exists() or destination.suffix != ".md":
                    continue
                anchor = unquote(parsed.fragment).lower()
                if anchor not in _anchors_in(destination):
                    rel = source.relative_to(REPO_ROOT)
                    broken.append(f"{rel} -> {target}")
        self.assertEqual(broken, [], "anchors that do not exist:\n" + "\n".join(broken))


if __name__ == "__main__":
    unittest.main()
