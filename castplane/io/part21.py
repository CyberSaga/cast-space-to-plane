"""ISO 10303-21 ("Part 21", the STEP physical file) syntax subset (contract §5.5.2).

Standard library only; no semantics and no OpenCascade.

    tokens = tokenize(text)          # [(kind, text), ...]; comments and whitespace dropped
    doc    = parse(text)             # {"header": {NAME: args}, "entities": {"#15": (NAME, args), ...}}

Tokens are the alternatives of **one** regular expression (so a ``/*`` inside a quoted string is
never taken for a comment): ``skip`` (whitespace, ``/* ... */``), ``ref`` ``#123``, ``str``
``'...'`` (``''`` escape), ``enum`` ``.NAME.``, ``real`` (``int`` when it has no ``.`` / ``E``),
``name`` (``ISO-10303-21`` included) and ``punct`` ``( ) , ; = * $``.

Values: ``#n`` -> the string ``"#n"``; strings unescaped (``\\X2\\...\\X0\\`` kept verbatim);
enumerations keep their dots (``".T."``); numbers -> ``int`` / ``float``; ``$`` and ``*`` -> ``None``;
``( ... )`` -> list; a typed value ``NAME(value)`` -> the tuple ``(NAME, value)``.  An instance is
``(NAME, args)``; a complex instance ``(A(...) B(...))`` is ``("COMPLEX", [(A, args), (B, args)])``.
Every syntax problem is a :class:`Part21SyntaxError` naming the character offset.
"""

from __future__ import annotations

import re

__all__ = ["Part21SyntaxError", "tokenize", "parse"]


class Part21SyntaxError(ValueError):
    """A Part 21 syntax error at character ``offset`` of the text."""

    def __init__(self, offset: int, message: str):
        self.offset = int(offset)
        self.message = message
        super().__init__(f"{message} at offset {self.offset}")


#: Deepest accepted nesting of lists / typed values (real Part 21 files nest at most 3 deep); a
#: deeper value is a syntax error instead of a ``RecursionError`` (review fix).
_MAX_NESTING = 64

#: Longest accepted entity id (digits after ``#``; 18 digits stay below 2**63, the integer range of
#: every Part 21 writer); a longer id is a syntax error instead of an ``int()`` failure (review fix).
_MAX_REF_DIGITS = 18


_TOKEN_RE = re.compile(r"""
      (?P<skip>  \s+ | /\*.*?\*/ )
    | (?P<ref>   \#\d+ )
    | (?P<str>   '(?:[^']|'')*' )
    | (?P<enum>  \.[A-Z0-9_]+\. )
    | (?P<real>  [+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][+-]?\d+)? )
    | (?P<name>  [A-Z_][A-Z0-9_-]* )
    | (?P<punct> [(),;=*$] )
""", re.X | re.S)


def _scan(text: str) -> list:
    """``[(kind, text, offset), ...]`` without the ``skip`` tokens."""
    out = []
    pos, n = 0, len(text)
    match = _TOKEN_RE.match
    while pos < n:
        m = match(text, pos)
        if m is None:
            if text.startswith("/*", pos):
                raise Part21SyntaxError(pos, "unterminated comment")
            if text[pos] == "'":
                raise Part21SyntaxError(pos, "unterminated string")
            raise Part21SyntaxError(pos, f"unexpected character {text[pos]!r}")
        kind = m.lastgroup
        if kind == "ref" and m.end() - pos - 1 > _MAX_REF_DIGITS:
            raise Part21SyntaxError(pos, f"entity id too long (more than {_MAX_REF_DIGITS} digits)")
        if kind != "skip":
            out.append((kind, m.group(), pos))
        pos = m.end()
    return out


def tokenize(text: str) -> list:
    """The token list ``[(kind, text), ...]`` of a Part 21 text (whitespace and comments dropped)."""
    return [(kind, tok) for kind, tok, _ in _scan(text)]


def _number(tok: str):
    """``float`` for a token with ``.`` / ``E``; otherwise ``int`` when the value is exactly
    representable as a double (``|v| < 2**53``), else the correctly rounded ``float`` (``inf``
    beyond 1e308), so a huge integer literal never reaches ``int()``'s digit limit nor raises
    ``OverflowError`` later (review fix; non-finite values are rejected by the reader)."""
    f = float(tok)
    if "." in tok or "E" in tok or "e" in tok:
        return f
    return int(tok) if abs(f) < 2.0 ** 53 else f


