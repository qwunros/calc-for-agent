"""Domain commands for the ``calc-for-agent`` skill.

Each ``do_*`` function takes already-validated arguments and returns a plain
JSON-serialisable dict, raising :class:`~calc_core.CalcError` for anything the
caller should report as a failed calculation.
"""

from __future__ import annotations

import math
from decimal import Decimal
from fractions import Fraction
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import calc_num as num
from calc_core import (
    CalcError,
    Exact,
    FactorizationError,
    divisors,
    factorize,
    format_fraction,
    fraction_from_decimal_string,
    fraction_to_decimal_string,
    is_prime,
    mixed_number,
    prime_factors,
)
import calc_parse as cp


# --------------------------------------------------------------------------
# shared value description
# --------------------------------------------------------------------------


def describe(kind: str, value, prec: int = num.DEFAULT_PREC, digits: int = 30, extra: bool = True) -> dict:
    """Turn an ``Exact`` or ``Decimal`` into the JSON result payload."""
    digits = max(1, int(digits))
    if kind == "exact":
        assert isinstance(value, Exact)
        if _is_unrenderable(value):
            return _describe_huge(value, prec, digits)
        out: dict = {
            "kind": "exact",
            "exact": str(value),
            "latex": value.latex(),
        }
        approx = num.fmt_dec(value.approx(min(num.MAX_PREC, max(prec + 10, digits + 10))), digits)
        out["approx"] = approx
        if value.is_rational():
            f = value.as_fraction()
            out["type"] = "integer" if f.denominator == 1 else "rational"
            out["fraction"] = format_fraction(f)
            out["mixed"] = mixed_number(f)
            dec = fraction_to_decimal_string(f, max(digits, 30))
            out["decimal"] = dec["text"]
            out["decimal_kind"] = dec["kind"]
            if extra and abs(f.numerator) < 10 ** 15 and f.denominator == 1:
                n = f.numerator
                if 1 <= n <= 10 ** 12:
                    fact = factorize(n)
                    if fact and len(fact) > 0:
                        out["factorization"] = " * ".join(
                            f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(fact.items())
                        )
                    out["is_prime"] = is_prime(n) if n > 1 else False
        else:
            out["type"] = "irrational_exact"
        adj = 0 if value.is_zero() else value.abs().approx(20).adjusted()
        out["float"] = value.to_float() if -300 < adj < 290 else None
        return out
    if kind == "approximate":
        d = value if isinstance(value, Decimal) else Decimal(value)
        text = num.fmt_dec(d, digits)
        out = {"kind": "approximate", "approx": text, "exact": None, "type": "approximate"}
        try:
            f = float(d)
            out["float"] = f if math.isfinite(f) else None
        except (OverflowError, ValueError):
            out["float"] = None
        return out
    raise CalcError(f"unknown value kind {kind!r}")


def _value_from_text(text: str) -> Fraction:
    return fraction_from_decimal_string(text)


# CPython refuses int -> str conversions above a digit limit (calc_core lifts it
# to 200000 digits).  Results near that bound are described instead of rendered.
_UNRENDERABLE_BITS = 560_000


def _is_unrenderable(value: Exact) -> bool:
    if not value.is_rational():
        return False
    f = value.as_fraction()
    return abs(f.numerator).bit_length() > _UNRENDERABLE_BITS or abs(f.denominator).bit_length() > _UNRENDERABLE_BITS


def _int_digits(n: int) -> Optional[int]:
    """Number of decimal digits of ``|n|`` without hitting the int->str limit."""
    a = abs(int(n))
    if a == 0:
        return 1
    if a.bit_length() <= _UNRENDERABLE_BITS:
        return len(str(a))
    with num.localcontext() as ctx:
        ctx.prec = 20
        return int(Decimal(a).log10()) + 1


def _describe_huge(value: Exact, prec: int, digits: int) -> dict:
    """Describe a rational too large to print as a decimal string."""
    f = value.as_fraction()
    out: dict = {
        "kind": "exact",
        "exact": None,
        "latex": None,
        "type": "integer" if f.denominator == 1 else "rational",
        "approx": num.fmt_dec(value.approx(min(num.MAX_PREC, max(prec + 10, digits + 10))), digits),
        "numerator_digits": _int_digits(f.numerator),
        "denominator_digits": _int_digits(f.denominator),
        "bit_length": abs(f.numerator).bit_length(),
        "fraction": None,
        "float": None,
        "note": (
            "the exact result is too large to render as a string (limit ~200000 digits); "
            "read `approx`, `numerator_digits`, `denominator_digits` or `bit_length` instead, "
            "or reformulate the question (e.g. compare logarithms)"
        ),
    }
    if f.denominator == 1:
        out["is_prime"] = None
    return out


# --------------------------------------------------------------------------
# eval / verify
# --------------------------------------------------------------------------


def do_eval(expr: str, prec: int = num.DEFAULT_PREC, digits: int = 30, bindings=None) -> dict:
    kind, value = cp.evaluate(expr, prec, bindings)
    out = describe(kind, value, prec, digits)
    out["input"] = expr
    out["exact_available"] = kind == "exact"
    out["precision"] = {"calculation_digits": prec, "printed_digits": digits}
    if kind == "approximate":
        out["note"] = (
            "this result is not exactly representable (the expression leaves the exact field); "
            f"up to {digits} significant digits are shown"
        )
    return out


def do_verify(left: str, right: str, prec: int = num.DEFAULT_PREC, digits: int = 30) -> dict:
    lk, lv = cp.evaluate(left, prec)
    rk, rv = cp.evaluate(right, prec)
    out: dict = {"left": left, "right": right, "left_value": describe(lk, lv, prec, digits, extra=False)}
    out["right_value"] = describe(rk, rv, prec, digits, extra=False)
    if lk == "exact" and rk == "exact":
        diff = lv.sub(rv)
        out["exact_equal"] = diff.is_zero()
        out["difference"] = describe("exact", diff, prec, digits, extra=False)
        out["equal"] = diff.is_zero()
        out["method"] = "exact symbolic comparison"
    else:
        ld = lv.approx(prec + 10) if lk == "exact" else lv
        rd = rv.approx(prec + 10) if rk == "exact" else rv
        delta = abs(ld - rd)
        tol = Decimal(10) ** (-(prec - 5))
        out["equal"] = bool(delta <= tol)
        out["difference"] = {
            "kind": "approximate",
            "approx": num.fmt_dec(ld - rd, digits),
        }
        out["method"] = f"high-precision comparison at {prec} digits (tolerance {tol})"
    return out


# --------------------------------------------------------------------------
# equations
# --------------------------------------------------------------------------


