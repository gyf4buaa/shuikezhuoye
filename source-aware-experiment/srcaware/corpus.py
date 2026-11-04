"""Read-only access to a pinned, real open-source game corpus.

The audit runs against a corpus that is *not* vendored into this repository.
`scripts/fetch_corpus.py` downloads the pinned release tarball; this module
enforces that retrieval may only read from a small evidence whitelist.

Safety properties that the tests rely on:

* the string table is read only from ``src/lang/english.txt``;
* every other language file is refused even if a caller constructs a path;
* paths escaping the corpus root are refused;
* evidence is limited to code/metadata suffixes; documentation, tests and
  bundled third-party libraries are excluded.

The corpus is GPL-2.0 (OpenTTD).  Only short quotations are written into the
audit report and experiment prompts; the corpus itself is never redistributed
by this repository.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


class CorpusError(Exception):
    """The corpus is missing, malformed or inaccessible."""


class LeakageError(CorpusError):
    """A caller tried to read a target-language or gold file."""


CODE_SUFFIXES = {".cpp", ".c", ".h", ".hpp"}
METADATA_GLOBS = ("src/table/settings/*.ini", "media/baseset/*.obg", "media/baseset/*.obs")

# Directories whose contents are never evidence.  ``src/lang`` holds the source
# table plus every translated table; only ``english.txt`` is read, through a
# dedicated parser that cannot be pointed at another language.
DENY_PREFIXES = (
    "src/lang/",
    "src/3rdparty/",
    ".git/",
    "docs/",
    "regression/",
)
# Extra defence in depth: any path matching one of these is refused, even if
# an allowlist rule would otherwise admit it.
DENY_PATTERNS = (
    re.compile(r"(?i)(?:^|/)(?:gold|reference|expected)(?:_|/|\.|$)"),
    re.compile(r"(?i)(?:^|/).*(?:translation|translated).*(?:gold|reference|expected).*"),
    re.compile(r"(?i)\.(?:po|mo|xliff|xlf)$"),
)


@dataclass(frozen=True)
class StringEntry:
    """One row of the source-language string table."""

    key: str
    text: str
    file: str
    line: int
    string_id: int


@dataclass(frozen=True)
class CorpusSpec:
    project: str
    version: str
    commit: str
    license: str
    repo_url: str
    archive_sha256: Optional[str] = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OpenTTDCorpus:
    """A pinned OpenTTD checkout with allowlisted evidence access."""

    REQUIRED = (
        "src/lang/english.txt",
        "src/table/cargo_const.h",
        "src/settings.cpp",
        "COPYING.md",
    )

    def __init__(self, root: Path | str, spec: Optional[CorpusSpec] = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.spec = spec
        if not self.root.is_dir():
            raise CorpusError(f"corpus directory does not exist: {self.root}")
        missing = [rel for rel in self.REQUIRED if not (self.root / rel).is_file()]
        if missing:
            raise CorpusError(
                "corpus is missing required files: " + ", ".join(missing)
            )
        self._entries: Optional[List[StringEntry]] = None
        self._entry_by_key: Optional[Dict[str, StringEntry]] = None
        self._id_by_key: Optional[Dict[str, int]] = None
        self._key_by_id: Optional[Dict[int, str]] = None
        self._files: Optional[List[str]] = None

    # ------------------------------------------------------------------ paths
    def resolve(self, relative: str) -> Path:
        """Resolve a corpus-relative POSIX path, refusing escapes."""
        rel = self.normalise_relative(relative)
        pure = PurePosixPath(rel)
        candidate = (self.root / Path(*pure.parts)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:  # pragma: no cover - resolve() already checked
            raise LeakageError(f"path escapes corpus root: {relative!r}") from exc
        return candidate

    @staticmethod
    def normalise_relative(relative: str) -> str:
        raw = str(relative).replace("\\", "/")
        if raw.startswith("/"):
            raise LeakageError(f"absolute path is not corpus-relative: {relative!r}")
        pure = PurePosixPath(raw)
        if pure.is_absolute() or ".." in pure.parts:
            raise LeakageError(f"path escapes corpus root: {relative!r}")
        return str(pure)

    def _denied(self, rel: str) -> Optional[str]:
        for prefix in DENY_PREFIXES:
            if rel == prefix.rstrip("/") or rel.startswith(prefix):
                return f"directory is excluded: {prefix}"
        for pattern in DENY_PATTERNS:
            if pattern.search(rel):
                return "path matches a target-language/gold denylist"
        return None

    def is_evidence_path(self, relative: str) -> bool:
        try:
            rel = self.normalise_relative(relative)
        except LeakageError:
            return False
        if self._denied(rel):
            return False
        pure = PurePosixPath(rel)
        if pure.suffix in CODE_SUFFIXES:
            return rel.startswith("src/")
        for glob in METADATA_GLOBS:
            prefix, _, pattern = glob.rpartition("/")
            if rel.startswith(prefix + "/") and pure.match(pattern):
                return True
        return False

    def read_evidence(self, relative: str) -> str:
        """Read one allowlisted evidence file as UTF-8 text."""
        rel = self.normalise_relative(relative)
        denied = self._denied(rel)
        if denied:
            raise LeakageError(f"refusing to read {rel}: {denied}")
        if not self.is_evidence_path(rel):
            raise LeakageError(
                f"refusing to read {rel}: not in the evidence allowlist"
            )
        path = self.resolve(rel)
        if not path.is_file():
            raise CorpusError(f"evidence file does not exist: {rel}")
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise CorpusError(f"cannot read {rel}: {exc}") from exc

    # ------------------------------------------------------------------- table
    def read_english_table(self) -> List[StringEntry]:
        """Parse ``src/lang/english.txt``; never reads another language.

        OpenTTD assigns StringIDs sequentially inside sections introduced by
        ``##id 0x....``.  Indices are required by the arithmetic-range locator,
        which verifies that a token plus an integer offset maps to the expected
        next key.
        """
        if self._entries is not None:
            return self._entries
        rel = "src/lang/english.txt"
        path = self.resolve(rel)
        if not path.is_file():
            raise CorpusError(f"missing source string table: {rel}")
        entries: List[StringEntry] = []
        base = 0
        offset = 0
        header_ok = False
        line_re = re.compile(r"^(STR_[A-Z0-9_]+)\s*:(.*)$")
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, 1):
                line = raw.rstrip("\n")
                if line.startswith("##name"):
                    header_ok = "English" in line
                id_match = re.match(r"##id\s+(0x[0-9A-Fa-f]+)", line)
                if id_match:
                    base = int(id_match.group(1), 16)
                    offset = 0
                    continue
                if line.startswith("##") or line.startswith("#") or not line.strip():
                    continue
                match = line_re.match(line)
                if not match:
                    raise CorpusError(
                        f"unexpected non-comment line {rel}:{line_no}: {line[:80]!r}"
                    )
                entries.append(
                    StringEntry(
                        key=match.group(1),
                        text=match.group(2),
                        file=rel,
                        line=line_no,
                        string_id=base + offset,
                    )
                )
                offset += 1
        if not header_ok:
            raise CorpusError(f"{rel} does not declare an English source table")
        if len(entries) < 20:
            raise CorpusError(f"{rel} parsed too few strings: {len(entries)}")
        keys = [entry.key for entry in entries]
        if len(set(keys)) != len(keys):
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            raise CorpusError(f"duplicate keys in {rel}: {duplicates[:5]}")
        self._entries = entries
        self._entry_by_key = {entry.key: entry for entry in entries}
        self._id_by_key = {entry.key: entry.string_id for entry in entries}
        self._key_by_id = {entry.string_id: entry.key for entry in entries}
        return entries

    @property
    def entries(self) -> List[StringEntry]:
        return self.read_english_table()

    @property
    def entry_by_key(self) -> Dict[str, StringEntry]:
        self.read_english_table()
        assert self._entry_by_key is not None
        return self._entry_by_key

    @property
    def id_by_key(self) -> Dict[str, int]:
        self.read_english_table()
        assert self._id_by_key is not None
        return self._id_by_key

    @property
    def key_by_id(self) -> Dict[int, str]:
        self.read_english_table()
        assert self._key_by_id is not None
        return self._key_by_id

    # ------------------------------------------------------------------- files
    def evidence_files(self) -> List[str]:
        """Sorted corpus-relative evidence paths."""
        if self._files is not None:
            return self._files
        files: List[str] = []
        src = self.root / "src"
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            if self.is_evidence_path(rel):
                files.append(rel)
        baseset = self.root / "media" / "baseset"
        if baseset.is_dir():
            for path in baseset.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(self.root).as_posix()
                    if self.is_evidence_path(rel):
                        files.append(rel)
        files.sort()
        self._files = files
        return files

    # ---------------------------------------------------------------- manifest
    @staticmethod
    def load_spec(path: Path | str) -> CorpusSpec:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return CorpusSpec(
            project=data["project"],
            version=data["version"],
            commit=data["commit"],
            license=data["license"],
            repo_url=data["repo_url"],
            archive_sha256=data.get("archive_sha256"),
        )

    def verify_spec(self) -> None:
        if self.spec is None:
            return
        if self.spec.project.lower() != "openttd":
            raise CorpusError(f"unsupported corpus project: {self.spec.project}")
        copying = (self.root / "COPYING.md").read_text(encoding="utf-8", errors="replace")
        if "GNU General Public License" not in copying:
            raise CorpusError("COPYING.md does not look like the GPL text")
        if self.spec.license.split()[0].lower() not in copying.lower():
            raise CorpusError(
                f"license mismatch: spec says {self.spec.license!r}"
            )
