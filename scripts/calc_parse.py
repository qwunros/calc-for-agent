"""Expression parsing and evaluation for the ``calc-for-agent`` skill.

The parser is a hand-written tokenizer plus recursive-descent parser, so no
``eval`` is ever used and the accepted language is exactly what the skill
documents:

* numbers: ``42``, ``1_000_000``, ``1.25``, ``.5``, ``1e-9``, ``0xFF``, ``0b1011``
* fractions: ``3/4`` parses as an exact division
* operators: ``+ - * / // % ^ **``, unary ``+ -``, postfix ``!`` (factorial)
* implicit multiplication: ``2x``, ``3(4+5)``, ``2sqrt(2)``, ``(x+1)(x-2)``
* the radical sign ``√`` as a prefix operator
* functions and constants listed in :data:`FUNCTIONS` / :data:`CONSTANTS`

Evaluation is attempted exactly first (:class:`~calc_core.Exact`); anything that
leaves the exact field (``sin``, ``ln``, ``pi``, ...) is evaluated with the
high-precision :mod:`decimal` engine of ``calc_num`` and reported as an
approximation.
"""

from __future__ import annotations

import re
from decimal import Decimal
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple

from calc_core import CalcError, Exact, factorize, prime_factors
import calc_num as num

__all__ = [
    "CalcError",
    "parse",
    "eval_exact",
    "eval_numeric",
    "evaluate",
    "to_polynomial",
    "to_rational_function",
    "poly_degree",
    "poly_trim",
    "parse_equation",
    "FUNCTIONS",
    "CONSTANTS",
    "LIST_FUNCTIONS",
]

# name -> (min_args, max_args, exact?, description)
FUNCTIONS: Dict[str, Tuple[int, int, bool, str]] = {
    "sqrt": (1, 1, True, "square root; stays exact (e.g. sqrt(8) -> 2*sqrt(2)) when possible"),
    "cbrt": (1, 1, True, "cube root"),
    "root": (2, 2, True, "root(x, n): n-th root of x"),
    "pow": (2, 2, True, "pow(a, b): a to the power b (caret-free spelling of a**b)"),
    "abs": (1, 1, True, "absolute value"),
    "sign": (1, 1, True, "-1, 0 or 1"),
    "floor": (1, 1, True, "round down to an integer"),
    "ceil": (1, 1, True, "round up to an integer"),
    "trunc": (1, 1, True, "round toward zero"),
    "round": (1, 2, True, "round(x) or round(x, digits); half away from zero"),
    "min": (1, 8, True, "minimum of the arguments"),
    "max": (1, 8, True, "maximum of the arguments"),
    "gcd": (2, 8, True, "greatest common divisor of integers"),
    "lcm": (2, 8, True, "least common multiple of integers"),
    "factorial": (1, 1, True, "n! for a non-negative integer"),
    "comb": (2, 2, True, "binomial coefficient C(n, k)"),
    "perm": (2, 2, True, "number of k-permutations P(n, k)"),
    "fib": (1, 1, True, "n-th Fibonacci number (F(0)=0, F(1)=1)"),
    "isprime": (1, 1, True, "1 when the integer is prime, else 0"),
    "mod": (2, 2, True, "remainder with the sign of the divisor"),
    "exp": (1, 1, False, "e**x (approximate)"),
    "ln": (1, 1, False, "natural logarithm (approximate)"),
    "log": (1, 2, False, "log(x) or log(x, base) (approximate)"),
    "log2": (1, 1, False, "base-2 logarithm (approximate)"),
    "log10": (1, 1, False, "base-10 logarithm (approximate)"),
    "sin": (1, 1, True, "sine of radians; exact at multiples of pi/6 and pi/4, else approximate"),
    "cos": (1, 1, True, "cosine of radians; exact at multiples of pi/6 and pi/4, else approximate"),
    "tan": (1, 1, True, "tangent of radians; exact at multiples of pi/4 and pi/6, else approximate"),
    "asin": (1, 1, False, "inverse sine, radians (approximate)"),
    "acos": (1, 1, False, "inverse cosine, radians (approximate)"),
    "atan": (1, 1, False, "inverse tangent, radians (approximate)"),
    "sinh": (1, 1, False, "hyperbolic sine (approximate)"),
    "cosh": (1, 1, False, "hyperbolic cosine (approximate)"),
    "tanh": (1, 1, False, "hyperbolic tangent (approximate)"),
    "asinh": (1, 1, False, "inverse hyperbolic sine (approximate)"),
    "acosh": (1, 1, False, "inverse hyperbolic cosine (approximate)"),
    "atanh": (1, 1, False, "inverse hyperbolic tangent (approximate)"),
    "gamma": (1, 1, False, "Gamma function (Lanczos approximation, ~15 significant digits)"),
}