def _poly_eval(poly: Dict[int, Exact], x: Exact) -> Exact:
    result = Exact()
    for degree in sorted(poly, reverse=True):
        result = result.mul(x).add(poly[degree])
    return result


def _poly_to_fractions(poly: Dict[int, Exact]) -> Optional[List[Fraction]]:
    if not all(c.is_rational() for c in poly.values()):
        return None
    degree = max(poly) if poly else 0
    coeffs = [Fraction(0)] * (degree + 1)
    for d, c in poly.items():
        coeffs[d] = c.as_fraction()
    return coeffs


def _synthetic_divide(coeffs: List[Fraction], root: Fraction) -> List[Fraction]:
    """Divide ``coeffs`` (low->high) by ``(x - root)``; returns the quotient."""
    n = len(coeffs) - 1
    out = [Fraction(0)] * n
    carry = coeffs[n]
    out[n - 1] = carry
    for k in range(n - 1, 0, -1):
        carry = coeffs[k] + root * carry
        out[k - 1] = carry
    return out


def _rational_roots(coeffs: List[Fraction]) -> List[Tuple[Fraction, int]]:
    """All rational roots with multiplicity (exact, via the rational root theorem)."""
    coeffs = [c for c in coeffs]
    while coeffs and coeffs[-1] == 0:
        coeffs.pop()
    found: List[Tuple[Fraction, int]] = []
    if len(coeffs) <= 1:
        return found
    while len(coeffs) > 1:
        if coeffs[0] == 0:
            found.append((Fraction(0), 1))
            coeffs = coeffs[1:]
            continue
        lead = coeffs[-1]
        if abs(coeffs[0]) > 10 ** 12 or abs(lead.numerator) > 10 ** 12:
            break
        p_divs = divisors(coeffs[0].numerator)
        q_divs = divisors(lead.numerator)
        if len(p_divs) * len(q_divs) > 20000:
            break
        hit = None
        for p in p_divs:
            for q in q_divs:
                for cand in (Fraction(p, q), Fraction(-p, q)):
                    if sum(c * cand ** i for i, c in enumerate(coeffs)) == 0:
                        hit = cand
                        break
                if hit is not None:
                    break
            if hit is not None:
                break
        if hit is None:
            break
        coeffs = _synthetic_divide(coeffs, hit)
        found.append((hit, 1))
    merged: List[Tuple[Fraction, int]] = []
    for root, mult in found:
        for i, (r, m) in enumerate(merged):
            if r == root:
                merged[i] = (r, m + mult)
                break
        else:
            merged.append((root, mult))
    return merged


def _dk_roots(coeffs: Sequence[Fraction], max_iter: int = 3000) -> List[complex]:
    """Durand-Kerner roots of a polynomial given low->high coefficients."""
    while coeffs and coeffs[-1] == 0:
        coeffs = coeffs[:-1]
    n = len(coeffs) - 1
    if n < 1:
        return []
    c = [complex(x) for x in coeffs]
    lead = c[-1]
    c = [x / lead for x in c]
    roots = [complex(0.4, 0.9) ** k for k in range(n)]
    for _ in range(max_iter):
        max_delta = 0.0
        new_roots = []
        for i, r in enumerate(roots):
            numv = 0j
            for coeff in reversed(c):
                numv = numv * r + coeff
            den = 1 + 0j
            for j, rj in enumerate(roots):
                if i != j:
                    den *= r - rj
            delta = numv / den if den != 0 else 0j
            new_roots.append(r - delta)
            max_delta = max(max_delta, abs(delta))
        roots = new_roots
        if max_delta < 1e-15:
            break
    return roots


def _newton_real(coeffs: Sequence[Fraction], start: Decimal, prec: int) -> Optional[Decimal]:
    """Refine one real root with Newton's method at high precision."""
    wp = prec + 30
    with num.localcontext() as ctx:
        ctx.prec = wp
        x = Decimal(start)
        cf = [Decimal(c.numerator) / Decimal(c.denominator) for c in coeffs]
        dcf = [cf[i] * i for i in range(1, len(cf))]
        for _ in range(200):
            f = Decimal(0)
            for coeff in reversed(cf):
                f = f * x + coeff
            df = Decimal(0)
            for coeff in reversed(dcf):
                df = df * x + coeff
            if df == 0:
                return None
            step = f / df
            x = x - step
            if step.copy_abs() <= abs(x) * Decimal(10) ** (-(prec + 5)):
                return +x
        return +x


def _round_complex(z: complex, digits: int) -> str:
    def fmt(x: float) -> str:
        text = f"{x:.{max(1, digits)}g}"
        if text in ("-0", "-0.0"):
            text = "0"
        return text

    re, im = z.real, z.imag
    if abs(im) <= 1e-12 * max(1.0, abs(re)):
        return fmt(re)
    sign = "+" if im >= 0 else "-"
    return f"{fmt(re)} {sign} {fmt(abs(im))}i"


