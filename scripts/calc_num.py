"""High-precision numeric engine (pure standard library).

The :mod:`decimal` module is used with a context precision the caller chooses,
so ``calc`` can print 50 correct digits of ``sqrt(2)``, ``pi``, ``exp(1)`` or
``sin(1)`` without any third-party dependency.  Constants are computed at
runtime (Machin's formula for pi, :meth:`Decimal.exp` for e) instead of being
hard-coded, so accuracy scales with the requested precision.
"""

from __future__ import annotations

from decimal import (
    Decimal,
    DivisionByZero,
    InvalidOperation,
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    localcontext,
)

__all__ = [
    "Decimal",
    "get_pi",
    "get_e",
    "get_tau",
    "fmt_dec",
    "pow_dec",
    "root_dec",
    "exp_dec",
    "ln_dec",
    "log_dec",
    "log10_dec",
    "log2_dec",
    "sin_dec",
    "cos_dec",
    "tan_dec",
    "asin_dec",
    "acos_dec",
    "atan_dec",
    "sinh_dec",
    "cosh_dec",
    "tanh_dec",
    "asinh_dec",
    "acosh_dec",
    "atanh_dec",
    "floor_dec",
    "ceil_dec",
    "round_dec",
    "trunc_dec",
    "gamma_dec",
]

MAX_PREC = 2000
DEFAULT_PREC = 30

_PI_CACHE: dict = {}


def _clamp_prec(prec: int) -> int:
    try:
        p = int(prec)
    except (TypeError, ValueError):
        p = DEFAULT_PREC
    return max(1, min(MAX_PREC, p))


def _atan_small(x: Decimal, prec: int) -> Decimal:
    """Taylor series for atan, valid for small ``|x|``."""
    with localcontext() as ctx:
        ctx.prec = prec + 12
        total = Decimal(0)
        x2 = x * x
        power = x
        k = 0
        while True:
            term = power / (2 * k + 1)
            total += term if k % 2 == 0 else -term
            if term == 0 or term.adjusted() < -(prec + 6):
                break
            power *= x2
            k += 1
        return +total


def get_pi(prec: int = DEFAULT_PREC) -> Decimal:
    """pi to ``prec`` significant digits (Machin's formula).

    Guard digits are generous (40 extra) so the last requested digit is
    correctly rounded rather than off by one ulp.
    """
    prec = _clamp_prec(prec)
    hit = _PI_CACHE.get(prec)
    if hit is not None:
        return hit
    with localcontext() as ctx:
        ctx.prec = prec + 45
        value = 16 * _atan_small(Decimal(1) / Decimal(5), prec + 35) - 4 * _atan_small(
            Decimal(1) / Decimal(239), prec + 35
        )
        value = +value
    _PI_CACHE[prec] = value
    return value


def get_e(prec: int = DEFAULT_PREC) -> Decimal:
    """e to ``prec`` significant digits."""
    prec = _clamp_prec(prec)
    with localcontext() as ctx:
        ctx.prec = prec + 20
        return +Decimal(1).exp()


def get_tau(prec: int = DEFAULT_PREC) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = _clamp_prec(prec) + 20
        return +(2 * get_pi(prec + 10))