LIST_FUNCTIONS = tuple(sorted(FUNCTIONS))

# name -> description; pi/e/tau are numeric, phi is exactly (1+sqrt(5))/2
CONSTANTS: Dict[str, str] = {
    "pi": "3.14159... (approximate, computed to the requested precision)",
    "e": "2.71828... (approximate, computed to the requested precision)",
    "tau": "2*pi (approximate)",
    "phi": "golden ratio (1+sqrt(5))/2, kept exactly",
    "inf": "positive infinity (numeric only)",
}


class ParseError(CalcError):
    """Raised when an expression cannot be parsed."""


# --------------------------------------------------------------------------
# tokenizer
# --------------------------------------------------------------------------

_NUM_RE = re.compile(
    r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+"
    r"|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?"
)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_OPS = ("**", "//", "+", "-", "*", "/", "%", "^", "(", ")", ",", "!", "√")

_TOKEN_RE = re.compile(
    r"\s+|" + _NUM_RE.pattern + r"|" + _IDENT_RE.pattern + r"|" + "|".join(re.escape(o) for o in _OPS)
)


def tokenize(text: str) -> List[Tuple[str, str]]:
    tokens: List[Tuple[str, str]] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise ParseError(f"unexpected character {text[pos]!r} at position {pos}")
        pos = m.end()
        tok = m.group(0)
        if tok.isspace():
            continue
        if _NUM_RE.fullmatch(tok):
            tokens.append(("num", tok))
        elif _IDENT_RE.fullmatch(tok):
            tokens.append(("ident", tok))
        else:
            tokens.append(("op", tok))
    tokens.append(("eof", ""))
    return tokens


def _number_value(tok: str) -> Fraction:
    t = tok.replace("_", "")
    low = t.lower()
    if low.startswith("0x"):
        return Fraction(int(t, 16))
    if low.startswith("0b"):
        return Fraction(int(t, 2))
    if low.startswith("0o"):
        return Fraction(int(t, 8))
    if "e" in low:
        mant, _, exp = low.partition("e")
        return Fraction(Decimal(mant)) * Fraction(10) ** int(exp)
    return Fraction(Decimal(t))


# --------------------------------------------------------------------------
# parser -> tuple AST
# --------------------------------------------------------------------------


class _Parser:
    def __init__(self, tokens: List[Tuple[str, str]]):
        self.tokens = tokens
        self.i = 0

    # -- helpers -----------------------------------------------------------
    def peek(self) -> Tuple[str, str]:
        return self.tokens[self.i]

    def next(self) -> Tuple[str, str]:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def accept(self, value: str) -> bool:
        kind, text = self.peek()
        if kind == "op" and text == value:
            self.i += 1
            return True
        return False

    def expect(self, value: str) -> None:
        if not self.accept(value):
            raise ParseError(f"expected {value!r} but found {self.peek()[1]!r}")

    # -- grammar -----------------------------------------------------------
    def parse(self):
        node = self.expr()
        if self.peek()[0] != "eof":
            raise ParseError(f"unexpected trailing input {self.peek()[1]!r}")
        return node

    def expr(self):
        node = self.term()
        while True:
            kind, text = self.peek()
            if kind == "op" and text in ("+", "-"):
                self.next()
                rhs = self.term()
                node = ("bin", text, node, rhs)
            else:
                return node

    def _starts_atom(self) -> bool:
        kind, text = self.peek()
        if kind in ("num", "ident"):
            return True
        if kind == "op" and text in ("(", "√"):
            return True
        return False

    def term(self):
        node = self.unary()
        while True:
            kind, text = self.peek()
            if kind == "op" and text in ("*", "/", "//", "%"):
                self.next()
                rhs = self.unary()
                node = ("bin", text, node, rhs)
            elif self._starts_atom():
                rhs = self.unary()
                node = ("bin", "*", node, rhs)
            else:
                return node

    def unary(self):
        kind, text = self.peek()
        if kind == "op" and text in ("+", "-"):
            self.next()
            operand = self.unary()
            return operand if text == "+" else ("neg", operand)
        return self.power()

    def power(self):
        base = self.postfix()
        kind, text = self.peek()
        if kind == "op" and text in ("^", "**"):
            self.next()
            exponent = self.unary()
            return ("bin", "**", base, exponent)
        return base

    def postfix(self):
        node = self.atom()
        while self.accept("!"):
            node = ("call", "factorial", [node])
        return node

    def atom(self):
        kind, text = self.next()
        if kind == "num":
            return ("num", _number_value(text))
        if kind == "ident":
            name = text.lower()
            if self.peek() == ("op", "("):
                args = self.arglist()
                return ("call", name, args)
            return ("const", name) if name in CONSTANTS else ("var", text)
        if kind == "op" and text == "(":
            node = self.expr()
            self.expect(")")
            return node
        if kind == "op" and text == "√":
            return ("call", "sqrt", [self.unary()])
        raise ParseError(f"unexpected token {text!r}")

    def arglist(self) -> List:
        self.expect("(")
        args: List = []
        if self.accept(")"):
            return args
        while True:
            args.append(self.expr())
            if self.accept(","):
                continue
            self.expect(")")
            return args