def _solve_polynomial(poly: Dict[int, Exact], prec: int, digits: int, complex_allowed: bool) -> dict:
    poly = cp.poly_trim(poly)
    degree = cp.poly_degree(poly)
    base = {"method": "exact polynomial", "degree": degree, "variable": "x"}
    if degree < 0:
        return {**base, "solutions": "all numbers", "note": "the equation is an identity (0 = 0)"}
    if degree == 0:
        return {**base, "solutions": [], "note": "the equation is contradictory (no value satisfies it)"}
    solutions: List[dict] = []

    def add_exact(value: Exact, multiplicity: int = 1, note: str = ""):
        item = describe("exact", value, prec, digits)
        item["multiplicity"] = multiplicity
        item["solution_kind"] = "exact"
        item["residual"] = _residual(poly, value, prec, digits)
        if note:
            item["note"] = note
        solutions.append(item)

    def add_numeric(x: Decimal, multiplicity: int = 1, residual: Optional[str] = None):
        out = describe("approximate", x, prec, digits)
        out["multiplicity"] = multiplicity
        out["solution_kind"] = "numeric"
        out["value"] = num.fmt_dec(x, digits)
        out["residual"] = residual if residual is not None else _residual_dec(poly, x, prec, digits)
        out["accuracy"] = f"Newton-polished to {prec} significant digits"
        solutions.append(out)

    if degree == 1:
        c0 = poly.get(0, Exact())
        c1 = poly.get(1, Exact())
        add_exact(c0.neg().div(c1))
        return {**base, "solutions": solutions}

    if degree == 2:
        c0 = poly.get(0, Exact())
        c1 = poly.get(1, Exact())
        c2 = poly.get(2, Exact())
        disc = c1.mul(c1).sub(c2.mul(c0).mul(Exact.from_int(4)))
        s = disc.sign()
        if s == 0:
            add_exact(c1.neg().div(c2.mul(Exact.from_int(2))), multiplicity=2, note="double root")
        elif s > 0:
            root = disc.sqrt_exact()
            two_a = c2.mul(Exact.from_int(2))
            if root is not None:
                add_exact(c1.neg().add(root).div(two_a))
                add_exact(c1.neg().sub(root).div(two_a))
            else:
                # irrational square root of an irrational discriminant:
                # report high-precision numeric roots instead of faking exactness
                roots = _numeric_roots(poly, prec)
                for r in roots:
                    add_numeric(r)
                base["method"] = "polynomial, numeric roots (discriminant has no exact square root)"
        else:
            if complex_allowed:
                real = c1.neg().div(c2.mul(Exact.from_int(2)))
                imag_root = disc.neg().sqrt_exact()
                two_a = c2.mul(Exact.from_int(2))
                if imag_root is not None:
                    imag = imag_root.div(two_a)
                    for sgn in (1, -1):
                        val = imag if sgn > 0 else imag.neg()
                        solutions.append(_complex_exact_item(real, val, prec, digits))
                else:
                    for r in _dk_roots(_poly_to_fractions(poly) or []):
                        solutions.append(_complex_numeric_item(r, prec, digits))
                base["method"] = "exact polynomial (complex roots)"
            else:
                base["note"] = "no real solutions (discriminant is negative); pass --complex to see them"
        return {**base, "solutions": solutions}

    coeffs = _poly_to_fractions(poly)
    if coeffs is None:
        for r in _numeric_roots(poly, prec):
            add_numeric(r)
        base["method"] = "numeric roots (irrational coefficients)"
        return {**base, "solutions": solutions}

    rationals = _rational_roots(coeffs)
    working = list(coeffs)
    for root, mult in rationals:
        for _ in range(mult):
            working = _synthetic_divide(working, root)
        add_exact(Exact.from_fraction(root), multiplicity=mult)
    while len(working) > 1 and working[-1] == 0:
        working.pop()
    rest_degree = len(working) - 1
    if rest_degree == 2:
        sub = {i: Exact.from_fraction(c) for i, c in enumerate(working)}
        sub_result = _solve_polynomial(sub, prec, digits, complex_allowed)
        for item in sub_result["solutions"]:
            item.setdefault("multiplicity", 1)
            solutions.append(item)
    elif rest_degree == 1:
        sub = {i: Exact.from_fraction(c) for i, c in enumerate(working)}
        sub_result = _solve_polynomial(sub, prec, digits, complex_allowed)
        solutions.extend(sub_result["solutions"])
    elif rest_degree > 2:
        base["method"] = "rational roots (exact) + remaining roots (numeric, real roots Newton-polished)"
        solutions.extend(_numeric_solution_items(working, prec, digits))
    return {**base, "solutions": solutions}


def _imag_text(imag: Exact) -> str:
    if imag.is_zero():
        return ""
    text = str(imag)
    if text == "1":
        return "i"
    if text == "-1":
        return "-i"
    return f"{text}*i"


def _complex_exact_item(real: Exact, imag: Exact, prec: int, digits: int) -> dict:
    im_text = _imag_text(imag)
    if real.is_zero():
        value = im_text or "0"
    else:
        sign = "+" if imag.sign() >= 0 else "-"
        value = f"{real} {sign} {_imag_text(imag.abs())}"
    with num.localcontext() as ctx:
        ctx.prec = prec + 25
        re_f = real.to_float()
        im_f = imag.to_float()
    approx = (
        f"{num.fmt_dec(Decimal(repr(re_f)), digits)} "
        f"{'+' if im_f >= 0 else '-'} {num.fmt_dec(Decimal(repr(abs(im_f))), digits)}i"
    )
    return {
        "kind": "exact",
        "solution_kind": "exact-complex",
        "exact": value,
        "value": value,
        "approx": approx,
        "imaginary": True,
        "multiplicity": 1,
    }


def _complex_numeric_item(z: complex, prec: int, digits: int) -> dict:
    shown = max(1, min(int(digits), 17))
    return {
        "kind": "approximate",
        "solution_kind": "numeric-complex" if abs(z.imag) > 1e-9 else "numeric",
        "value": _round_complex(z, shown),
        "approx": _round_complex(z, shown),
        "residual": None,
        "multiplicity": 1,
        "accuracy": "double precision (~15 significant digits)",
    }


def _residual_coeffs_dec(coeffs: Sequence[Fraction], x: Decimal, prec: int, digits: int) -> str:
    with num.localcontext() as ctx:
        ctx.prec = prec + 25
        cf = [Decimal(c.numerator) / Decimal(c.denominator) for c in coeffs]
        total = Decimal(0)
        for coeff in reversed(cf):
            total = total * x + coeff
        return num.fmt_dec(total, min(digits, 12))


def _numeric_solution_items(coeffs: Sequence[Fraction], prec: int, digits: int) -> List[dict]:
    """Turn Durand-Kerner roots into reported solutions.

    Real roots are polished with Newton's method in Decimal arithmetic, so they
    really do carry ``prec`` correct digits.  Complex roots stay in double
    precision and say so, instead of printing meaningless extra digits.
    """
    items: List[dict] = []
    for z in _dk_roots(coeffs):
        is_real = abs(z.imag) <= 1e-8 * max(1.0, abs(z.real))
        if is_real:
            refined = _newton_real(coeffs, Decimal(repr(z.real)), prec)
            if refined is None or not refined.is_finite():
                refined = Decimal(repr(z.real))
                accuracy = "double precision (~15 significant digits)"
            else:
                accuracy = f"Newton-polished to {prec} significant digits"
            item = describe("approximate", refined, prec, digits)
            item["solution_kind"] = "numeric"
            item["value"] = num.fmt_dec(refined, digits)
            item["residual"] = _residual_coeffs_dec(coeffs, refined, prec, digits)
            item["accuracy"] = accuracy
        else:
            item = _complex_numeric_item(z, prec, digits)
        item["multiplicity"] = 1
        items.append(item)
    items.sort(key=lambda item: (item.get("solution_kind") != "numeric", item.get("value", "")))
    return items


def _residual(poly: Dict[int, Exact], x: Exact, prec: int, digits: int) -> str:
    value = _poly_eval(poly, x)
    if value.is_zero():
        return "0"
    return num.fmt_dec(value.approx(prec + 10), min(digits, 12))


def _residual_dec(poly: Dict[int, Exact], x: Decimal, prec: int, digits: int) -> str:
    with num.localcontext() as ctx:
        ctx.prec = prec + 25
        total = Decimal(0)
        for degree in sorted(poly, reverse=True):
            coeff = poly[degree]
            c = Decimal(coeff.as_fraction().numerator) / Decimal(coeff.as_fraction().denominator) if coeff.is_rational() else coeff.approx(prec + 10)
            total = total * x + c
        return num.fmt_dec(total, min(digits, 12))