class _Parser:
    def __init__(self, text: str):
        self.tokens = _scan(text)
        self.end = len(text)
        self.i = 0
        self.depth = 0

    # -- token access -------------------------------------------------------------------------
    def peek(self):
        if self.i >= len(self.tokens):
            raise Part21SyntaxError(self.end, "unexpected end of input")
        return self.tokens[self.i]

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, kind: str, text: str | None = None):
        k, t, off = self.next()
        if k != kind or (text is not None and t != text):
            want = repr(text) if text is not None else kind
            raise Part21SyntaxError(off, f"expected {want}, found {t!r}")
        return t, off

    def at(self, kind: str, text: str | None = None) -> bool:
        if self.i >= len(self.tokens):
            return False
        k, t, _ = self.tokens[self.i]
        return k == kind and (text is None or t == text)

    # -- grammar ------------------------------------------------------------------------------
    def value(self):
        kind, tok, off = self.next()
        if kind == "ref":
            return tok
        if kind == "str":
            return tok[1:-1].replace("''", "'")
        if kind == "enum":
            return tok
        if kind == "real":
            return _number(tok)
        if kind == "punct":
            if tok in ("$", "*"):
                return None
            if tok == "(":
                return self._nested(off, self.args_after_open)
        if kind == "name":
            self.expect("punct", "(")
            inner = self._nested(off, self.value)
            self.expect("punct", ")")
            return (tok, inner)
        raise Part21SyntaxError(off, f"unexpected {tok!r} where a value is expected")

    def _nested(self, off: int, parse_inner):
        """``parse_inner()`` one nesting level deeper; past :data:`_MAX_NESTING` a syntax error."""
        if self.depth >= _MAX_NESTING:
            raise Part21SyntaxError(off, f"nesting too deep (more than {_MAX_NESTING} levels)")
        self.depth += 1
        try:
            return parse_inner()
        finally:
            self.depth -= 1

    def args_after_open(self) -> list:
        """The comma-separated values after an opening ``(`` up to and including its ``)``."""
        out = []
        if self.at("punct", ")"):
            self.next()
            return out
        while True:
            out.append(self.value())
            kind, tok, off = self.next()
            if kind == "punct" and tok == ")":
                return out
            if not (kind == "punct" and tok == ","):
                raise Part21SyntaxError(off, f"expected ',' or ')', found {tok!r}")

    def record(self):
        """``NAME ( args )``."""
        name, _ = self.expect("name")
        self.expect("punct", "(")
        return name, self.args_after_open()

    def instance(self):
        if self.at("punct", "("):
            self.next()
            parts = []
            while not self.at("punct", ")"):
                parts.append(self.record())
            _, off = self.expect("punct", ")")
            if not parts:
                raise Part21SyntaxError(off, "empty complex entity")
            return ("COMPLEX", parts)
        return self.record()

    def parse(self) -> dict:
        self.expect("name", "ISO-10303-21")
        self.expect("punct", ";")
        self.expect("name", "HEADER")
        self.expect("punct", ";")
        header = {}
        while not self.at("name", "ENDSEC"):
            name, args = self.record()
            self.expect("punct", ";")
            header[name] = args
        self.expect("name", "ENDSEC")
        self.expect("punct", ";")
        entities = {}
        if not self.at("name", "DATA"):
            kind, tok, off = self.peek()
            raise Part21SyntaxError(off, f"expected 'DATA', found {tok!r}")
        while self.at("name", "DATA"):
            self.next()
            self.expect("punct", ";")
            while not self.at("name", "ENDSEC"):
                ref, off = self.expect("ref")
                if ref in entities:
                    raise Part21SyntaxError(off, f"duplicate instance {ref}")
                self.expect("punct", "=")
                entities[ref] = self.instance()
                self.expect("punct", ";")
            self.expect("name", "ENDSEC")
            self.expect("punct", ";")
        self.expect("name", "END-ISO-10303-21")
        self.expect("punct", ";")
        if self.i < len(self.tokens):
            _, tok, off = self.tokens[self.i]
            raise Part21SyntaxError(off, f"unexpected {tok!r} after END-ISO-10303-21")
        return {"header": header, "entities": entities}


def parse(text: str) -> dict:
    """Parse a Part 21 text into ``{"header": {NAME: args}, "entities": {"#id": instance}}``
    (contract §5.5.2).  No semantic checks."""
    return _Parser(text).parse()