def parse(text: str):
    """Parse ``text`` into an AST, raising :class:`ParseError` on bad input."""
    if text is None or not str(text).strip():
        raise ParseError("empty expression")
    return _Parser(tokenize(str(text))).parse()


def parse_equation(text: str) -> Tuple[object, object, str]:
    """Split ``"lhs = rhs"`` and return ``(lhs_ast, rhs_ast, var)``.

    A bare expression (no ``=``) is treated as ``expr = 0``.  The variable name
    is auto-detected from free identifiers when exactly one is present.
    """
    text = str(text).strip()
    if text.count("=") > 1:
        # allow == and <= / >= mistakes to fail loudly instead of silently
        raise ParseError("use a single '=' between the two sides of an equation")
    if "=" in text:
        lhs, _, rhs = text.partition("=")
    else:
        lhs, rhs = text, "0"
    left = parse(lhs)
    right = parse(rhs)
    names = set()
    for node in (left, right):
        _collect_vars(node, names)
    if len(names) > 1:
        raise ParseError(f"only one unknown is supported, found {sorted(names)}")
    var = names.pop() if names else "x"
    return left, right, var


def _collect_vars(node, out: set) -> None:
    if not isinstance(node, tuple):
        return
    tag = node[0]
    if tag == "var":
        out.add(node[1])
    elif tag == "bin":
        _collect_vars(node[2], out)
        _collect_vars(node[3], out)
    elif tag in ("neg",):
        _collect_vars(node[1], out)
    elif tag == "call":
        for arg in node[2]:
            _collect_vars(arg, out)


# --------------------------------------------------------------------------
# exact evaluation
# --------------------------------------------------------------------------


def _exact_int(value: Exact, what: str) -> int:
    if not value.is_rational():
        raise CalcError(f"{what} requires a rational argument")
    f = value.as_fraction()
    if f.denominator != 1:
        raise CalcError(f"{what} requires an integer argument")
    return f.numerator


def eval_exact(node, bindings: Optional[Dict[str, Exact]] = None) -> Optional[Exact]:
    """Evaluate exactly, or return ``None`` when the result leaves the exact field."""
    bindings = bindings or {}
    tag = node[0]
    if tag == "num":
        return Exact.from_fraction(node[1])
    if tag == "const":
        name = node[1]
        if name == "phi":
            # (1 + sqrt(5)) / 2
            root = Exact.sqrt_of_rational(Fraction(5))
            return Exact.from_fraction(Fraction(1, 2)).add(root.mul(Exact.from_fraction(Fraction(1, 2))))
        return None
    if tag == "var":
        if node[1] in bindings:
            return bindings[node[1]]
        raise CalcError(f"unknown variable {node[1]!r} (pass --var {node[1]}=<value>)")
    if tag == "neg":
        inner = eval_exact(node[1], bindings)
        return None if inner is None else inner.neg()
    if tag == "bin":
        op = node[1]
        left = eval_exact(node[2], bindings)
        if left is None:
            return None
        right = eval_exact(node[3], bindings)
        if right is None:
            return None
        if op == "+":
            return left.add(right)
        if op == "-":
            return left.sub(right)
        if op == "*":
            return left.mul(right)
        if op == "/":
            if right.is_zero():
                raise CalcError("division by zero")
            return left.div(right)
        if op == "//":
            if right.is_zero():
                raise CalcError("integer division by zero")
            q = left.div(right)
            fq = _floor_exact(q)
            return Exact.from_fraction(Fraction(fq))
        if op == "%":
            if right.is_zero():
                raise CalcError("modulo by zero")
            q = left.div(right)
            fq = _floor_exact(q)
            return left.sub(right.mul(Exact.from_fraction(Fraction(fq))))
        if op == "**":
            if not right.is_rational():
                return None
            exp_f = right.as_fraction()
            if exp_f.denominator != 1:
                return None
            n = exp_f.numerator
            if left.is_zero() and n < 0:
                raise CalcError("division by zero (0 raised to a negative power)")
            return left.pow_int(n)
        return None
    if tag == "call":
        return _call_exact(node[1], node[2], bindings)
    raise CalcError(f"unsupported expression node {tag!r}")