def _numeric_roots(poly: Dict[int, Exact], prec: int) -> List[Decimal]:
    coeffs = _poly_to_fractions(poly)
    if coeffs is None:
        coeffs = [
            poly[d].as_fraction() if poly[d].is_rational() else Fraction(poly[d].approx(prec + 5))
            for d in range(max(poly) + 1)
        ]
    out: List[Decimal] = []
    for z in _dk_roots(coeffs):
        if abs(z.imag) > 1e-8 * max(1.0, abs(z.real)):
            continue
        refined = _newton_real(coeffs, Decimal(repr(z.real)), prec)
        if refined is not None and refined.is_finite():
            out.append(refined)
        else:
            out.append(Decimal(repr(z.real)))
    out.sort()
    deduped: List[Decimal] = []
    for value in out:
        if not deduped or abs(value - deduped[-1]) > abs(value) * Decimal(10) ** (-(min(prec, 25) // 2)) + Decimal(
            10
        ) ** (-(min(prec, 25) // 2)):
            deduped.append(value)
    return deduped


def do_solve(
    text: str,
    var: Optional[str] = None,
    prec: int = num.DEFAULT_PREC,
    digits: int = 30,
    complex_allowed: bool = False,
    numeric: bool = False,
    scan_range: Tuple[float, float] = (-50.0, 50.0),
    samples: int = 4000,
) -> dict:
    left, right, auto_var = cp.parse_equation(text)
    name = var or auto_var
    poly = None
    denominators: Optional[Dict[int, Exact]] = None
    if not numeric:
        pl = cp.to_polynomial(left, name)
        pr = cp.to_polynomial(right, name)
        if pl is not None and pr is not None:
            poly = cp._poly_add(pl, cp._poly_scale(pr, Exact.from_int(-1)))
        else:
            fl = cp.to_rational_function(left, name)
            fr = cp.to_rational_function(right, name)
            if fl is not None and fr is not None:
                num_poly = cp._poly_add(
                    cp._poly_mul(fl[0], fr[1]), cp._poly_scale(cp._poly_mul(fr[0], fl[1]), Exact.from_int(-1))
                )
                den_poly = cp._poly_mul(fl[1], fr[1])
                if cp.poly_degree(den_poly) > 0:
                    poly = num_poly
                    denominators = den_poly
    if poly is not None:
        result = _solve_polynomial(poly, prec, digits, complex_allowed)
        result["variable"] = name
        result["equation"] = text
        if denominators is not None and isinstance(result["solutions"], list):
            kept = []
            excluded = []
            for solution in result["solutions"]:
                if isinstance(solution, dict) and solution.get("kind") == "exact" and solution.get("fraction"):
                    value = Exact.from_fraction(_value_from_text(solution["fraction"]))
                    if _poly_eval(denominators, value).is_zero():
                        excluded.append(solution.get("exact"))
                        continue
                kept.append(solution)
            result["solutions"] = kept
            result["method"] = (result.get("method") or "") + " (rational equation: denominators cross-multiplied)"
            result["excluded_extraneous_roots"] = excluded
            if excluded:
                result["note"] = (
                    "cross-multiplying can create extraneous roots; the listed values make a "
                    "denominator zero and were removed"
                )
        result["exact_solution_count"] = sum(
            1 for s in result["solutions"] if isinstance(s, dict) and s.get("kind") == "exact"
        )
        result["numeric_solution_count"] = sum(
            1 for s in result["solutions"] if isinstance(s, dict) and s.get("kind") == "approximate"
        )
        return result
    return _solve_numeric_equation(text, left, right, name, prec, digits, scan_range, samples, complex_allowed)


def _solve_numeric_equation(text, left, right, name, prec, digits, scan_range, samples, complex_allowed=False) -> dict:
    lo, hi = float(scan_range[0]), float(scan_range[1])
    if not lo < hi:
        raise CalcError("--range requires lo < hi")
    if samples < 2:
        raise CalcError("--samples must be at least 2")

    def f(x: Decimal) -> Decimal:
        try:
            with num.localcontext() as ctx:
                ctx.prec = prec + 25
                return cp.eval_numeric(left, prec + 10, {name: Exact.from_fraction(Fraction(x))}) - cp.eval_numeric(
                    right, prec + 10, {name: Exact.from_fraction(Fraction(x))}
                )
        except (CalcError, ArithmeticError, ZeroDivisionError):
            return Decimal("NaN")

    roots: List[dict] = []
    step = (hi - lo) / samples
    prev_x = Decimal(repr(lo))
    prev_y = f(prev_x)
    for i in range(1, samples + 1):
        x = Decimal(repr(lo + step * i))
        y = f(x)
        if y.is_nan() or prev_y.is_nan():
            prev_x, prev_y = x, y
            continue
        if y == 0:
            cand = x
        elif (y > 0) != (prev_y > 0):
            # bisection
            a, b, fa = prev_x, x, prev_y
            for _ in range(200):
                mid = (a + b) / 2
                fm = f(mid)
                if fm.is_nan():
                    break
                if fm == 0:
                    a = b = mid
                    break
                if (fm > 0) != (fa > 0):
                    b = mid
                else:
                    a, fa = mid, fm
                if abs(b - a) <= abs(b) * Decimal(10) ** (-(prec + 5)) + Decimal(10) ** (-(prec + 5)):
                    break
            cand = (a + b) / 2
        else:
            prev_x, prev_y = x, y
            continue
        value = f(cand)
        tolerance = Decimal(10) ** (-(min(prec, 25) // 2 + 1))
        if value.is_nan() or abs(value) > tolerance:
            prev_x, prev_y = x, y
            continue
        if roots and abs(cand - Decimal(roots[-1]["_raw"])) < Decimal(10) ** (-(min(prec, 20) // 2)):
            prev_x, prev_y = x, y
            continue
        item = describe("approximate", cand, prec, digits)
        item["solution_kind"] = "numeric"
        item["value"] = num.fmt_dec(cand, digits)
        item["residual"] = num.fmt_dec(value, min(digits, 12))
        item["multiplicity"] = 1
        item["accuracy"] = f"bisection to {prec} significant digits"
        item["_raw"] = str(cand)
        roots.append(item)
        prev_x, prev_y = x, y
    for item in roots:
        item.pop("_raw", None)
    note = (
        "transcendental or non-polynomial equation: roots are numeric approximations "
        "within the scanned interval only"
    )
    if complex_allowed:
        note += "; --complex does not apply here because the scan locates real sign changes only"
    return {
        "equation": text,
        "variable": name,
        "method": f"numeric search over [{lo}, {hi}] with {samples} samples + bisection",
        "degree": None,
        "solutions": roots,
        "numeric_solution_count": len(roots),
        "exact_solution_count": 0,
        "note": note,
    }


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------


def _percentile(sorted_vals: List[Fraction], p: Fraction) -> Fraction:
    if not sorted_vals:
        raise CalcError("no data")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = p * (len(sorted_vals) - 1)
    lo = idx.numerator // idx.denominator
    frac = idx - lo
    if frac == 0:
        return sorted_vals[lo]
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def do_stats(values: Sequence[str], prec: int = num.DEFAULT_PREC, digits: int = 30) -> dict:
    if not values:
        raise CalcError("no data supplied")
    data: List[Fraction] = []
    for raw in values:
        try:
            data.append(_value_from_text(str(raw)))
        except ValueError as exc:
            raise CalcError(f"could not read {raw!r} as a number: {exc}")
    n = len(data)
    ordered = sorted(data)
    total = sum(data, Fraction(0))
    mean = total / n
    median = _percentile(ordered, Fraction(1, 2))

    counts: Dict[Fraction, int] = {}
    for v in data:
        counts[v] = counts.get(v, 0) + 1
    best = max(counts.values())
    modes = sorted(v for v, c in counts.items() if c == best) if best > 1 else []

    def variance(sample: bool) -> Optional[Fraction]:
        if sample and n < 2:
            return None
        mu = mean
        ss = sum((v - mu) ** 2 for v in data)
        return ss / (n - 1 if sample else n)

    def exact_or_approx_root(var: Optional[Fraction]):
        if var is None:
            return None
        root = Exact.sqrt_of_rational(var)
        if root is not None:
            return describe("exact", root, prec, digits, extra=False)
        with num.localcontext() as ctx:
            ctx.prec = prec + 25
            d = (Decimal(var.numerator) / Decimal(var.denominator)).sqrt()
        return describe("approximate", d, prec, digits, extra=False)

    var_pop = variance(False)
    var_sample = variance(True)

    def maybe(value: Optional[Fraction], kind: str = "exact"):
        if value is None:
            return None
        return describe(kind, Exact.from_fraction(value) if kind == "exact" else value, prec, digits, extra=False)

    geometric = None
    if all(v > 0 for v in data):
        product = Fraction(1)
        for v in data:
            product *= v
        root = Exact.nth_root_of_rational(product, n)
        if root is not None:
            geometric = describe("exact", root, prec, digits, extra=False)
        else:
            with num.localcontext() as ctx:
                ctx.prec = prec + 25
                arg = Decimal(product.numerator) / Decimal(product.denominator)
                geometric = describe("approximate", num.root_dec(arg, n, prec), prec, digits, extra=False)
    harmonic = None
    if all(v != 0 for v in data):
        reciprocal_sum = sum(Fraction(1, 1) / v for v in data)
        if reciprocal_sum != 0:
            harmonic = describe("exact", Exact.from_fraction(Fraction(n) / reciprocal_sum), prec, digits, extra=False)

    out = {
        "count": n,
        "sum": describe("exact", Exact.from_fraction(total), prec, digits, extra=False),
        "mean": describe("exact", Exact.from_fraction(mean), prec, digits),
        "median": describe("exact", Exact.from_fraction(median), prec, digits),
        "mode": [format_fraction(m) for m in modes],
        "min": describe("exact", Exact.from_fraction(ordered[0]), prec, digits, extra=False),
        "max": describe("exact", Exact.from_fraction(ordered[-1]), prec, digits, extra=False),
        "range": describe("exact", Exact.from_fraction(ordered[-1] - ordered[0]), prec, digits, extra=False),
        "q1": describe("exact", Exact.from_fraction(_percentile(ordered, Fraction(1, 4))), prec, digits, extra=False),
        "q3": describe("exact", Exact.from_fraction(_percentile(ordered, Fraction(3, 4))), prec, digits, extra=False),
        "iqr": describe(
            "exact",
            Exact.from_fraction(_percentile(ordered, Fraction(3, 4)) - _percentile(ordered, Fraction(1, 4))),
            prec,
            digits,
            extra=False,
        ),
        "variance_population": maybe(var_pop),
        "variance_sample": maybe(var_sample),
        "stddev_population": exact_or_approx_root(var_pop),
        "stddev_sample": exact_or_approx_root(var_sample),
        "sum_of_squares": describe("exact", Exact.from_fraction(sum(v * v for v in data)), prec, digits, extra=False),
        "geometric_mean": geometric,
        "harmonic_mean": harmonic,
        "quantile_method": "linear interpolation between order statistics: index = p*(n-1)",
        "sorted": [format_fraction(v) for v in ordered],
    }
    out["variance_population_exact"] = format_fraction(var_pop) if var_pop is not None else None
    out["variance_sample_exact"] = format_fraction(var_sample) if var_sample is not None else None
    return out


# --------------------------------------------------------------------------
# base conversion
# --------------------------------------------------------------------------

_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _int_to_base(n: int, base: int) -> str:
    if n == 0:
        return "0"
    sign = "-" if n < 0 else ""
    n = abs(n)
    out = []
    while n:
        n, r = divmod(n, base)
        out.append(_DIGITS[r])
    return sign + "".join(reversed(out))


def _parse_in_base(text: str, base: int) -> Fraction:
    s = str(text).strip().replace("_", "").replace(" ", "")
    if not s:
        raise CalcError("empty number")
    neg = s.startswith("-")
    if s[0] in "+-":
        s = s[1:]
    if "(" in s:
        if not s.endswith(")"):
            raise CalcError(f"unbalanced recurring notation in {text!r}")
        head, _, rest = s.partition("(")
        cycle = rest[:-1]
        if not cycle:
            raise CalcError(f"empty recurring block in {text!r}")
        prefix_len = len(head.split(".", 1)[1]) if "." in head else 0
        allowed = set(_DIGITS[:base])
        for ch in cycle:
            if ch.lower() not in allowed:
                raise CalcError(f"digit {ch!r} is not valid in base {base}")
        value = _parse_in_base(head, base)
        value += Fraction(int(cycle, base), (base ** len(cycle) - 1) * base ** prefix_len)
        return -value if neg else value
    if "." in s:
        int_part, frac_part = s.split(".", 1)
    else:
        int_part, frac_part = s, ""
    if not int_part:
        int_part = "0"
    allowed = set(_DIGITS[:base])
    for ch in int_part + frac_part:
        if ch.lower() not in allowed:
            raise CalcError(f"digit {ch!r} is not valid in base {base}")
    value = Fraction(int(int_part, base)) if int_part else Fraction(0)
    if frac_part:
        value += Fraction(int(frac_part, base), base ** len(frac_part))
    return -value if neg else value


def _frac_to_base(f: Fraction, base: int, max_digits: int = 40) -> dict:
    """Convert the fractional part ``0 <= f < 1`` to ``base`` with cycle detection."""
    if f == 0:
        return {"text": "", "kind": "terminating", "exact": True}
    seen: Dict[Fraction, int] = {}
    digits: List[str] = []
    r = f
    period_start = None
    while r != 0 and len(digits) < max_digits:
        if r in seen:
            period_start = seen[r]
            break
        seen[r] = len(digits)
        r *= base
        d = r.numerator // r.denominator
        digits.append(_DIGITS[d])
        r -= d
    if r == 0:
        return {"text": "".join(digits), "kind": "terminating", "exact": True}
    if period_start is not None:
        return {
            "text": "".join(digits[:period_start]) + "(" + "".join(digits[period_start:]) + ")",
            "kind": "recurring",
            "exact": True,
        }
    return {"text": "".join(digits), "kind": "truncated", "exact": False}


def _detect_base(text: str) -> Tuple[str, int]:
    s = str(text).strip().lower()
    if s.startswith("0x"):
        return s[2:], 16
    if s.startswith("0b"):
        return s[2:], 2
    if s.startswith("0o"):
        return s[2:], 8
    return str(text).strip(), 10


def do_base(
    value: str,
    from_base: Optional[int] = None,
    to_base: int = 16,
    digits: int = 40,
    prec: int = num.DEFAULT_PREC,
) -> dict:
    if from_base is None:
        text, from_base = _detect_base(value)
    else:
        text = str(value).strip()
    if not (2 <= from_base <= 36):
        raise CalcError("--from must be between 2 and 36")
    if not (2 <= to_base <= 36):
        raise CalcError("--to must be between 2 and 36")
    if "/" in text:
        raise CalcError(
            "base conversion needs a plain numeral in the source base; "
            "use `decimal`/`fraction` (or `eval`) for rationals and fractions"
        )
    number = _parse_in_base(text, from_base)
    sign = "-" if number < 0 else ""
    a = abs(number)
    whole = a.numerator // a.denominator
    frac = a - whole
    int_text = _int_to_base(whole, to_base)
    frac_info = _frac_to_base(frac, to_base, max(1, int(digits)))
    body = int_text + ("." + frac_info["text"] if frac_info["text"] else "")
    result_text = sign + body
    # round-trip verification
    back = _parse_in_base(result_text, to_base)
    return {
        "input": str(value),
        "from_base": from_base,
        "to_base": to_base,
        "result": result_text,
        "exact": bool(frac_info["exact"]),
        "integer_part": sign + int_text,
        "fractional_digits": frac_info["kind"],
        "digits_emitted": len(frac_info["text"].replace("(", "").replace(")", "")),
        "decimal_value": fraction_to_decimal_string(number, max(30, digits))["text"],
        "fraction": format_fraction(number),
        "round_trip_value": format_fraction(back),
        "note": None
        if frac_info["exact"]
        else f"the expansion does not terminate in base {to_base}; the first {digits} digits are shown",
    }


# --------------------------------------------------------------------------
# fractions / decimals
# --------------------------------------------------------------------------


def do_fraction(text: str, prec: int = num.DEFAULT_PREC, digits: int = 30) -> dict:
    try:
        value = _value_from_text(text)
    except ValueError as exc:
        raise CalcError(f"could not read {text!r} as a number: {exc}")
    out = describe("exact", Exact.from_fraction(value), prec, digits)
    out["input"] = text
    out["reduced_fraction"] = format_fraction(value)
    out["mixed"] = mixed_number(value)
    if value.denominator != 1:
        out["numerator"] = value.numerator
        out["denominator"] = value.denominator
        out["numerator_factors"] = _factor_string(abs(value.numerator))
        out["denominator_factors"] = _factor_string(abs(value.denominator))
        out["is_terminating_decimal"] = _terminates_in_base10(value.denominator)
    return out


def _factor_string(n: int) -> str:
    if n <= 1:
        return str(n)
    fact = factorize(n)
    return " * ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(fact.items()))


def _terminates_in_base10(den: int) -> bool:
    for p in (2, 5):
        while den % p == 0:
            den //= p
    return den == 1


def do_decimal(text: str, digits: int = 50, prec: int = num.DEFAULT_PREC) -> dict:
    try:
        value = _value_from_text(text)
    except ValueError as exc:
        raise CalcError(f"could not read {text!r} as a number: {exc}")
    info = fraction_to_decimal_string(value, max(1, int(digits)))
    return {
        "input": text,
        "fraction": format_fraction(value),
        "decimal": info["text"],
        "kind": info["kind"],
        "exact": info["exact"],
        "digits_emitted": info["digits"],
        "recurring_notation": "(...) marks the repeating block"
        if info["kind"] == "recurring"
        else None,
    }


# --------------------------------------------------------------------------
# number theory
# --------------------------------------------------------------------------


def do_factor(text: str, prec: int = num.DEFAULT_PREC, digits: int = 30, max_steps: int = 2000000) -> dict:
    try:
        value = _value_from_text(text)
    except ValueError as exc:
        raise CalcError(f"could not read {text!r} as an integer: {exc}")
    if value.denominator != 1:
        raise CalcError("factor requires an integer")
    n = value.numerator
    if n == 0:
        raise CalcError("0 has no prime factorisation")
    if abs(n) == 1:
        return {
            "input": str(text),
            "value": n,
            "sign": -1 if n < 0 else 1,
            "value_abs": 1,
            "factorization": "1 (no prime factors)",
            "factors": {},
            "prime_factors": [],
            "is_prime": False,
            "is_perfect_square": True,
            "square_root": 1,
            "divisor_count": 1,
            "divisor_sum": 1,
            "euler_phi": 1,
            "divisors": [1],
        }
    base = {
        "input": str(text),
        "value": n,
        "sign": -1 if n < 0 else 1,
        "value_abs": abs(n),
        "is_prime": is_prime(abs(n)) if abs(n) > 1 else False,
        "is_perfect_square": _is_square(abs(n)),
    }
    try:
        fact = factorize(abs(n), max_steps)
    except FactorizationError as exc:
        return {
            **base,
            "factorization": None,
            "factors": None,
            "prime_factors": None,
            "divisor_count": None,
            "divisor_sum": None,
            "euler_phi": None,
            "partial": False,
            "note": str(exc),
        }
    out = {
        **base,
        "factorization": " * ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(fact.items())),
        "factors": {str(p): e for p, e in sorted(fact.items())},
        "prime_factors": [p for p in sorted(fact)],
        "is_prime": abs(n) > 1 and len(fact) == 1 and list(fact.values())[0] == 1,
        "divisor_count": 1,
        "divisor_sum": 1,
        "euler_phi": 1,
    }
    for p, e in fact.items():
        out["divisor_count"] *= e + 1
        out["divisor_sum"] *= (p ** (e + 1) - 1) // (p - 1)
        out["euler_phi"] *= p ** (e - 1) * (p - 1)
    if out["is_perfect_square"]:
        out["square_root"] = int(math.isqrt(abs(n)))
    divs = divisors(abs(n))
    if len(divs) <= 100:
        out["divisors"] = divs
    else:
        out["divisors"] = f"{len(divs)} divisors (omitted: too many to list)"
    return out


def _is_square(n: int) -> bool:
    if n < 0:
        return False
    r = math.isqrt(n)
    return r * r == n


def do_primes(lo: str, hi: str, limit: int = 2000) -> dict:
    try:
        a, b = int(lo), int(hi)
    except ValueError:
        raise CalcError("primes needs two integers: primes <lo> <hi>")
    if b < a:
        raise CalcError("primes requires lo <= hi")
    found: List[int] = []
    n = max(2, a)
    while n <= b:
        if is_prime(n):
            found.append(n)
            if len(found) >= limit:
                break
        n += 1
    return {
        "range": [a, b],
        "count": len(found),
        "primes": found,
        "truncated": len(found) >= limit,
        "note": f"capped at {limit} primes" if len(found) >= limit else None,
    }


# --------------------------------------------------------------------------
# unit conversion
# --------------------------------------------------------------------------

F = Fraction
UNITS: Dict[str, Tuple[str, Fraction]] = {}


def _register(category: str, factor, *names: str) -> None:
    for name in names:
        UNITS[name] = (category, F(factor))


# length, base metre
_register("length", 1, "m", "meter", "metre", "meters", "metres")
_register("length", F(1000), "km", "kilometer", "kilometre", "kilometers")
_register("length", F(1, 100), "cm", "centimeter", "centimetre")
_register("length", F(1, 1000), "mm", "millimeter", "millimetre")
_register("length", F(1, 10 ** 6), "um", "micrometer", "micron")
_register("length", F(1, 10 ** 9), "nm", "nanometer")
_register("length", F(254, 10000), "in", "inch", "inches")
_register("length", F(3048, 10000), "ft", "foot", "feet")
_register("length", F(9144, 10000), "yd", "yard", "yards")
_register("length", F(1609344, 1000), "mi", "mile", "miles")
_register("length", F(1852), "nmi", "nauticalmile")
# mass, base kilogram
_register("mass", 1, "kg", "kilogram", "kilograms")
_register("mass", F(1, 1000), "g", "gram", "grams")
_register("mass", F(1, 10 ** 6), "mg", "milligram")
_register("mass", F(1, 10 ** 9), "ug", "microgram")
_register("mass", F(1000), "t", "tonne", "tonnes", "metricton")
_register("mass", F(45359237, 10 ** 8), "lb", "lbs", "pound", "pounds")
_register("mass", F(45359237, 16 * 10 ** 8), "oz", "ounce", "ounces")
# time, base second
_register("time", 1, "s", "sec", "second", "seconds")
_register("time", 60, "min", "minute", "minutes")
_register("time", 3600, "h", "hr", "hour", "hours")
_register("time", 86400, "day", "days")
_register("time", 604800, "week", "weeks")
_register("time", 31557600, "year", "years", "julianyear")
# area, base square metre
_register("area", 1, "m2", "sqm")
_register("area", 10 ** 6, "km2", "sqkm")
_register("area", F(1, 10 ** 4), "cm2", "sqcm")
_register("area", F(3048 ** 2, 10 ** 8), "ft2", "sqft")
_register("area", 10 ** 4, "ha", "hectare", "hectares")
_register("area", F(40468564224, 10 ** 7), "acre", "acres")
# volume, base cubic metre
_register("volume", 1, "m3", "cubicmeter")
_register("volume", F(1, 1000), "l", "liter", "litre", "liters", "litres")
_register("volume", F(1, 10 ** 6), "ml", "milliliter", "millilitre")
_register("volume", F(1, 10 ** 6), "cm3", "cc")
_register("volume", F(3785411784, 10 ** 12), "gal", "gallon", "usgallon")
_register("volume", F(946352946, 10 ** 12), "qt", "quart")
_register("volume", F(2365882365, 10 ** 13), "cup", "cups")
_register("volume", F(473176473, 10 ** 12), "pt", "pint")
# speed, base metre per second
_register("speed", 1, "mps", "m/s")
_register("speed", F(1000, 3600), "kph", "kmh", "km/h")
_register("speed", F(1609344, 3600 * 1000), "mph", "mi/h")
_register("speed", F(1852, 3600), "knot", "knots", "kn")
_register("speed", F(1, 1000), "mmps")
# data, base bit
_register("data", 1, "bit", "bits", "b")
_register("data", 8, "B", "byte", "bytes")
_register("data", 8000, "kb", "kbit")
_register("data", 8 * 10 ** 6, "mb", "mbit")
_register("data", 8 * 10 ** 9, "gb", "gbit")
_register("data", 8 * 10 ** 12, "tb", "tbit")
_register("data", 8 * 1024, "kib", "KiB")
_register("data", 8 * 1024 ** 2, "mib", "MiB")
_register("data", 8 * 1024 ** 3, "gib", "GiB")
# energy, base joule
_register("energy", 1, "j", "joule", "joules")
_register("energy", 1000, "kj", "kilojoule")
_register("energy", F(4184, 1000), "cal", "calorie", "calories")
_register("energy", 4184, "kcal", "kilocalorie")
_register("energy", 3600, "wh", "watthour")
_register("energy", 3600000, "kwh", "kilowatthour")
# pressure, base pascal
_register("pressure", 1, "pa", "pascal", "pascals")
_register("pressure", 1000, "kpa", "kilopascal")
_register("pressure", 10 ** 6, "mpa", "megapascal")
_register("pressure", 10 ** 5, "bar", "bars")
_register("pressure", 101325, "atm", "atmosphere")
# mmHg is defined as 133.322387415 Pa exactly; torr is 1/760 atm exactly
_register("pressure", F(133322387415, 10 ** 9), "mmhg")
_register("pressure", F(101325, 760), "torr")
# 1 psi = 1 lbf/in^2 = (0.45359237*9.80665 N)/(0.0254 m)^2 exactly
_register("pressure", F(44482216152605, 6451600000), "psi")
# angle, base degree (rad handled separately because it involves pi)
_register("angle", 1, "deg", "degree", "degrees")
_register("angle", F(9, 10), "grad", "gradian", "gon")
_register("angle", 360, "turn", "turns", "rev")
# temperature is affine, handled by name
TEMPERATURES = ("c", "celsius", "f", "fahrenheit", "k", "kelvin")
ALL_UNITS = sorted(set(UNITS) | set(TEMPERATURES) | {"rad", "radian", "radians"})


def _unit_category(name: str) -> Tuple[str, str]:
    key = str(name).strip()
    if key in UNITS:
        return UNITS[key][0], key
    if key in TEMPERATURES:
        return "temperature", key
    if key in ("rad", "radian", "radians"):
        return "angle", "rad"
    lowered = key.lower()
    if lowered in UNITS:
        return UNITS[lowered][0], lowered
    if lowered in TEMPERATURES:
        return "temperature", lowered
    if lowered in ("rad", "radian", "radians"):
        return "angle", "rad"
    raise CalcError(f"unknown unit {name!r}; use `units --list` to see all units")


def _to_celsius(value: Fraction, unit: str) -> Fraction:
    if unit in ("c", "celsius"):
        return value
    if unit in ("f", "fahrenheit"):
        return (value - 32) * F(5, 9)
    if unit in ("k", "kelvin"):
        return value - F(27315, 100)
    raise CalcError(f"unknown temperature unit {unit!r}")


def _from_celsius(value: Fraction, unit: str) -> Fraction:
    if unit in ("c", "celsius"):
        return value
    if unit in ("f", "fahrenheit"):
        return value * F(9, 5) + 32
    if unit in ("k", "kelvin"):
        return value + F(27315, 100)
    raise CalcError(f"unknown temperature unit {unit!r}")


def units_listing() -> List[dict]:
    groups: Dict[str, List[str]] = {}
    for name, (category, _factor) in sorted(UNITS.items()):
        groups.setdefault(category, []).append(name)
    for name in TEMPERATURES:
        groups.setdefault("temperature", []).append(name)
    groups.setdefault("angle", []).append("rad")
    return [
        {"category": category, "units": sorted(set(names))}
        for category, names in sorted(groups.items())
    ]


def do_units(
    value_text: str,
    from_unit: str,
    to_unit: str,
    prec: int = num.DEFAULT_PREC,
    digits: int = 30,
) -> dict:
    try:
        value = _value_from_text(value_text)
    except ValueError as exc:
        raise CalcError(f"could not read {value_text!r} as a number: {exc}")
    cat_a, key_a = _unit_category(from_unit)
    cat_b, key_b = _unit_category(to_unit)
    if cat_a != cat_b:
        raise CalcError(f"cannot convert {from_unit!r} ({cat_a}) to {to_unit!r} ({cat_b})")
    factor = None
    if cat_a == "temperature":
        result = _from_celsius(_to_celsius(value, key_a), key_b)
        payload = describe("exact", Exact.from_fraction(result), prec, digits)
    elif cat_a == "angle":
        if key_a == "rad":
            with num.localcontext() as ctx:
                ctx.prec = prec + 25
                degrees = (
                    Decimal(value.numerator) / Decimal(value.denominator)
                ) * Decimal(180) / num.get_pi(prec + 15)
        else:
            degrees = value * UNITS[key_a][1]
        if key_b == "rad":
            with num.localcontext() as ctx:
                ctx.prec = prec + 25
                deg_dec = (
                    degrees
                    if isinstance(degrees, Decimal)
                    else Decimal(degrees.numerator) / Decimal(degrees.denominator)
                )
                radians = deg_dec * num.get_pi(prec + 15) / Decimal(180)
            payload = describe("approximate", radians, prec, digits)
        elif isinstance(degrees, Fraction):
            payload = describe("exact", Exact.from_fraction(degrees / UNITS[key_b][1]), prec, digits)
            factor = UNITS[key_a][1] / UNITS[key_b][1]
        else:
            with num.localcontext() as ctx:
                ctx.prec = prec + 25
                out = degrees * Decimal(UNITS[key_b][1].numerator) / Decimal(UNITS[key_b][1].denominator)
            payload = describe("approximate", out, prec, digits)
    else:
        factor_a = UNITS[key_a][1]
        factor_b = UNITS[key_b][1]
        factor = factor_a / factor_b
        payload = describe("exact", Exact.from_fraction(value * factor), prec, digits)
    payload.update(
        {
            "input": str(value_text),
            "from": from_unit,
            "to": to_unit,
            "category": cat_a,
            "conversion_factor": format_fraction(factor) if factor is not None else None,
        }
    )
    payload["result"] = payload.get("exact") if payload.get("exact") is not None else payload.get("approx")
    if cat_a == "temperature":
        payload["conversion_formula"] = _temperature_formula(key_a, key_b)
    elif cat_a == "angle" and (key_a == "rad" or key_b == "rad"):
        payload["note"] = "radian conversions involve pi, so the result is approximate"
    return payload


def _temperature_formula(key_a: str, key_b: str) -> str:
    names = {
        "c": "Celsius",
        "celsius": "Celsius",
        "f": "Fahrenheit",
        "fahrenheit": "Fahrenheit",
        "k": "Kelvin",
        "kelvin": "Kelvin",
    }
    a, b = names.get(key_a, key_a), names.get(key_b, key_b)
    if a == b:
        return "identity"
    table = {
        ("Celsius", "Fahrenheit"): "x * 9/5 + 32",
        ("Fahrenheit", "Celsius"): "(x - 32) * 5/9",
        ("Celsius", "Kelvin"): "x + 273.15",
        ("Kelvin", "Celsius"): "x - 273.15",
        ("Fahrenheit", "Kelvin"): "(x - 32) * 5/9 + 273.15",
        ("Kelvin", "Fahrenheit"): "(x - 273.15) * 9/5 + 32",
    }
    return table.get((a, b), "affine conversion")


# --------------------------------------------------------------------------
# small helpers used by the CLI
# --------------------------------------------------------------------------


def do_round(text: str, digits: int = 0, prec: int = num.DEFAULT_PREC) -> dict:
    """Round an expression to ``digits`` decimal places (half away from zero)."""
    kind, value = cp.evaluate(text, prec)
    if kind == "exact" and value.is_rational():
        node = ("call", "round", [("num", value.as_fraction()), ("num", Fraction(int(digits)))])
        rounded = cp.eval_exact(node)
        if rounded is not None:
            return describe("exact", rounded, prec, max(digits + 12, 12))
    dec = value.approx(prec + 10) if kind == "exact" else value
    return describe("approximate", num.round_dec(dec, digits), prec, max(digits + 12, 12))
