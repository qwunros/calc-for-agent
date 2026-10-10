"""Exact-arithmetic core for the ``calc-for-agent`` skill.

Everything here is pure standard library.  The central type is :class:`Exact`,
an element of a multiquadratic number field written as a finite sum

    sum over keys S of  c_S * sqrt(prod S)

where ``S`` is a tuple of distinct primes and ``c_S`` is a :class:`fractions.Fraction`.
That representation keeps the following exact:

* arbitrary-precision integers,
* arbitrary rational numbers / fractions,
* finite decimals (a finite decimal is exactly a rational number),
* square roots of rationals (``sqrt(8) == 2*sqrt(2)`` keeps its exact form),
* sums/products/quotients/integer powers of the above,
* exact statistics such as ``mean`` and ``variance``.

Operations that leave the field (``sqrt(sqrt(2))``, ``sin``, ``ln``, ...) are
reported through the high-precision :mod:`decimal` engine in ``calc_num`` and
are clearly marked as approximations.
"""

from __future__ import annotations

import math
import sys
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

# Exact arithmetic on large integers is the point of this tool, so lift CPython's
# 4300-digit int <-> str safety limit (which would otherwise break e.g. factorial(20000)).
_INT_STR_DIGIT_LIMIT = 200_000
try:  # pragma: no cover - depends on the interpreter build
    sys.set_int_max_str_digits(max(int(sys.get_int_max_str_digits()), _INT_STR_DIGIT_LIMIT))
except (AttributeError, ValueError):  # pragma: no cover
    pass

__all__ = [
    "Exact",
    "CalcError",
    "FactorizationError",
    "Fraction",
    "is_prime",
    "prime_factors",
    "factorize",
    "divisors",
    "squarefree_part",
    "perfect_power_root",
    "fraction_from_decimal_string",
    "fraction_to_decimal_string",
    "format_fraction",
    "mixed_number",
    "approx_float",
]

MAX_FRACTION_DIGITS = 10 ** 6  # guard against pathological input


class CalcError(Exception):
    """User-facing calculation error; carried into the JSON error payload."""

    def __init__(self, message: str, kind: str = "calc_error"):
        super().__init__(message)
        self.kind = kind

    @property
    def message(self) -> str:
        return str(self)

# --------------------------------------------------------------------------
# integer helpers
# --------------------------------------------------------------------------


def is_prime(n: int) -> bool:
    """Deterministic Miller-Rabin: exact for n < 3.3e24, very strong beyond."""
    if n < 2:
        return False
    small = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
    for p in small:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for a in small + (41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101):
        if a >= n:
            continue
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _pollard_brent(n: int, budget: List[int]) -> Optional[int]:
    """Find a non-trivial factor of a composite ``n`` (Brent's variant of rho).

    ``budget`` is a one-element list acting as a shared step counter; when it is
    exhausted the function returns ``None`` instead of running forever, so a
    number with very large prime factors fails cleanly rather than hanging.
    """
    import math as _math

    if n % 2 == 0:
        return 2
    if n % 3 == 0:
        return 3

    def spend(k: int = 1) -> bool:
        budget[0] -= k
        return budget[0] > 0

    for c in (1, 2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47):
        y, m = 2, 128
        g = r = q = 1
        x = ys = 0
        while g == 1:
            x = y
            for _ in range(r):
                y = (y * y + c) % n
            if not spend(max(1, min(r, 4096))):
                return None
            k = 0
            while k < r and g == 1:
                ys = y
                for _ in range(min(m, r - k)):
                    y = (y * y + c) % n
                    q = q * abs(x - y) % n
                if not spend(min(m, r - k)):
                    return None
                g = _math.gcd(q, n)
                k += m
            r *= 2
        if g == n:
            g = 1
            while g == 1:
                ys = (ys * ys + c) % n
                if not spend():
                    return None
                g = _math.gcd(abs(x - ys), n)
        if g != n:
            return g
    return None


class FactorizationError(CalcError):
    """Raised when a number cannot be factored within the effort budget."""