def _floor_exact(value: Exact) -> int:
    """Exact floor for any :class:`Exact` value."""
    if value.is_rational():
        f = value.as_fraction()
        return f.numerator // f.denominator
    rough = value.approx(30)
    extra = max(0, rough.adjusted() + 1)
    approx = value.approx(60 + extra)
    candidate = int(approx.to_integral_value(rounding="ROUND_FLOOR"))
    for delta in (0, -1, 1, -2, 2):
        k = candidate + delta
        if Exact.from_int(k).sub(value).sign() <= 0 and value.sub(Exact.from_int(k + 1)).sign() < 0:
            return k
    raise CalcError("could not determine the integer part exactly")


def _ceil_exact(value: Exact) -> int:
    return -_floor_exact(value.neg())


def _pi_linear(node) -> Optional[Tuple[Fraction, Fraction]]:
    """Return ``(c, d)`` with ``value = c*pi + d`` for rational ``c``/``d``.

    Used to recognise exact trigonometric values at multiples of pi.  Returns
    ``None`` as soon as the node is not a rational linear function of pi.
    """
    tag = node[0]
    if tag == "const" and node[1] == "pi":
        return Fraction(1), Fraction(0)
    if tag == "const" and node[1] == "tau":
        return Fraction(2), Fraction(0)
    if tag == "num":
        return Fraction(0), node[1]
    if tag == "neg":
        inner = _pi_linear(node[1])
        return None if inner is None else (-inner[0], -inner[1])
    if tag == "bin":
        op = node[1]
        if op in ("+", "-"):
            a = _pi_linear(node[2])
            b = _pi_linear(node[3])
            if a is None or b is None:
                return None
            return (a[0] + b[0], a[1] + b[1]) if op == "+" else (a[0] - b[0], a[1] - b[1])
        if op == "*":
            a = _pi_linear(node[2])
            b = _pi_linear(node[3])
            if a is None or b is None:
                return None
            if a[0] == 0:
                return a[1] * b[0], a[1] * b[1]
            if b[0] == 0:
                return b[1] * a[0], b[1] * a[1]
            return None
        if op == "/":
            a = _pi_linear(node[2])
            b = _pi_linear(node[3])
            if a is None or b is None:
                return None
            if b[0] != 0 or b[1] == 0:
                return None
            return a[0] / b[1], a[1] / b[1]
        return None
    if tag == "var":
        return None
    const = _try_const(node)
    if const is not None and const.is_rational():
        return Fraction(0), const.as_fraction()
    return None


_SQRT2_HALF = Exact.sqrt_of_rational(Fraction(1, 2))   # sqrt(2)/2
_SQRT3_HALF = Exact.sqrt_of_rational(Fraction(3, 4))   # sqrt(3)/2
_SPECIAL_SIN = {
    Fraction(0): Exact.from_int(0),
    Fraction(1, 6): Exact.from_fraction(Fraction(1, 2)),
    Fraction(1, 4): _SQRT2_HALF,
    Fraction(1, 3): _SQRT3_HALF,
    Fraction(1, 2): Exact.from_int(1),
}


def _special_sin(pi_multiple: Fraction) -> Optional[Exact]:
    """Exact ``sin(c*pi)`` for the classic angles, else ``None``."""
    f = pi_multiple % 2  # reduce modulo the period 2*pi
    if f <= Fraction(1, 2):
        angle, sign = f, 1
    elif f <= 1:
        angle, sign = 1 - f, 1
    elif f <= Fraction(3, 2):
        angle, sign = f - 1, -1
    else:
        angle, sign = 2 - f, -1
    value = _SPECIAL_SIN.get(angle)
    if value is None:
        return None
    return value if sign > 0 else value.neg()


def _special_cos(pi_multiple: Fraction) -> Optional[Exact]:
    return _special_sin(pi_multiple + Fraction(1, 2))


def _special_tan(pi_multiple: Fraction) -> Optional[Exact]:
    sin_value = _special_sin(pi_multiple)
    cos_value = _special_cos(pi_multiple)
    if sin_value is None or cos_value is None:
        return None
    if cos_value.is_zero():
        raise CalcError("tan() is undefined at odd multiples of pi/2")
    return sin_value.div(cos_value)


