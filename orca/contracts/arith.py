"""
Safe deterministic arithmetic for ORNEUR contracts. NO Python evaluation of any kind: a tiny hand-written tokenizer and recursive-descent parser over
exact rationals (fractions.Fraction). Supported: non-negative integer/decimal literals, + - * / , unary + -, parentheses. Everything else (names, calls,
attributes, strings, exponent operators, unicode operators, scientific notation) is a syntax error. All sizes are bounded, so hostile input cannot exhaust CPU/memory.
"""
from __future__ import annotations

import re
from fractions import Fraction

MAX_EXPRESSION_CHARS = 200
MAX_TOKENS = 100
MAX_NESTING_DEPTH = 24
MAX_LITERAL_DIGITS = 30
MAX_RESULT_BITS = 4096
MAX_FRACTIONAL_DIGITS = 12                      # non-terminating results are rounded (half-even) to this many digits and flagged in evidence

_TOKEN = re.compile(r"\s*(?:(?P<num>[0-9]+(?:\.[0-9]+)?|\.[0-9]+)|(?P<op>[-+*/()]))")


class ArithmeticSyntaxError(ValueError):
    pass


class ArithmeticSizeError(ArithmeticSyntaxError):
    """Input that looks like arithmetic but exceeds the hard size/nesting/literal bounds (rejected, never evaluated)."""


class ArithmeticDomainError(ValueError):
    """Well-formed but has no value (division by zero) or exceeds the numeric bounds."""


def _tokenize(expr: str) -> list[tuple[str, str]]:
    if len(expr) > MAX_EXPRESSION_CHARS:
        raise ArithmeticSizeError("expression too long")
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        if expr[pos:].strip() == "":
            break
        m = _TOKEN.match(expr, pos)
        if not m:
            raise ArithmeticSyntaxError(f"unsupported character at {pos}")
        if m.group("num") is not None:
            if len(m.group("num").replace(".", "")) > MAX_LITERAL_DIGITS:
                raise ArithmeticSizeError("numeric literal too long")
            tokens.append(("num", m.group("num")))
        else:
            tokens.append(("op", m.group("op")))
        pos = m.end()
        if len(tokens) > MAX_TOKENS:
            raise ArithmeticSizeError("too many tokens")
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.t, self.i, self.binary_ops = tokens, 0, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expr(self, depth):
        if depth > MAX_NESTING_DEPTH:
            raise ArithmeticSizeError("nesting too deep")
        v = self.term(depth)
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            r = self.term(depth)
            self.binary_ops += 1
            v = v + r if op == "+" else v - r
            self._bound(v)
        return v

    def term(self, depth):
        v = self.unary(depth)
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            r = self.unary(depth)
            self.binary_ops += 1
            if op == "*":
                v = v * r
            else:
                if r == 0:
                    raise ArithmeticDomainError("division by zero")
                v = v / r
            self._bound(v)
        return v

    def unary(self, depth):
        if depth > MAX_NESTING_DEPTH:
            raise ArithmeticSizeError("nesting too deep")
        kind, val = self.peek()
        if kind == "op" and val in "+-":
            self.take()
            v = self.unary(depth + 1)
            return -v if val == "-" else v
        return self.primary(depth)

    def primary(self, depth):
        kind, val = self.take()
        if kind == "num":
            return Fraction(val)
        if kind == "op" and val == "(":
            v = self.expr(depth + 1)
            if self.take() != ("op", ")"):
                raise ArithmeticSyntaxError("expected ')'")
            return v
        raise ArithmeticSyntaxError("expected a number or '('")

    @staticmethod
    def _bound(v: Fraction):
        if v.numerator.bit_length() > MAX_RESULT_BITS or v.denominator.bit_length() > MAX_RESULT_BITS:
            raise ArithmeticDomainError("result exceeds the supported numeric size")


def evaluate(expr: str) -> tuple[Fraction, int]:
    """(exact value, number of binary operators). Raises ArithmeticSyntaxError / ArithmeticDomainError. Never evaluates code."""
    if not isinstance(expr, str):
        raise ArithmeticSyntaxError("expression must be text")
    p = _Parser(_tokenize(expr))
    v = p.expr(0)
    if p.i != len(p.t):
        raise ArithmeticSyntaxError("unexpected trailing tokens")
    return v, p.binary_ops


def format_result(v: Fraction) -> tuple[str, bool]:
    """Canonical text of an exact rational: integers as digits ('5', never '5.0'); terminating decimals exactly without trailing zeros; non-terminating values
    rounded half-even to MAX_FRACTIONAL_DIGITS (second element True = rounded, recorded in evidence). No exponent notation, no '-0'."""
    if v.denominator == 1:
        return str(v.numerator), False
    d, twos, fives = v.denominator, 0, 0
    while d % 2 == 0:
        d //= 2
        twos += 1
    while d % 5 == 0:
        d //= 5
        fives += 1
    rounded = d != 1
    scale = MAX_FRACTIONAL_DIGITS if rounded else max(twos, fives)
    scaled = v * (10 ** scale)
    n = scaled.numerator // scaled.denominator                      # floor
    rem = scaled - n
    if rem > Fraction(1, 2) or (rem == Fraction(1, 2) and n % 2 == 1):
        n += 1
    sign = "-" if n < 0 else ""
    n = abs(n)
    s = str(n).rjust(scale + 1, "0")
    whole, frac = s[:-scale], s[-scale:].rstrip("0")
    out = whole + ("." + frac if frac else "")
    return (sign + out if out.strip("0.") else out), rounded