def factorize(n: int, max_steps: int = 2000000) -> Dict[int, int]:
    """Full prime factorisation ``n = prod(p**e)`` for ``n >= 1``.

    Trial division handles small factors; Miller-Rabin plus Pollard's rho
    handle large ones.  ``max_steps`` bounds the rho effort so that a hard
    semiprime raises :class:`FactorizationError` instead of blocking forever.
    """
    n = abs(int(n))
    out: Dict[int, int] = {}
    if n <= 1:
        return out
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        while n % p == 0:
            out[p] = out.get(p, 0) + 1
            n //= p
    stack = [n] if n > 1 else []
    budget = [max_steps]
    while stack:
        m = stack.pop()
        if m == 1:
            continue
        if is_prime(m):
            out[m] = out.get(m, 0) + 1
            continue
        if budget[0] <= 0:
            raise FactorizationError(
                f"could not factor {m} within the effort budget (large prime factors); "
                "increase --max-steps or factor the parts separately"
            )
        d = _pollard_brent(m, budget)
        if d is None or d in (1, m):
            raise FactorizationError(
                f"could not factor {m} within the effort budget (large prime factors); "
                "increase --max-steps or factor the parts separately"
            )
        stack.append(d)
        stack.append(m // d)
    return out


def prime_factors(n: int) -> List[int]:
    """Return the distinct prime factors of ``|n|`` in increasing order."""
    return sorted(factorize(n))


def divisors(n: int) -> List[int]:
    n = abs(int(n))
    if n == 0:
        return []
    out = [1]
    for p, e in sorted(factorize(n).items()):
        out = [d * p ** k for d in out for k in range(e + 1)]
    return sorted(out)


def squarefree_part(n: int) -> Tuple[int, int]:
    """Return ``(s, m)`` with ``n = s**2 * m`` and ``m`` squarefree."""
    n = abs(int(n))
    if n == 0:
        return 0, 0
    s, m = 1, 1
    for p, e in factorize(n).items():
        s *= p ** (e // 2)
        if e % 2:
            m *= p
    return s, m


def perfect_power_root(n: int, k: int) -> Optional[int]:
    """Exact integer ``k``-th root of ``n`` (``k >= 1``), or ``None``."""
    if k == 1:
        return n
    if k <= 0:
        raise ValueError("root index must be a positive integer")
    sign = -1 if n < 0 else 1
    if sign < 0 and k % 2 == 0:
        return None
    a = abs(int(n))
    if a in (0, 1):
        return sign * a
    r = int(round(a ** (1.0 / k)))
    for cand in range(max(0, r - 3), r + 4):
        if cand ** k == a:
            return sign * cand
    # widen only for huge exponents where the float estimate is unusable
    if a.bit_length() > 1000:
        lo, hi = 1, 1 << (a.bit_length() // k + 2)
        while lo <= hi:
            mid = (lo + hi) // 2
            v = mid ** k
            if v == a:
                return sign * mid
            if v < a:
                lo = mid + 1
            else:
                hi = mid - 1
    return None


# --------------------------------------------------------------------------
# the Exact value type
# --------------------------------------------------------------------------


def _norm_key(key: Iterable[int]) -> Tuple[int, ...]:
    return tuple(sorted(set(int(p) for p in key)))


def _term_body(c: Fraction, key: Tuple[int, ...], latex: bool = False) -> str:
    """Render the unsigned body of one term (sign is added by the caller)."""
    a = abs(c)
    if not key:
        return _latex_fraction(a) if latex else format_fraction(a)
    rad = 1
    for p in key:
        rad *= p
    root = f"\\sqrt{{{rad}}}" if latex else f"sqrt({rad})"
    if a == 1:
        return root
    if a.denominator == 1:
        return f"{a.numerator}{root}" if latex else f"{a.numerator}*{root}"
    if a.numerator == 1:
        return f"\\frac{{{root}}}{{{a.denominator}}}" if latex else f"{root}/{a.denominator}"
    return (
        f"\\frac{{{a.numerator}{root}}}{{{a.denominator}}}"
        if latex
        else f"{a.numerator}*{root}/{a.denominator}"
    )


_KEY_CACHE: Dict[Tuple[int, ...], Tuple[Tuple[int, ...], int]] = {}


def reduce_key(key: Iterable[int]) -> Tuple[Tuple[int, ...], int]:
    """Reduce a radical key to ``(prime_tuple, rational_scale)``.

    ``prod(sqrt(k) for k in key) == rational_scale * prod(sqrt(p) for p in primes)``.
    Keys produced internally are already prime tuples, so the common case is
    cheap; arbitrary keys such as ``(6,)`` or ``(2, 8)`` are reduced too.
    """
    raw = tuple(key)
    cached = _KEY_CACHE.get(raw)
    if cached is not None:
        return cached
    n = 1
    for k in raw:
        n *= abs(int(k))
    if n <= 1:
        out = ((), 1)
    else:
        s, m = squarefree_part(n)
        out = (tuple(prime_factors(m)), s)
    if len(_KEY_CACHE) < 4096:
        _KEY_CACHE[raw] = out
    return out


class Exact:
    """Exact value ``sum(c_S * sqrt(prod(S)))`` over squarefree radical keys."""

    __slots__ = ("terms",)

    def __init__(self, terms: Optional[Dict[Tuple[int, ...], Fraction]] = None):
        clean: Dict[Tuple[int, ...], Fraction] = {}
        if terms:
            for key, coeff in terms.items():
                k, scale = reduce_key(key)
                c = coeff if isinstance(coeff, Fraction) else Fraction(coeff)
                if scale != 1:
                    c = c * scale
                if c == 0:
                    continue
                total = clean.get(k, Fraction(0)) + c
                if total:
                    clean[k] = total
                elif k in clean:
                    del clean[k]
        self.terms: Dict[Tuple[int, ...], Fraction] = clean

    # -- constructors ------------------------------------------------------
    @staticmethod
    def from_int(n: int) -> "Exact":
        return Exact({(): Fraction(int(n))})

    @staticmethod
    def from_fraction(f: Fraction) -> "Exact":
        f = Fraction(f)
        if f == 0:
            return Exact()
        return Exact({(): f})

    @staticmethod
    def from_number(value) -> "Exact":
        if isinstance(value, Exact):
            return value
        if isinstance(value, Fraction):
            return Exact.from_fraction(value)
        if isinstance(value, int):
            return Exact.from_int(value)
        if isinstance(value, Decimal):
            return Exact.from_fraction(Fraction(value))
        if isinstance(value, float):
            return Exact.from_fraction(Fraction(str(value)))
        raise TypeError(f"cannot convert {value!r} to Exact")

    @staticmethod
    def sqrt_of_rational(q) -> Optional["Exact"]:
        """Exact ``sqrt(q)`` for rational ``q >= 0``, else ``None``."""
        q = Fraction(q)
        if q < 0:
            return None
        if q == 0:
            return Exact()
        num, den = q.numerator, q.denominator
        try:
            sn, mn = squarefree_part(num)
            sd, md = squarefree_part(den)
        except FactorizationError:
            return None
        # sqrt(num/den) = sqrt(num*den)/den = sn*sd*sqrt(mn*md)/den
        rad = mn * md
        s, m = squarefree_part(rad)
        coeff = Fraction(sn * sd * s, den)
        if m == 1:
            return Exact.from_fraction(coeff)
        return Exact({tuple(prime_factors(m)): coeff})

    @staticmethod
    def nth_root_of_rational(q, n: int) -> Optional["Exact"]:
        """Exact ``q ** (1/n)`` for rational ``q`` when it exists, else ``None``."""
        q = Fraction(q)
        if n <= 0:
            return None
        if n == 1:
            return Exact.from_fraction(q)
        if n == 2:
            # square roots stay in the exact field even when they are irrational
            return Exact.sqrt_of_rational(q)
        neg = q < 0
        if neg and n % 2 == 0:
            return None
        a = abs(q)
        rn = perfect_power_root(a.numerator, n)
        rd = perfect_power_root(a.denominator, n)
        if rn is None or rd is None:
            return None
        val = Fraction(-rn if neg else rn, rd)
        return Exact.from_fraction(val)

    # -- predicates --------------------------------------------------------
    def is_zero(self) -> bool:
        return not self.terms

    def is_rational(self) -> bool:
        return all(k == () for k in self.terms)

    def is_positive(self) -> bool:
        return self.sign() > 0

    def as_fraction(self) -> Fraction:
        if not self.is_rational():
            raise ValueError("value is irrational")
        return self.terms.get((), Fraction(0))

    def to_fraction(self) -> Fraction:
        return self.as_fraction()

    # -- arithmetic --------------------------------------------------------
    def add(self, other: "Exact") -> "Exact":
        terms = dict(self.terms)
        for k, c in other.terms.items():
            v = terms.get(k, Fraction(0)) + c
            if v:
                terms[k] = v
            elif k in terms:
                del terms[k]
        return Exact(terms)

    def sub(self, other: "Exact") -> "Exact":
        return self.add(other.neg())

    def neg(self) -> "Exact":
        return Exact({k: -c for k, c in self.terms.items()})

    def mul(self, other: "Exact") -> "Exact":
        if self.is_zero() or other.is_zero():
            return Exact()
        out: Dict[Tuple[int, ...], Fraction] = {}
        for k1, c1 in self.terms.items():
            for k2, c2 in other.terms.items():
                coeff = c1 * c2
                common = set(k1) & set(k2)
                for p in common:
                    coeff *= p
                key = tuple(sorted(set(k1) ^ set(k2)))
                v = out.get(key, Fraction(0)) + coeff
                if v:
                    out[key] = v
                elif key in out:
                    del out[key]
        return Exact(out)

    def reciprocal(self) -> "Exact":
        if self.is_zero():
            raise ZeroDivisionError("division by zero")
        if len(self.terms) == 1:
            key, c = next(iter(self.terms.items()))
            rad = 1
            for p in key:
                rad *= p
            # 1/(c*sqrt(rad)) = sqrt(rad)/(c*rad)
            return Exact({key: Fraction(1, 1) / (c * rad)})
        # pick a prime appearing in some key and split E = A + sqrt(p)*B
        p = None
        for key in self.terms:
            if key:
                p = key[0]
                break
        assert p is not None
        a_terms: Dict[Tuple[int, ...], Fraction] = {}
        b_terms: Dict[Tuple[int, ...], Fraction] = {}
        for key, c in self.terms.items():
            if p in key:
                b_terms[tuple(x for x in key if x != p)] = c
            else:
                a_terms[key] = c
        A = Exact(a_terms)
        B = Exact(b_terms)
        denom = A.mul(A).sub(B.mul(B).mul(Exact.from_int(p)))
        conj = A.sub(B.mul(Exact({(p,): Fraction(1)})))
        return conj.mul(denom.reciprocal())

    def div(self, other: "Exact") -> "Exact":
        return self.mul(other.reciprocal())

    def pow_int(self, n: int) -> "Exact":
        n = int(n)
        if n == 0:
            return Exact.from_int(1)
        if n < 0:
            return self.reciprocal().pow_int(-n)
        result = Exact.from_int(1)
        base = self
        while n:
            if n & 1:
                result = result.mul(base)
            n >>= 1
            if n:
                base = base.mul(base)
        return result

    def square(self) -> "Exact":
        return self.mul(self)

    def abs(self) -> "Exact":
        return self if self.sign() >= 0 else self.neg()

    def sqrt_exact(self) -> Optional["Exact"]:
        """Exact square root when it exists, else ``None``."""
        if len(self.terms) == 1:
            key, c = next(iter(self.terms.items()))
            if not key:
                return Exact.sqrt_of_rational(c)
            # sqrt(c*sqrt(N)) is exact only when c*N is a perfect 4th-power
            # shaped value; accept the r**2 case c == sqrt(N) * k**2 form,
            # i.e. sqrt(c*sqrt(N)) = k * N**(1/4) * ... -> not in this field.
            return None
        return None

    def nth_root_exact(self, n: int) -> Optional["Exact"]:
        if self.is_rational():
            return Exact.nth_root_of_rational(self.as_fraction(), n)
        return None

    # -- ordering / numerics ----------------------------------------------
    def approx(self, prec: int = 30) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = prec + 12
            total = Decimal(0)
            for key, c in self.terms.items():
                term = Decimal(c.numerator) / Decimal(c.denominator)
                if key:
                    rad = 1
                    for p in key:
                        rad *= p
                    term *= Decimal(rad).sqrt()
                total += term
            return +total

    def sign(self) -> int:
        if not self.terms:
            return 0
        if len(self.terms) == 1:
            key, c = next(iter(self.terms.items()))
            return 1 if c > 0 else -1
        for prec in (30, 60, 120, 240, 480):
            v = self.approx(prec)
            if v == 0:
                continue
            mag = sum(abs(c) for c in self.terms.values())
            magd = Decimal(mag.numerator) / Decimal(mag.denominator)
            bound = Decimal(10) ** (-(prec - 5)) * (magd + 1)
            if abs(v) > bound:
                return 1 if v > 0 else -1
        raise ArithmeticError("cannot determine the sign of this value reliably")

    def to_float(self) -> float:
        with localcontext() as ctx:
            ctx.prec = 60
            return float(self.approx(50))

    # -- rendering ---------------------------------------------------------
    def _sorted_terms(self) -> List[Tuple[Tuple[int, ...], Fraction]]:
        items = list(self.terms.items())
        items.sort(key=lambda kv: (len(kv[0]), kv[0]) if kv[0] else (10 ** 6, ()))
        return items

    def __str__(self) -> str:
        if not self.terms:
            return "0"
        if self.is_rational():
            return format_fraction(self.as_fraction())
        parts: List[str] = []
        for key, c in self._sorted_terms():
            body = _term_body(c, key)
            if not parts:
                parts.append(("-" if c < 0 else "") + body)
            else:
                parts.append(("- " if c < 0 else "+ ") + body)
        text = parts[0] + (" " + " ".join(parts[1:]) if len(parts) > 1 else "")
        return text

    def __repr__(self) -> str:
        return f"Exact({self})"

    def latex(self) -> str:
        if not self.terms:
            return "0"
        if self.is_rational():
            return _latex_fraction(self.as_fraction())
        parts: List[str] = []
        for key, c in self._sorted_terms():
            body = _term_body(c, key, latex=True)
            if not parts:
                parts.append(("-" if c < 0 else "") + body)
            else:
                parts.append(("- " if c < 0 else "+ ") + body)
        return parts[0] + (" " + " ".join(parts[1:]) if len(parts) > 1 else "")

    def __eq__(self, other) -> bool:
        if not isinstance(other, Exact):
            try:
                other = Exact.from_number(other)
            except (TypeError, ValueError):
                return NotImplemented
        return self.terms == other.terms

    def __hash__(self) -> int:
        return hash(tuple(sorted(self.terms.items())))


# --------------------------------------------------------------------------
# rational formatting / parsing
# --------------------------------------------------------------------------


def format_fraction(f) -> str:
    f = Fraction(f)
    if f.denominator == 1:
        return str(f.numerator)
    return f"{f.numerator}/{f.denominator}"


def _latex_fraction(f) -> str:
    f = Fraction(f)
    if f.denominator == 1:
        return str(f.numerator)
    sign = "-" if f < 0 else ""
    a = abs(f)
    return f"{sign}\\frac{{{a.numerator}}}{{{a.denominator}}}"


def mixed_number(f) -> str:
    f = Fraction(f)
    if f.denominator == 1:
        return str(f.numerator)
    sign = "-" if f < 0 else ""
    a = abs(f)
    whole, rem = divmod(a.numerator, a.denominator)
    if whole == 0:
        return f"{sign}{rem}/{a.denominator}"
    return f"{sign}{whole} {rem}/{a.denominator}"


def approx_float(f) -> float:
    if isinstance(f, Fraction):
        return f.numerator / f.denominator
    if isinstance(f, Exact):
        return f.to_float()
    return float(f)


def fraction_from_decimal_string(text: str) -> Fraction:
    """Parse ``"3/4"``, ``"1.25"``, ``".5"``, ``"1e-3"``, ``"0.1(6)"`` exactly."""
    s = str(text).strip().replace("_", "").replace(" ", "")
    if not s:
        raise ValueError("empty numeric literal")
    if "/" in s:
        num, den = s.split("/", 1)
        try:
            return Fraction(int(num), int(den))
        except ValueError:
            raise ValueError(f"invalid fraction literal: {text!r}")
    neg = s.startswith("-")
    if s[0] in "+-":
        s = s[1:]
    if s.startswith("."):
        s = "0" + s
    if "e" in s.lower():
        mant, _, exp = s.lower().partition("e")
        base = fraction_from_decimal_string(mant)
        e = int(exp)
        f = base * Fraction(10) ** e
        return -f if neg else f
    if "(" in s:
        if not s.endswith(")"):
            raise ValueError(f"invalid recurring decimal: {text!r}")
        head, _, rest = s.partition("(")
        repeat = rest[:-1]
        if not repeat.isdigit():
            raise ValueError(f"invalid recurring decimal: {text!r}")
        if "." in head:
            ipart, fpart = head.split(".", 1)
        else:
            ipart, fpart = head, ""
        if not ipart:
            ipart = "0"
        value = Fraction(int(ipart))
        if fpart:
            value += Fraction(int(fpart), 10 ** len(fpart))
        value += Fraction(int(repeat), (10 ** len(repeat) - 1) * 10 ** len(fpart))
        return -value if neg else value
    if "." in s:
        ipart, fpart = s.split(".", 1)
        if not ipart:
            ipart = "0"
        if not fpart.isdigit() or not ipart.isdigit():
            raise ValueError(f"invalid decimal literal: {text!r}")
        value = Fraction(int(ipart)) + Fraction(int(fpart), 10 ** len(fpart))
        return -value if neg else value
    if not s.isdigit():
        raise ValueError(f"invalid numeric literal: {text!r}")
    value = Fraction(int(s))
    return -value if neg else value


def fraction_to_decimal_string(f, max_digits: int = 30, recurring: bool = True) -> dict:
    """Render a fraction as a decimal, detecting exact/recurring expansions.

    Returns ``{"text", "kind", "exact", "digits"}`` where ``kind`` is one of
    ``"integer"``, ``"terminating"``, ``"recurring"`` or ``"rounded"``.
    """
    f = Fraction(f)
    sign = "-" if f < 0 else ""
    a = abs(f)
    if a.denominator == 1:
        return {"text": f"{sign}{a.numerator}", "kind": "integer", "exact": True, "digits": 0}
    whole, rem = divmod(a.numerator, a.denominator)
    # terminating?
    den = a.denominator
    for p in (2, 5):
        while den % p == 0:
            den //= p
    if den == 1:
        twos = 0
        d = a.denominator
        while d % 2 == 0:
            d //= 2
            twos += 1
        fives = 0
        while d % 5 == 0:
            d //= 5
            fives += 1
        digits = max(twos, fives)
        scaled = rem * 10 ** digits // a.denominator
        text = f"{sign}{whole}." + str(scaled).rjust(digits, "0")
        return {"text": text, "kind": "terminating", "exact": True, "digits": digits}
    # recurring cycle by long division, capped
    seen: Dict[int, int] = {}
    digits: List[str] = []
    r = rem
    period_start = None
    limit = min(max_digits, 5000) if recurring else max_digits
    while r and len(digits) < limit:
        if r in seen:
            period_start = seen[r]
            break
        seen[r] = len(digits)
        r *= 10
        digits.append(str(r // a.denominator))
        r %= a.denominator
    body = "".join(digits)
    if r == 0:
        text = f"{sign}{whole}.{body}".rstrip("0")
        return {"text": text, "kind": "terminating", "exact": True, "digits": len(digits)}
    if period_start is not None:
        head, cycle = body[:period_start], body[period_start:]
        text = f"{sign}{whole}.{head}({cycle})"
        return {"text": text, "kind": "recurring", "exact": True, "digits": len(digits)}
    with localcontext() as ctx:
        ctx.prec = max_digits + 5
        q = (Decimal(a.numerator) / Decimal(a.denominator))
    text = f"{sign}{whole}." + body[:max_digits]
    return {"text": text, "kind": "rounded", "exact": False, "digits": max_digits, "value": str(+q)}