def fmt_dec(value: Decimal, digits: int = DEFAULT_PREC, scientific_after: int = 40) -> str:
    """Render a Decimal with ``digits`` significant digits, no exponent if short."""
    digits = max(1, int(digits))
    if value.is_nan():
        return "NaN"
    if value.is_infinite():
        return "-Infinity" if value < 0 else "Infinity"
    with localcontext() as ctx:
        ctx.prec = digits
        v = +value
    if v == 0:
        return "0"
    adj = v.adjusted()
    if adj >= scientific_after or adj <= -scientific_after:
        return format(v, "E").replace("E+", "e+").replace("E-", "e-").replace("E", "e")
    text = format(v, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-"):
        text = "0"
    return text


def _work_prec(prec: int, *values: Decimal) -> int:
    extra = 0
    for v in values:
        if isinstance(v, Decimal) and v.is_finite() and v != 0:
            extra = max(extra, v.adjusted() + 1)
    return _clamp_prec(prec) + max(0, extra) + 25


def pow_dec(x: Decimal, y: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    """``x ** y`` over the reals with high precision."""
    wp = _work_prec(prec, x, y)
    with localcontext() as ctx:
        ctx.prec = wp
        if y == y.to_integral_value():
            n = int(y)
            if x == 0 and n < 0:
                raise ZeroDivisionError("0 raised to a negative power")
            try:
                return +(x ** n)
            except (InvalidOperation, OverflowError) as exc:
                raise ArithmeticError(f"cannot evaluate power: {exc}")
        if x == 0:
            if y > 0:
                return Decimal(0)
            raise ZeroDivisionError("0 raised to a non-positive power")
        if x < 0:
            raise ArithmeticError(
                "a negative base with a non-integer exponent has no real value "
                "(use --complex aware tooling or reformulate)"
            )
        if x == 1:
            return Decimal(1)
        return +(y * x.ln()).exp()


def root_dec(x: Decimal, n: int, prec: int = DEFAULT_PREC) -> Decimal:
    """Real ``n``-th root of ``x`` (``n`` a positive integer)."""
    n = int(n)
    if n <= 0:
        raise ArithmeticError("root index must be a positive integer")
    if x < 0 and n % 2 == 0:
        raise ArithmeticError("even root of a negative number has no real value")
    neg = x < 0
    a = -x if neg else x
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        if a == 0:
            return Decimal(0)
        value = (a.ln() / Decimal(n)).exp()
        if neg:
            value = -value
        return +value


def exp_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        return +x.exp()


def ln_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    if x <= 0:
        raise ArithmeticError("logarithm of a non-positive number is undefined over the reals")
    with localcontext() as ctx:
        ctx.prec = _clamp_prec(prec) + 25
        return +x.ln()


def log10_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    if x <= 0:
        raise ArithmeticError("logarithm of a non-positive number is undefined over the reals")
    with localcontext() as ctx:
        ctx.prec = _clamp_prec(prec) + 25
        return +x.log10()


def log2_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    if x <= 0:
        raise ArithmeticError("logarithm of a non-positive number is undefined over the reals")
    wp = _clamp_prec(prec) + 25
    with localcontext() as ctx:
        ctx.prec = wp
        return +(x.ln() / Decimal(2).ln())


def log_dec(x: Decimal, base: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    if x <= 0 or base <= 0 or base == 1:
        raise ArithmeticError("invalid logarithm arguments")
    wp = _clamp_prec(prec) + 25
    with localcontext() as ctx:
        ctx.prec = wp
        return +(x.ln() / base.ln())


def _sin_series(x: Decimal, prec: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = prec + 12
        term = x
        total = x
        x2 = x * x
        k = 1
        while term != 0 and term.adjusted() > -(prec + 6):
            term = -term * x2 / ((2 * k) * (2 * k + 1))
            total += term
            k += 1
        return +total


def _cos_series(x: Decimal, prec: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = prec + 12
        term = Decimal(1)
        total = Decimal(1)
        x2 = x * x
        k = 1
        while term != 0 and term.adjusted() > -(prec + 6):
            term = -term * x2 / ((2 * k - 1) * (2 * k))
            total += term
            k += 1
        return +total


def _sin_cos(x: Decimal, prec: int):
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        if not x.is_finite():
            raise ArithmeticError("trigonometric functions need a finite argument")
        pi = get_pi(wp)
        half_pi = pi / 2
        k = (x / half_pi).to_integral_value(rounding=ROUND_HALF_EVEN)
        r = x - k * half_pi
        s = _sin_series(r, wp)
        c = _cos_series(r, wp)
        quad = int(k) % 4
        if quad == 0:
            return +s, +c
        if quad == 1:
            return +c, -s
        if quad == 2:
            return -s, -c
        return -c, +s


def sin_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    return _sin_cos(x, prec)[0]


def cos_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    return _sin_cos(x, prec)[1]


def tan_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    s, c = _sin_cos(x, prec)
    if c == 0 or c.copy_abs().adjusted() < -(prec - 5):
        raise ArithmeticError("tangent is undefined at this point (cos == 0)")
    with localcontext() as ctx:
        ctx.prec = _clamp_prec(prec) + 25
        return +(s / c)


def atan_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        neg = x < 0
        a = -x if neg else x
        inverted = False
        if a > 1:
            a = 1 / a
            inverted = True
        halvings = 0
        while a > Decimal("0.2"):
            a = a / (1 + (1 + a * a).sqrt())
            halvings += 1
        value = _atan_small(a, wp) * (2 ** halvings)
        if inverted:
            value = get_pi(wp) / 2 - value
        return +(-value if neg else value)


def asin_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        if x.copy_abs() > 1:
            raise ArithmeticError("asin is defined on [-1, 1] only")
        if x.copy_abs() == 1:
            value = get_pi(wp) / 2
            return +(-value if x < 0 else value)
        value = atan_dec(x / (1 - x * x).sqrt(), wp)
        return +value


def acos_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        if x.copy_abs() > 1:
            raise ArithmeticError("acos is defined on [-1, 1] only")
        return +(get_pi(wp) / 2 - asin_dec(x, wp))


def sinh_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        return +((x.exp() - (-x).exp()) / 2)


def cosh_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        return +((x.exp() + (-x).exp()) / 2)


def tanh_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        e2 = (2 * x).exp()
        return +((e2 - 1) / (e2 + 1))


def asinh_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        return +((x + (x * x + 1).sqrt()).ln())


def acosh_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    if x < 1:
        raise ArithmeticError("acosh is defined on [1, +inf) only")
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        return +((x + (x * x - 1).sqrt()).ln())


def atanh_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    if x.copy_abs() >= 1:
        raise ArithmeticError("atanh is defined on (-1, 1) only")
    wp = _work_prec(prec, x)
    with localcontext() as ctx:
        ctx.prec = wp
        return +(((1 + x) / (1 - x)).ln() / 2)


def floor_dec(x: Decimal) -> Decimal:
    return +x.to_integral_value(rounding=ROUND_FLOOR)


def ceil_dec(x: Decimal) -> Decimal:
    return +x.to_integral_value(rounding=ROUND_CEILING)


def round_dec(x: Decimal, digits: int = 0) -> Decimal:
    """Round to ``digits`` decimal places using half-away-from-zero."""
    digits = int(digits)
    with localcontext() as ctx:
        ctx.prec = max(28, x.adjusted() + abs(digits) + 10)
        return +x.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def trunc_dec(x: Decimal) -> Decimal:
    return +x.to_integral_value(rounding=ROUND_FLOOR if x >= 0 else ROUND_CEILING)


def gamma_dec(x: Decimal, prec: int = DEFAULT_PREC) -> Decimal:
    """Gamma function via the Lanczos approximation.

    The approximation carries roughly 15 correct significant digits, so the
    result is deliberately rounded to that many digits instead of pretending to
    honour a larger ``prec``.
    """
    if x == x.to_integral_value() and x <= 0:
        raise ArithmeticError("Gamma has poles at non-positive integers")
    wp = _clamp_prec(prec) + 25
    g = Decimal(7)
    with localcontext() as ctx:
        ctx.prec = wp
        coef = [
            "0.99999999999980993",
            "676.5203681218851",
            "-1259.1392167224028",
            "771.32342877765313",
            "-176.61502916214059",
            "12.507343278686905",
            "-0.13857109526572012",
            "9.9843695780195716e-6",
            "1.5056327351493116e-7",
        ]
        if x < Decimal("0.5"):
            pi = get_pi(wp)
            value = pi / (sin_dec(pi * x, wp) * gamma_dec(1 - x, wp))
        else:
            z = x - 1
            a = Decimal(coef[0])
            t = z + g + Decimal("0.5")
            for i in range(1, 9):
                a += Decimal(coef[i]) / (z + i)
            value = (2 * get_pi(wp)).sqrt() * t ** (z + Decimal("0.5")) * (-t).exp() * a
        return +value.quantize(Decimal(1).scaleb(value.adjusted() - 14))