def _call_exact(name: str, args: List, bindings) -> Optional[Exact]:
    spec = FUNCTIONS.get(name)
    if spec is None:
        available = ", ".join(LIST_FUNCTIONS)
        raise CalcError(f"unknown function {name!r}; available: {available}")
    lo, hi, exact_capable, _desc = spec
    if not (lo <= len(args) <= hi):
        raise CalcError(
            f"{name}() takes {'exactly ' + str(lo) if lo == hi else f'{lo}..{hi}'} argument(s), got {len(args)}"
        )
    if name in ("sin", "cos", "tan"):
        # exact values at the classic angles (0, pi/6, pi/4, pi/3, pi/2, ...)
        linear = _pi_linear(args[0])
        if linear is not None and linear[1] == 0:
            special = {"sin": _special_sin, "cos": _special_cos, "tan": _special_tan}[name](linear[0])
            if special is not None:
                return special
        return None
    vals: List[Optional[Exact]] = []
    for arg in args:
        v = eval_exact(arg, bindings)
        if v is None:
            return None
        vals.append(v)
    if not exact_capable:
        return None
    if name == "sqrt":
        x = vals[0]
        if x.sign() < 0:
            raise CalcError("sqrt() of a negative number has no real value")
        return x.sqrt_exact()
    if name in ("cbrt", "root"):
        if name == "cbrt":
            x, n = vals[0], 3
        else:
            n = _exact_int(vals[1], "root() index")
            x = vals[0]
        if n == 0:
            raise CalcError("root() index must be non-zero")
        if n < 0:
            pos = x.nth_root_exact(-n)
            if pos is None:
                return None
            if pos.is_zero():
                raise CalcError("division by zero")
            return pos.reciprocal()
        return x.nth_root_exact(n)
    if name == "abs":
        return vals[0].abs()
    if name == "pow":
        if not vals[1].is_rational():
            return None
        exp_f = vals[1].as_fraction()
        if exp_f.denominator != 1:
            return None
        n = exp_f.numerator
        if vals[0].is_zero() and n < 0:
            raise CalcError("division by zero (0 raised to a negative power)")
        return vals[0].pow_int(n)
    if name == "sign":
        return Exact.from_int(vals[0].sign())
    if name == "floor":
        return Exact.from_int(_floor_exact(vals[0]))
    if name == "ceil":
        return Exact.from_int(_ceil_exact(vals[0]))
    if name == "trunc":
        x = vals[0]
        return Exact.from_int(_ceil_exact(x) if x.sign() < 0 else _floor_exact(x))
    if name == "round":
        x = vals[0]
        digits = _exact_int(vals[1], "round() digits") if len(vals) == 2 else 0
        if digits >= 0:
            scaled = x.mul(Exact.from_fraction(Fraction(10) ** digits))
        else:
            scaled = x.div(Exact.from_fraction(Fraction(10) ** (-digits)))
        sign = scaled.sign()
        mag = scaled.abs()
        fl = _floor_exact(mag)
        frac_part = mag.sub(Exact.from_int(fl))
        rounded = fl + (1 if frac_part.sub(Exact.from_fraction(Fraction(1, 2))).sign() >= 0 else 0)
        result = Exact.from_int(rounded) if sign >= 0 else Exact.from_int(-rounded)
        if digits > 0:
            result = result.div(Exact.from_fraction(Fraction(10) ** digits))
        elif digits < 0:
            result = result.mul(Exact.from_fraction(Fraction(10) ** (-digits)))
        return result
    if name in ("min", "max"):
        best = vals[0]
        for v in vals[1:]:
            diff = v.sub(best)
            if (name == "min" and diff.sign() < 0) or (name == "max" and diff.sign() > 0):
                best = v
        return best
    if name == "gcd":
        result = 0
        for v in vals:
            result = _gcd(result, abs(_exact_int(v, "gcd()")))
        return Exact.from_int(result)
    if name == "lcm":
        result = 1
        for v in vals:
            n = abs(_exact_int(v, "lcm()"))
            result = result * n // _gcd(result, n) if result else 0
        return Exact.from_int(result)
    if name == "factorial":
        n = _exact_int(vals[0], "factorial()")
        if n < 0 or n > 100000:
            raise CalcError("factorial() needs an integer between 0 and 100000")
        return Exact.from_int(_factorial(n))
    if name == "comb":
        n = _exact_int(vals[0], "comb()")
        k = _exact_int(vals[1], "comb()")
        if k < 0 or n < 0 or k > n:
            raise CalcError("comb(n, k) requires 0 <= k <= n")
        return Exact.from_int(_factorial(n) // (_factorial(k) * _factorial(n - k)))
    if name == "perm":
        n = _exact_int(vals[0], "perm()")
        k = _exact_int(vals[1], "perm()")
        if k < 0 or n < 0 or k > n:
            raise CalcError("perm(n, k) requires 0 <= k <= n")
        out = 1
        for i in range(n - k + 1, n + 1):
            out *= i
        return Exact.from_int(out)
    if name == "fib":
        n = _exact_int(vals[0], "fib()")
        if n < 0 or n > 1000000:
            raise CalcError("fib() needs an integer between 0 and 1000000")
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
        return Exact.from_int(a)
    if name == "isprime":
        from calc_core import is_prime

        n = _exact_int(vals[0], "isprime()")
        return Exact.from_int(1 if is_prime(n) else 0)
    if name == "mod":
        if vals[1].is_zero():
            raise CalcError("mod() by zero")
        q = _floor_exact(vals[0].div(vals[1]))
        return vals[0].sub(vals[1].mul(Exact.from_int(q)))
    return None


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return abs(a)


def _factorial(n: int) -> int:
    import math

    return math.factorial(n)


# --------------------------------------------------------------------------
# numeric evaluation
# --------------------------------------------------------------------------


def eval_numeric(node, prec: int = num.DEFAULT_PREC, bindings: Optional[Dict[str, Exact]] = None) -> Decimal:
    """Evaluate with the high-precision Decimal engine."""
    bindings = bindings or {}
    tag = node[0]
    if tag == "num":
        f = node[1]
        with num.localcontext() as ctx:
            ctx.prec = prec + 25
            return +(Decimal(f.numerator) / Decimal(f.denominator))
    if tag == "const":
        name = node[1]
        if name == "pi":
            return num.get_pi(prec + 10)
        if name == "e":
            return num.get_e(prec + 10)
        if name == "tau":
            return num.get_tau(prec + 10)
        if name == "phi":
            return (Decimal(1) + Decimal(5).sqrt()) / 2
        if name == "inf":
            return Decimal("Infinity")
        raise CalcError(f"unknown constant {name!r}")
    if tag == "var":
        if node[1] in bindings:
            return _exact_to_dec(bindings[node[1]], prec)
        raise CalcError(f"unknown variable {node[1]!r} (pass --var {node[1]}=<value>)")
    if tag == "neg":
        return -eval_numeric(node[1], prec, bindings)
    if tag == "bin":
        op = node[1]
        left = eval_numeric(node[2], prec, bindings)
        right = eval_numeric(node[3], prec, bindings)
        with num.localcontext() as ctx:
            ctx.prec = prec + 25
            if op == "+":
                return +(left + right)
            if op == "-":
                return +(left - right)
            if op == "*":
                return +(left * right)
            if op == "/":
                if right == 0:
                    raise CalcError("division by zero")
                return +(left / right)
            if op == "//":
                if right == 0:
                    raise CalcError("integer division by zero")
                return num.floor_dec(left / right)
            if op == "%":
                if right == 0:
                    raise CalcError("modulo by zero")
                return +(left - right * num.floor_dec(left / right))
            if op == "**":
                return num.pow_dec(left, right, prec)
        raise CalcError(f"unsupported operator {op!r}")
    if tag == "call":
        return _call_numeric(node[1], node[2], prec, bindings)
    raise CalcError(f"unsupported expression node {tag!r}")


def _exact_to_dec(value: Exact, prec: int) -> Decimal:
    with num.localcontext() as ctx:
        ctx.prec = prec + 25
        return +value.approx(prec + 10)


def _call_numeric(name: str, args: List, prec: int, bindings) -> Decimal:
    spec = FUNCTIONS.get(name)
    if spec is None:
        available = ", ".join(LIST_FUNCTIONS)
        raise CalcError(f"unknown function {name!r}; available: {available}")
    lo, hi, _exact_capable, _desc = spec
    if not (lo <= len(args) <= hi):
        raise CalcError(
            f"{name}() takes {'exactly ' + str(lo) if lo == hi else f'{lo}..{hi}'} argument(s), got {len(args)}"
        )
    vals = [eval_numeric(a, prec, bindings) for a in args]
    w = prec + 25
    if name == "sqrt":
        if vals[0] < 0:
            raise CalcError("sqrt() of a negative number has no real value")
        with num.localcontext() as ctx:
            ctx.prec = w
            return +vals[0].sqrt()
    if name == "cbrt":
        return num.root_dec(vals[0], 3, prec)
    if name == "root":
        n = int(vals[1])
        return num.root_dec(vals[0], n, prec)
    if name == "abs":
        return +vals[0].copy_abs()
    if name == "pow":
        return num.pow_dec(vals[0], vals[1], prec)
    if name == "sign":
        return Decimal(-1 if vals[0] < 0 else (1 if vals[0] > 0 else 0))
    if name == "floor":
        return num.floor_dec(vals[0])
    if name == "ceil":
        return num.ceil_dec(vals[0])
    if name == "trunc":
        return num.trunc_dec(vals[0])
    if name == "round":
        return num.round_dec(vals[0], int(vals[1]) if len(vals) == 2 else 0)
    if name == "min":
        return +min(vals)
    if name == "max":
        return +max(vals)
    if name == "gcd":
        a, b = int(vals[0]), int(vals[1])
        return Decimal(_gcd(a, b))
    if name == "lcm":
        result = 1
        for v in vals:
            n = abs(int(v))
            result = result * n // _gcd(result, n) if result else 0
        return Decimal(result)
    if name == "factorial":
        return Decimal(_factorial(int(vals[0])))
    if name == "comb":
        n, k = int(vals[0]), int(vals[1])
        return Decimal(_factorial(n) // (_factorial(k) * _factorial(n - k)))
    if name == "perm":
        n, k = int(vals[0]), int(vals[1])
        out = 1
        for i in range(n - k + 1, n + 1):
            out *= i
        return Decimal(out)
    if name == "fib":
        a, b = 0, 1
        for _ in range(int(vals[0])):
            a, b = b, a + b
        return Decimal(a)
    if name == "isprime":
        from calc_core import is_prime

        return Decimal(1 if is_prime(int(vals[0])) else 0)
    if name == "mod":
        if vals[1] == 0:
            raise CalcError("mod() by zero")
        with num.localcontext() as ctx:
            ctx.prec = w
            return +(vals[0] - vals[1] * num.floor_dec(vals[0] / vals[1]))
    if name == "exp":
        return num.exp_dec(vals[0], prec)
    if name == "ln":
        return num.ln_dec(vals[0], prec)
    if name == "log":
        if len(vals) == 2:
            return num.log_dec(vals[0], vals[1], prec)
        return num.ln_dec(vals[0], prec)
    if name == "log2":
        return num.log2_dec(vals[0], prec)
    if name == "log10":
        return num.log10_dec(vals[0], prec)
    if name == "sin":
        return num.sin_dec(vals[0], prec)
    if name == "cos":
        return num.cos_dec(vals[0], prec)
    if name == "tan":
        return num.tan_dec(vals[0], prec)
    if name == "asin":
        return num.asin_dec(vals[0], prec)
    if name == "acos":
        return num.acos_dec(vals[0], prec)
    if name == "atan":
        return num.atan_dec(vals[0], prec)
    if name == "sinh":
        return num.sinh_dec(vals[0], prec)
    if name == "cosh":
        return num.cosh_dec(vals[0], prec)
    if name == "tanh":
        return num.tanh_dec(vals[0], prec)
    if name == "asinh":
        return num.asinh_dec(vals[0], prec)
    if name == "acosh":
        return num.acosh_dec(vals[0], prec)
    if name == "atanh":
        return num.atanh_dec(vals[0], prec)
    if name == "gamma":
        return num.gamma_dec(vals[0], prec)
    raise CalcError(f"function {name!r} has no numeric implementation")


def evaluate(text_or_node, prec: int = num.DEFAULT_PREC, bindings=None, allow_approximate: bool = True):
    """Evaluate an expression, preferring the exact path.

    Returns ``(kind, value)`` where ``kind`` is ``"exact"`` with an
    :class:`Exact` value, or ``"approximate"`` with a :class:`~decimal.Decimal`.
    """
    node = parse(text_or_node) if isinstance(text_or_node, str) else text_or_node
    exact = eval_exact(node, bindings)
    if exact is not None:
        return "exact", exact
    if not allow_approximate:
        raise CalcError("this expression has no exact result")
    return "approximate", eval_numeric(node, prec, bindings)


# --------------------------------------------------------------------------
# polynomial extraction (used by the solver)
# --------------------------------------------------------------------------


def poly_trim(poly: Dict[int, Exact]) -> Dict[int, Exact]:
    return {d: c for d, c in poly.items() if not c.is_zero()}


def poly_degree(poly: Dict[int, Exact]) -> int:
    poly = poly_trim(poly)
    return max(poly) if poly else -1


def _poly_add(a: Dict[int, Exact], b: Dict[int, Exact]) -> Dict[int, Exact]:
    out = dict(a)
    for d, c in b.items():
        out[d] = out.get(d, Exact()).add(c)
    return poly_trim(out)


def _poly_scale(a: Dict[int, Exact], k: Exact) -> Dict[int, Exact]:
    return poly_trim({d: c.mul(k) for d, c in a.items()})


def _poly_mul(a: Dict[int, Exact], b: Dict[int, Exact]) -> Dict[int, Exact]:
    out: Dict[int, Exact] = {}
    for d1, c1 in a.items():
        for d2, c2 in b.items():
            d = d1 + d2
            out[d] = out.get(d, Exact()).add(c1.mul(c2))
    return poly_trim(out)


def to_rational_function(
    node, var: str
) -> Optional[Tuple[Dict[int, Exact], Dict[int, Exact]]]:
    """Return ``(numerator, denominator)`` polynomials for a rational expression.

    This extends :func:`to_polynomial` so that equations such as ``1/x = 4`` or
    ``(x+1)/(x-2) = 3`` are still solved exactly before falling back to numeric
    root finding.
    """
    tag = node[0]
    if tag == "var":
        if node[1] == var:
            return {1: Exact.from_int(1)}, {0: Exact.from_int(1)}
        return None
    if tag in ("call", "const"):
        const = _try_const(node)
        return None if const is None else ({0: const}, {0: Exact.from_int(1)})
    if tag == "num":
        return {0: Exact.from_fraction(node[1])}, {0: Exact.from_int(1)}
    if tag == "neg":
        inner = to_rational_function(node[1], var)
        if inner is None:
            return None
        return _poly_scale(inner[0], Exact.from_int(-1)), inner[1]
    if tag == "bin":
        op = node[1]
        left = to_rational_function(node[2], var)
        if left is None:
            return None
        right = to_rational_function(node[3], var)
        if right is None:
            return None
        n1, d1 = left
        n2, d2 = right
        if op == "+":
            return _poly_add(_poly_mul(n1, d2), _poly_mul(n2, d1)), _poly_mul(d1, d2)
        if op == "-":
            return _poly_add(_poly_mul(n1, d2), _poly_scale(_poly_mul(n2, d1), Exact.from_int(-1))), _poly_mul(d1, d2)
        if op == "*":
            return _poly_mul(n1, n2), _poly_mul(d1, d2)
        if op == "/":
            if poly_degree(n2) < 0:
                return None
            return _poly_mul(n1, d2), _poly_mul(d1, n2)
        if op == "**":
            if poly_degree(n2) != 0 or poly_degree(d2) != 0:
                return None
            exp_val = n2.get(0, Exact())
            if not exp_val.is_rational():
                return None
            f = exp_val.as_fraction()
            if f.denominator != 1 or f.numerator < 0 or f.numerator > 100:
                return None
            num_p, den_p = {0: Exact.from_int(1)}, {0: Exact.from_int(1)}
            for _ in range(f.numerator):
                num_p = _poly_mul(num_p, n1)
                den_p = _poly_mul(den_p, d1)
            return num_p, den_p
        return None
    return None


def _try_const(node) -> Optional[Exact]:
    """Return the exact value of a variable-free node, or ``None``."""
    try:
        return eval_exact(node, {})
    except CalcError:
        return None


def to_polynomial(node, var: str) -> Optional[Dict[int, Exact]]:
    """Convert an AST to ``{degree: coefficient}`` when it is a polynomial in ``var``."""
    tag = node[0]
    if tag == "var":
        if node[1] == var:
            return {1: Exact.from_int(1)}
        return None
    if tag in ("call", "const"):
        const = _try_const(node)
        return None if const is None else {0: const}
    if tag == "num":
        return {0: Exact.from_fraction(node[1])}
    if tag == "neg":
        inner = to_polynomial(node[1], var)
        return None if inner is None else _poly_scale(inner, Exact.from_int(-1))
    if tag == "bin":
        op = node[1]
        left = to_polynomial(node[2], var)
        if left is None:
            return None
        right = to_polynomial(node[3], var)
        if right is None:
            return None
        if op == "+":
            return _poly_add(left, right)
        if op == "-":
            return _poly_add(left, _poly_scale(right, Exact.from_int(-1)))
        if op == "*":
            return _poly_mul(left, right)
        if op == "/":
            if poly_degree(right) != 0:
                return None
            divisor = right.get(0, Exact.from_int(1))
            if divisor.is_zero():
                raise CalcError("division by zero")
            return _poly_scale(left, divisor.reciprocal())
        if op == "**":
            if poly_degree(right) != 0:
                return None
            exp_val = right.get(0, Exact())
            if not exp_val.is_rational():
                return None
            f = exp_val.as_fraction()
            if f.denominator != 1 or f.numerator < 0 or f.numerator > 200:
                return None
            result = {0: Exact.from_int(1)}
            for _ in range(f.numerator):
                result = _poly_mul(result, left)
            return result
        return None
    return None
