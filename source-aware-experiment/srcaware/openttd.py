"""A practical source locator for one real OpenTTD checkout.

The locator is deliberately narrow: it understands the conventions that this
engine actually uses (StringID tokens, token-pasting cargo macros, settings
dropdown ranges and integer-offset ranges) and reports everything else as
unresolved rather than pretending to understand it.

Every piece of evidence carries a real ``path:line`` from the pinned corpus.
No per-key answer is hard-coded: candidate ranges are accepted only when the
string table proves that the StringIDs are contiguous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .corpus import CorpusError, LeakageError, OpenTTDCorpus, StringEntry

TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])STR_[A-Z0-9_]+")
PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
CONTROL_TOKENS = {
    "BLACK", "WHITE", "RED", "GREEN", "BLUE", "YELLOW", "ORANGE", "GOLD",
    "SILVER", "LTBLUE", "TINY_FONT", "BIG_FONT", "NBSP", "P", "SPACE", "",
}
DATA_TOKENS = {
    "STRING", "STRING1", "STRING2", "RAW_STRING", "NUM", "COMMA",
    "CURRENCY_LONG", "TOWN", "COMPANY", "COMPANY_NUM", "STATION",
    "VEHICLE", "INDUSTRY", "DATE_SHORT", "DATE_LONG", "HEIGHT",
    "PRESIDENT_NAME", "CURRENCY", "CURRENCY_SHORT", "VELOCITY",
    "POWER", "WEIGHT", "VOLUME", "FORCE", "DURATION", "SIGNED",
}


def placeholder_tokens(text: str) -> List[Dict[str, str]]:
    """Classify ``{...}`` tokens as style codes or translation data."""
    tokens: List[Dict[str, str]] = []
    for match in PLACEHOLDER_RE.finditer(text):
        token = match.group(1)
        if token in DATA_TOKENS:
            kind = "data"
        elif token in CONTROL_TOKENS:
            kind = "style"
        else:
            # NewGRF string substitutions and rare control words are not
            # translated, but they are still format syntax.
            kind = "style"
        tokens.append({"token": token, "kind": kind})
    return tokens


def data_placeholders(text: str) -> List[str]:
    return [item["token"] for item in placeholder_tokens(text) if item["kind"] == "data"]


@dataclass(frozen=True)
class Ref:
    """One source location that mentions a key."""

    key: str
    path: str
    line: int
    column: int
    kind: str
    snippet: str
    scope: Optional[str] = None
    call: Optional[str] = None
    args: Tuple[str, ...] = ()
    relation: Optional[str] = None

    @property
    def evidence_id(self) -> str:
        return f"{self.path}:{self.line}:{self.key}"

    def as_dict(self) -> Dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "key": self.key,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
            "scope": self.scope,
            "call": self.call,
            "args": list(self.args),
            "relation": self.relation,
            "snippet": self.snippet,
        }


@dataclass
class Bundle:
    key: str
    text: str
    status: str
    confidence: str
    refs: List[Ref] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    placeholders: List[Dict[str, str]] = field(default_factory=list)

    @property
    def evidence_ids(self) -> List[str]:
        seen: List[str] = []
        for ref in self.refs:
            if ref.evidence_id not in seen:
                seen.append(ref.evidence_id)
        return seen

    def as_dict(self) -> Dict[str, object]:
        return {
            "key": self.key,
            "text": self.text,
            "status": self.status,
            "confidence": self.confidence,
            "notes": list(self.notes),
            "placeholders": list(self.placeholders),
            "evidence_ids": self.evidence_ids,
            "refs": [ref.as_dict() for ref in self.refs],
        }


def build_snippet(lines: Sequence[str], line_index: int, radius: int = 2) -> str:
    start = max(0, line_index - radius)
    end = min(len(lines), line_index + radius + 1)
    rendered: List[str] = []
    for idx in range(start, end):
        marker = ">" if idx == line_index else " "
        text = lines[idx].rstrip()
        if len(text) > 240:
            text = text[:237] + "..."
        rendered.append(f"{marker} {idx + 1:5d} | {text}")
    return "\n".join(rendered)


FUNC_RE = re.compile(
    r"^(?!(?:if|for|foreach|while|switch|catch|else|do|case)\b)"
    r"[A-Za-z_][\w:<>,*&\s]*\b([A-Za-z_][A-Za-z0-9_:<>]*)\s*\([^;{}]*\)\s*(?:const)?\s*$"
)
CONTROL_WORDS = ("if", "for", "foreach", "while", "switch", "catch", "else", "do", "case")


def enclosing_scope(lines: Sequence[str], line_index: int) -> Optional[str]:
    """Best-effort enclosing declaration; explicitly heuristic."""
    for idx in range(line_index, max(-1, line_index - 200), -1):
        text = lines[idx].rstrip()
        if not text or text.lstrip().startswith(("//", "/*", "*")):
            continue
        match = FUNC_RE.match(text.strip())
        if not match:
            continue
        if match.group(1) in CONTROL_WORDS:
            continue
        # Accept only when a body follows within a few lines.
        for follow in range(idx + 1, min(len(lines), idx + 4)):
            if lines[follow].lstrip().startswith("{"):
                return text.strip()[:200]
        return text.strip()[:200]
    return None


def _split_args(raw: str) -> Tuple[str, ...]:
    """Split a C/C++ argument list on top-level commas."""
    args: List[str] = []
    current: List[str] = []
    depth = 0
    quote: Optional[str] = None
    escape = False
    for char in raw:
        if quote:
            current.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
        elif char in "([{":
            depth += 1
            current.append(char)
        elif char in ")]}":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        args.append("".join(current).strip())
    return tuple(args)


def _call_context(
    lines: Sequence[str], line_index: int, column: int
) -> Tuple[Optional[str], Tuple[str, ...]]:
    """Extract the innermost call containing a reference, if it is on one line."""
    line = lines[line_index]
    prefix = line[:column]
    open_index = prefix.rfind("(")
    if open_index < 0:
        return None, ()
    callee_match = re.search(r"([A-Za-z_][A-Za-z0-9_:<>]*)\s*$", prefix[:open_index])
    callee = callee_match.group(1) if callee_match else None
    # Balance parentheses from the opening one to the end of the same line.
    depth = 0
    quote: Optional[str] = None
    escape = False
    end = None
    for offset in range(open_index, len(line)):
        char = line[offset]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                end = offset + 1
                break
    if end is None or end - 1 < column:
        # The parentheses closed before the key: this is not the call that
        # contains the reference (e.g. ``foo() ? STR_X : STR_Y``).
        return None, ()
    args = _split_args(line[open_index + 1:end - 1])
    return callee, args


def _classify_ref(path: str, line_text: str, column: int, callee: Optional[str]) -> str:
    if path == "src/newgrf/newgrf_stringmapping.cpp":
        # A TTDP compatibility table maps old numeric IDs to new StringIDs; it
        # proves the alias but is not the UI use site, so keep it out of the
        # first evidence slots when a real use exists.
        return "compat_mapping"
    if path.endswith((".obg", ".obs")):
        return "baseset_metadata"
    if path.endswith(".ini"):
        return "settings_field"
    if callee:
        return f"call:{callee}"
    stripped = line_text.strip()
    if stripped.startswith(("//", "/*", "*")):
        return "comment"
    if "{" in line_text and "}" not in line_text:
        return "initializer"
    return "reference"


class OpenTTDLocator:
    """Locate source evidence for OpenTTD StringIDs."""

    def __init__(self, corpus: OpenTTDCorpus) -> None:
        self.corpus = corpus
        self.entries = corpus.entries
        self.by_key = corpus.entry_by_key
        self.id_by_key = corpus.id_by_key
        self.key_by_id = corpus.key_by_id
        self._lines: Dict[str, List[str]] = {}
        self._refs: Dict[str, List[Ref]] = {}
        self._cargo: Dict[str, Tuple[Ref, Ref]] = {}
        self._settings: Dict[str, Dict[str, object]] = {}
        self._families: Dict[str, Dict[str, object]] = {}
        self._family_base_refs: Dict[str, List[Ref]] = {}
        self._vehicle_name_bases: List[Tuple[str, Ref]] = []
        self._index()
        self._parse_cargo()
        self._parse_settings()
        self._parse_arithmetic_families()
        self._parse_vehicle_name_ranges()

    # ------------------------------------------------------------------ index
    def lines(self, path: str) -> List[str]:
        cached = self._lines.get(path)
        if cached is None:
            cached = self.corpus.read_evidence(path).splitlines()
            self._lines[path] = cached
        return cached

    def _index(self) -> None:
        for path in self.corpus.evidence_files():
            lines = self.lines(path)
            for line_index, line in enumerate(lines):
                for match in TOKEN_RE.finditer(line):
                    key = match.group(0)
                    if key not in self.by_key:
                        continue
                    column = match.start()
                    callee, args = _call_context(lines, line_index, column)
                    kind = _classify_ref(path, line, column, callee)
                    ref = Ref(
                        key=key,
                        path=path,
                        line=line_index + 1,
                        column=column + 1,
                        kind=kind,
                        snippet=build_snippet(lines, line_index),
                        scope=enclosing_scope(lines, line_index),
                        call=callee,
                        args=args,
                    )
                    self._refs.setdefault(key, []).append(ref)
        for refs in self._refs.values():
            refs.sort(
                key=lambda item: (
                    item.kind == "compat_mapping",
                    item.path,
                    item.line,
                    item.column,
                )
            )

    def direct_refs(self, key: str) -> List[Ref]:
        return list(self._refs.get(key, []))

    # ------------------------------------------------------------------- cargo
    def _parse_cargo(self) -> None:
        path = "src/table/cargo_const.h"
        if path not in self.corpus.evidence_files():
            return
        lines = self.lines(path)
        macro_defs: Dict[str, Ref] = {}
        for line_index, line in enumerate(lines):
            match = re.match(
                r"\s*#define\s+(MK_STR_(?:CARGO_(?:PLURAL|SINGULAR)|QUANTITY|ABBREV))"
                r"\(\s*(\w+)\s*\)\s+(STR_[A-Z0-9_]+)\s*##\s*(\w+)",
                line,
            )
            if not match:
                continue
            family, parameter, prefix, suffix = match.groups()
            macro_defs[family] = Ref(
                key=prefix,
                path=path,
                line=line_index + 1,
                column=line.index("#define") + 1,
                kind="macro_definition",
                snippet=build_snippet(lines, line_index),
                scope="preprocessor",
                relation=(
                    f"{family}({parameter}) expands to {prefix}<{parameter}>; "
                    "the argument is pasted after the prefix"
                ),
            )
        if not macro_defs:
            return
        table_start = None
        for line_index, line in enumerate(lines):
            if "_default_cargo" in line and "CargoSpec" in line:
                table_start = line_index
                break
        if table_start is None:
            return
        for line_index in range(table_start, len(lines)):
            line = lines[line_index]
            if not line.lstrip().startswith("MK("):
                continue
            open_index = line.index("MK(") + 2
            # Gather the possibly multi-line initializer.
            joined = line
            cursor = line_index
            while joined.count("(") != joined.count(")") and cursor + 1 < len(lines):
                cursor += 1
                joined += "\n" + lines[cursor]
            args = _split_args(joined[open_index + 1:joined.rfind(")")])
            if len(args) < 13:
                continue
            plural, singular = args[10], args[11]
            for family, suffix in (
                ("MK_STR_CARGO_PLURAL", plural),
                ("MK_STR_CARGO_SINGULAR", singular),
                ("MK_STR_QUANTITY", plural),
                ("MK_STR_ABBREV", plural),
            ):
                key = f"{macro_defs[family].key}{suffix}"
                if key not in self.by_key:
                    continue
                macro_ref = macro_defs[family]
                row_ref = Ref(
                    key=key,
                    path=path,
                    line=line_index + 1,
                    column=line.index("MK(") + 1,
                    kind="cargo_table_row",
                    snippet=build_snippet(lines, line_index),
                    scope="_default_cargo[]",
                    call="MK",
                    args=args,
                    relation=(
                        f"row for cargo label {args[1]}; {family.split('_')[-1].lower()} "
                        f"name slot uses argument {suffix!r}"
                    ),
                )
                self._cargo[key] = (macro_ref, row_ref)

    # ---------------------------------------------------------------- settings
    def _parse_settings(self) -> None:
        rule_path = "src/settings.cpp"
        rule_line = None
        rule_text = ""
        if rule_path in self.corpus.evidence_files():
            for idx, line in enumerate(self.lines(rule_path), 1):
                if "str_val - min_val + value" in line:
                    rule_line = idx
                    rule_text = line.strip()
                    break
        if rule_line is None:
            return
        rule_ref = Ref(
            key="STR_NULL",
            path=rule_path,
            line=rule_line,
            column=1,
            kind="settings_rule",
            snippet=build_snippet(self.lines(rule_path), rule_line - 1),
            scope="GetSettingsValueString",
            relation=(
                "a dropdown value maps to StringID str_val - min_val + value"
            ),
        )
        sections: Dict[str, Dict[str, object]] = {}
        for path in self.corpus.evidence_files():
            if not path.startswith("src/table/settings/"):
                continue
            current: Optional[Dict[str, object]] = None
            lines = self.lines(path)
            for line_index, raw in enumerate(lines):
                line = raw.strip()
                header = re.match(r"^\[(SDT[A-Z0-9_]*)\]$", line)
                if header:
                    if current is not None:
                        self._register_setting(current, rule_ref)
                    current = {
                        "section": header.group(1),
                        "path": path,
                        "line": line_index + 1,
                        "fields": {},
                        "field_lines": {},
                    }
                    continue
                if current is None or not line or line.startswith((";", "#")):
                    continue
                field = re.match(r"^([A-Za-z_]+)\s*=\s*(.*)$", line)
                if not field:
                    continue
                name, value = field.group(1), field.group(2).strip()
                current["fields"][name] = value  # type: ignore[index]
                current["field_lines"][name] = line_index + 1  # type: ignore[index]
            if current is not None:
                self._register_setting(current, rule_ref)
        # ``_register_setting`` appends to self._settings as it goes.

    def _register_setting(self, section: Dict[str, object], rule_ref: Ref) -> None:
        fields: Dict[str, str] = section["fields"]  # type: ignore[assignment]
        field_lines: Dict[str, int] = section["field_lines"]  # type: ignore[assignment]
        strval = fields.get("strval", "").strip()
        if not strval.startswith("STR_") or strval not in self.by_key:
            return
        try:
            minimum = int(fields["min"])
            maximum = int(fields["max"])
        except (KeyError, ValueError):
            return
        span = maximum - minimum
        if span < 1 or span > 64:
            return
        if "GuiZeroIsSpecial" in fields.get("flags", ""):
            return
        base_id = self.id_by_key[strval]
        candidates: Dict[str, Dict[str, object]] = {}
        for value in range(minimum, maximum + 1):
            key = self.key_by_id.get(base_id + value - minimum)
            if key is None:
                return
            if not key.startswith("STR_"):
                return
            candidates[key] = {"value": value, "offset": value - minimum}
        path = str(section["path"])
        field_line = int(field_lines["strval"])
        ref = Ref(
            key=strval,
            path=path,
            line=field_line,
            column=1,
            kind="settings_dropdown_base",
            snippet=build_snippet(self.lines(path), field_line - 1),
            scope=str(section["section"]),
            relation=(
                f"{fields.get('var', '?')} dropdown: StringID = {strval} + "
                f"(value - {minimum}); values {minimum}..{maximum}"
            ),
        )
        for key, info in candidates.items():
            self._settings[key] = {
                "base": strval,
                "value": info["value"],
                "offset": info["offset"],
                "min": minimum,
                "max": maximum,
                "var": fields.get("var", "?"),
                "ini_ref": ref,
                "rule_ref": rule_ref,
            }

    # --------------------------------------------------------------- arithmetic
    ARITHMETIC_FAMILIES: Sequence[Tuple[str, str, int, str]] = (
        ("goal_buttons", "STR_GOAL_QUESTION_BUTTON_CANCEL", 18, "goal question buttons"),
        ("buy_captions", "STR_BUY_VEHICLE_TRAIN_ALL_CAPTION", 4, "vehicle purchase captions"),
        ("months", "STR_MONTH_JAN", 12, "month names"),
        ("days", "STR_DAY_NUMBER_1ST", 31, "day ordinals"),
        ("colours", "STR_COLOUR_DARK_BLUE", 16, "company colour names"),
        ("group_all", "STR_GROUP_ALL_TRAINS", 4, "all-vehicles group labels"),
        ("group_default", "STR_GROUP_DEFAULT_TRAINS", 4, "ungrouped vehicle labels"),
        ("smallmap_types", "STR_SMALLMAP_TYPE_CONTOURS", 7, "small map mode labels"),
        ("performance_details", "STR_PERFORMANCE_DETAIL_VEHICLES", 7, "performance detail labels"),
        ("finance_sections", "STR_FINANCES_SECTION_CONSTRUCTION", 12, "finance section labels"),
        ("livery_schemes", "STR_LIVERY_DEFAULT", 20, "livery scheme names"),
        ("vehicle_waiting_news", "STR_NEWS_TRAIN_IS_WAITING", 4, "vehicle waiting news"),
    )

    def _parse_arithmetic_families(self) -> None:
        arith_re = re.compile(
            r"\b(STR_[A-Z0-9_]+)\s*\+\s*([A-Za-z_][\w\.\->\[\]]*)"
        )
        arith_refs: Dict[str, List[Tuple[Ref, str]]] = {}
        for path in self.corpus.evidence_files():
            if path.endswith((".obg", ".obs", ".ini")):
                continue
            lines = self.lines(path)
            for line_index, line in enumerate(lines):
                for match in arith_re.finditer(line):
                    base, expression = match.group(1), match.group(2)
                    if base not in self.by_key:
                        continue
                    callee, args = _call_context(lines, line_index, match.start())
                    ref = Ref(
                        key=base,
                        path=path,
                        line=line_index + 1,
                        column=match.start() + 1,
                        kind="arithmetic_base",
                        snippet=build_snippet(lines, line_index),
                        scope=enclosing_scope(lines, line_index),
                        call=callee,
                        args=args,
                        relation=f"computed StringID: {base} + {expression}",
                    )
                    arith_refs.setdefault(base, []).append((ref, expression))
        # Some ranges are written as ``(condition ? other : BASE) + offset``,
        # which the simple adjacency regex above does not see.  For the known
        # family bases, accept a nearby ``+`` on the same line as evidence.
        family_bases = {base for _, base, _, _ in self.ARITHMETIC_FAMILIES}
        for path in self.corpus.evidence_files():
            if path.endswith((".obg", ".obs", ".ini")):
                continue
            lines = self.lines(path)
            for line_index, line in enumerate(lines):
                for match in TOKEN_RE.finditer(line):
                    base = match.group(0)
                    if base not in family_bases or base in arith_refs:
                        continue
                    tail = line[match.end():]
                    plus = tail.find("+")
                    if plus < 0 or plus > 80:
                        continue
                    expression = tail[plus + 1:].strip().split(";", 1)[0][:60]
                    callee, args = _call_context(lines, line_index, match.start())
                    ref = Ref(
                        key=base,
                        path=path,
                        line=line_index + 1,
                        column=match.start() + 1,
                        kind="arithmetic_base",
                        snippet=build_snippet(lines, line_index),
                        scope=enclosing_scope(lines, line_index),
                        call=callee,
                        args=args,
                        relation=f"computed StringID: {base} + {expression}",
                    )
                    arith_refs.setdefault(base, []).append((ref, expression))
        for name, base, count, label in self.ARITHMETIC_FAMILIES:
            if base not in self.id_by_key:
                continue
            base_id = self.id_by_key[base]
            keys: List[str] = []
            for offset in range(count):
                key = self.key_by_id.get(base_id + offset)
                if key is None:
                    keys = []
                    break
                keys.append(key)
            if len(keys) != count:
                continue
            refs = [ref for ref, _ in arith_refs.get(base, [])]
            if not refs:
                continue
            family = {
                "name": name,
                "label": label,
                "base": base,
                "base_id": base_id,
                "keys": keys,
                "refs": refs,
                "expressions": sorted({expr for _, expr in arith_refs[base]}),
            }
            for offset, key in enumerate(keys):
                self._families[key] = dict(family, offset=offset)
            self._family_base_refs[base] = refs

    def _parse_vehicle_name_ranges(self) -> None:
        """Record ``STR_VEHICLE_NAME_* + local_id`` bases as partial evidence."""
        arith_re = re.compile(
            r"\b(STR_VEHICLE_NAME_[A-Z0-9_]+)\s*\+\s*[A-Za-z_][\w\.\->\[\]]*"
        )
        for path in self.corpus.evidence_files():
            if path.endswith((".obg", ".obs", ".ini")):
                continue
            lines = self.lines(path)
            for line_index, line in enumerate(lines):
                for match in arith_re.finditer(line):
                    base = match.group(1)
                    if base not in self.by_key:
                        continue
                    ref = Ref(
                        key=base,
                        path=path,
                        line=line_index + 1,
                        column=match.start() + 1,
                        kind="arithmetic_base",
                        snippet=build_snippet(lines, line_index),
                        scope=enclosing_scope(lines, line_index),
                        relation=f"computed StringID: {base} + table index",
                    )
                    self._vehicle_name_bases.append((base, ref))
        self._vehicle_name_bases.sort(key=lambda item: (item[0], item[1].path, item[1].line))

    # ----------------------------------------------------------------- lookup
    def lookup(self, key: str) -> Bundle:
        entry = self.by_key.get(key)
        if entry is None:
            return Bundle(key=key, text="", status="unknown_key", confidence="none")
        placeholders = placeholder_tokens(entry.text)
        direct = self.direct_refs(key)
        if direct:
            return Bundle(
                key=key,
                text=entry.text,
                status="direct",
                confidence="high",
                refs=direct,
                placeholders=placeholders,
                notes=[
                    "StringID token is referenced directly; definition row is not evidence.",
                ],
            )
        if key in self._cargo:
            macro_ref, row_ref = self._cargo[key]  # type: ignore[misc]
            return Bundle(
                key=key,
                text=entry.text,
                status="macro",
                confidence="high",
                refs=[macro_ref, row_ref],
                placeholders=placeholders,
                notes=[
                    "Reached through a token-pasting cargo macro; the row was parsed from "
                    "the CargoSpec table.",
                ],
            )
        if key in self._settings:
            info = self._settings[key]
            refs = [info["ini_ref"], info["rule_ref"]]  # type: ignore[list-item]
            return Bundle(
                key=key,
                text=entry.text,
                status="settings",
                confidence="high",
                refs=refs,
                placeholders=placeholders,
                notes=[
                    f"Settings dropdown option {info['value']} of "
                    f"{info['min']}..{info['max']} for {info['var']}.",
                ],
            )
        if key in self._families:
            info = self._families[key]
            refs = list(info["refs"])  # type: ignore[arg-type]
            return Bundle(
                key=key,
                text=entry.text,
                status="arithmetic",
                confidence="high",
                refs=refs,
                placeholders=placeholders,
                notes=[
                    f"StringID = {info['base']} + {info['offset']} "
                    f"({info['label']}); candidate verified contiguous.",
                ],
            )
        # Vehicle names are assigned by engine table index.  We can point at the
        # base expression but cannot prove this particular key without running
        # the engine, so this is explicitly partial.
        for base, ref in self._vehicle_name_bases:
            if base == key:
                continue
            base_id = self.id_by_key.get(base)
            if base_id is None:
                continue
            offset = self.id_by_key[key] - base_id
            if 0 < offset <= 128 and key.startswith(
                "STR_VEHICLE_NAME_" + base.split("STR_VEHICLE_NAME_", 1)[1].split("_", 1)[0] + "_"
            ):
                return Bundle(
                    key=key,
                    text=entry.text,
                    status="dynamic_unresolved",
                    confidence="low",
                    refs=[ref],
                    placeholders=placeholders,
                    notes=[
                        f"Only a computed base was found ({base} + %d); exact key "
                        "attribution needs an engine-table index and is not proven." % offset,
                    ],
                )
        return Bundle(
            key=key,
            text=entry.text,
            status="missing",
            confidence="none",
            placeholders=placeholders,
            notes=[
                "No direct token, macro row, settings range, or verified offset range "
                "was found in the allowlisted evidence.",
            ],
        )

    # ------------------------------------------------------------------ report
    def summary(self) -> Dict[str, object]:
        counts: Dict[str, int] = {}
        for entry in self.entries:
            status = self.lookup(entry.key).status
            counts[status] = counts.get(status, 0) + 1
        return {
            "project": "OpenTTD",
            "keys": len(self.entries),
            "evidence_files": len(self.corpus.evidence_files()),
            "cargo_keys": len(self._cargo),
            "settings_keys": len(self._settings),
            "family_keys": len(self._families),
            "vehicle_name_partial_bases": len(self._vehicle_name_bases),
            "status_counts": dict(sorted(counts.items())),
        }
