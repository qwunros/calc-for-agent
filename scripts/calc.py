#!/usr/bin/env python3
"""``calc`` - exact scientific calculator CLI for AI agents.

Every command prints one JSON object on stdout (``{"ok": true, ...}`` on
success, ``{"ok": false, "error": {...}}`` on failure) so an agent can parse the
result without guessing.  ``--text`` switches to a compact human-readable form.

Run ``calc.py help`` for the command list, ``calc.py funcs`` for the supported
functions, or ``calc.py help <command>`` for one command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# deeply nested parentheses / long chains are parsed recursively
sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))

import calc_num as num  # noqa: E402
import calc_parse as cp  # noqa: E402
from calc_core import CalcError, Exact, format_fraction, fraction_from_decimal_string  # noqa: E402
import calc_domains as dom  # noqa: E402

VERSION = "1.0.0"

EXIT_OK = 0
EXIT_CALC = 1
EXIT_USAGE = 2


class JsonArgumentParser(argparse.ArgumentParser):
    """Argparse variant that reports usage errors as JSON on stdout (exit 2)."""

    def error(self, message: str):  # noqa: D102 - argparse hook
        base = (self.prog or "calc").split(" ")[0]
        emit_error(f"{message}; run `{base} help` for usage", "usage_error", False)
        raise SystemExit(EXIT_USAGE)


# --------------------------------------------------------------------------
# output helpers
# --------------------------------------------------------------------------


def _plain(payload: dict, indent: bool) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2 if indent else None)


def emit(payload: dict, pretty: bool = False) -> None:
    sys.stdout.write(_plain(payload, pretty) + "\n")


def emit_error(message: str, kind: str = "calc_error", pretty: bool = False) -> None:
    emit({"ok": False, "error": {"type": kind, "message": message}}, pretty)


def ok(command: str, result: dict, pretty: bool = False) -> None:
    payload = {"ok": True, "command": command}
    payload.update(result)
    emit(payload, pretty)


def text_mode(command: str, result: dict) -> None:
    """Render a result as compact ``key: value`` lines for human reading."""
    lines = [f"# {command}"]
    for key, value in result.items():
        if isinstance(value, dict):
            if "exact" in value and value["exact"] is not None:
                lines.append(f"{key}: {value['exact']}   (approx {value.get('approx')})")
            elif "approx" in value:
                lines.append(f"{key}: {value['approx']}")
            else:
                lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        elif isinstance(value, list):
            rendered = []
            for item in value:
                if isinstance(item, dict):
                    rendered.append(str(item.get("exact") or item.get("value") or item.get("approx")))
                else:
                    rendered.append(str(item))
            lines.append(f"{key}: {', '.join(rendered) if rendered else '[]'}")
        else:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    sys.stdout.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# bindings
# --------------------------------------------------------------------------


def parse_bindings(pairs) -> dict:
    bindings: dict = {}
    for raw in pairs or []:
        if "=" not in raw:
            raise CalcError(f"--var expects name=value, got {raw!r}")
        name, _, value = raw.partition("=")
        name = name.strip()
        if not name:
            raise CalcError(f"--var expects name=value, got {raw!r}")
        kind, val = cp.evaluate(value.strip(), num.DEFAULT_PREC)
        bindings[name] = val if kind == "exact" else Exact.from_fraction(fraction_from_decimal_string(str(val)))
    return bindings


def read_file(path: str) -> str:
    """Read a text file, turning OS failures into clean calculation errors."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CalcError(f"cannot read {path!r}: {exc.strerror or exc}") from exc


def read_numbers(args) -> list:
    """Collect numbers from positional arguments, --file and --stdin."""
    values = list(getattr(args, "values", []) or [])
    if getattr(args, "file", None):
        text = read_file(args.file)
        values.extend(text.replace(",", " ").split())
    if getattr(args, "stdin", False):
        values.extend(sys.stdin.read().replace(",", " ").split())
    return values


# --------------------------------------------------------------------------
# command handlers
# --------------------------------------------------------------------------


def cmd_eval(args) -> int:
    bindings = parse_bindings(args.var)
    result = dom.do_eval(args.expr, args.prec, args.digits, bindings)
    if args.text:
        text_mode("eval", result)
    else:
        ok("eval", result, args.pretty)
    return EXIT_OK


def cmd_verify(args) -> int:
    result = dom.do_verify(args.left, args.right, args.prec, args.digits)
    if args.text:
        text_mode("verify", result)
    else:
        ok("verify", result, args.pretty)
    return EXIT_OK


def cmd_solve(args) -> int:
    result = dom.do_solve(
        args.equation,
        var=args.var_name,
        prec=args.prec,
        digits=args.digits,
        complex_allowed=args.complex,
        numeric=args.numeric,
        scan_range=(args.range[0], args.range[1]),
        samples=args.samples,
    )
    if args.text:
        text_mode("solve", result)
    else:
        ok("solve", result, args.pretty)
    return EXIT_OK


def cmd_stats(args) -> int:
    values = read_numbers(args)
    if not values:
        raise CalcError("no data: pass numbers, --file <path> or --stdin")
    result = dom.do_stats(values, args.prec, args.digits)
    result["input_values"] = values
    if args.text:
        text_mode("stats", result)
    else:
        ok("stats", result, args.pretty)
    return EXIT_OK


def cmd_base(args) -> int:
    result = dom.do_base(args.value, args.from_base, args.to, args.digits, args.prec)
    if args.text:
        text_mode("base", result)
    else:
        ok("base", result, args.pretty)
    return EXIT_OK


def cmd_fraction(args) -> int:
    result = dom.do_fraction(args.value, args.prec, args.digits)
    if args.text:
        text_mode("fraction", result)
    else:
        ok("fraction", result, args.pretty)
    return EXIT_OK


def cmd_decimal(args) -> int:
    result = dom.do_decimal(args.value, args.digits, args.prec)
    if args.text:
        text_mode("decimal", result)
    else:
        ok("decimal", result, args.pretty)
    return EXIT_OK


def cmd_factor(args) -> int:
    result = dom.do_factor(args.value, args.prec, args.digits, args.max_steps)
    if args.text:
        text_mode("factor", result)
    else:
        ok("factor", result, args.pretty)
    return EXIT_OK


def cmd_primes(args) -> int:
    result = dom.do_primes(args.lo, args.hi, args.limit)
    if args.text:
        text_mode("primes", result)
    else:
        ok("primes", result, args.pretty)
    return EXIT_OK


def cmd_units(args) -> int:
    if args.list:
        ok("units", {"categories": dom.units_listing()}, args.pretty)
        return EXIT_OK
    if not args.value or not args.to_unit:
        raise CalcError("usage: units <value> <from_unit> --to <unit>   (or: units --list)")
    result = dom.do_units(args.value, args.from_unit, args.to_unit, args.prec, args.digits)
    if args.text:
        text_mode("units", result)
    else:
        ok("units", result, args.pretty)
    return EXIT_OK


def cmd_round(args) -> int:
    result = dom.do_round(args.expr, args.digits_places, args.prec)
    if args.text:
        text_mode("round", result)
    else:
        ok("round", result, args.pretty)
    return EXIT_OK


def cmd_batch(args) -> int:
    """Read a stream of jobs and answer them in one process.

    Each input line is either a bare expression (evaluated) or a JSON object
    ``{"cmd": "...", ...}`` matching the command line options.
    """
    results = []
    stream = sys.stdin.read()
    if args.file:
        stream = read_file(args.file)
    for lineno, line in enumerate(stream.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            if stripped.startswith("{"):
                job = json.loads(stripped)
                results.append(_run_job(job, lineno))
            else:
                results.append({"line": lineno, "input": stripped, "ok": True, **dom.do_eval(stripped, args.prec, args.digits)})
        except CalcError as exc:
            results.append({"line": lineno, "ok": False, "error": {"type": exc.kind, "message": str(exc)}})
        except (ValueError, TypeError, ArithmeticError, ZeroDivisionError) as exc:
            results.append({"line": lineno, "ok": False, "error": {"type": "error", "message": str(exc)}})
        except Exception as exc:  # pragma: no cover - defensive
            results.append({"line": lineno, "ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
    payload = {"ok": True, "command": "batch", "count": len(results), "results": results}
    emit(payload, args.pretty)
    return EXIT_OK


def _run_job(job: dict, lineno: int) -> dict:
    cmd = str(job.get("cmd") or job.get("op") or "eval").lower()
    prec = int(job.get("prec", num.DEFAULT_PREC))
    digits = int(job.get("digits", 30))
    if cmd in ("eval", "calc", "expr"):
        body = dom.do_eval(str(job.get("expr", job.get("input", ""))), prec, digits)
    elif cmd == "verify":
        body = dom.do_verify(str(job.get("left", job.get("a", ""))), str(job.get("right", job.get("b", ""))), prec, digits)
    elif cmd == "solve":
        body = dom.do_solve(
            str(job.get("equation", job.get("expr", ""))),
            var=job.get("var"),
            prec=prec,
            digits=digits,
            complex_allowed=bool(job.get("complex", False)),
            numeric=bool(job.get("numeric", False)),
        )
    elif cmd == "stats":
        values = job.get("values") or job.get("data") or []
        body = dom.do_stats([str(v) for v in values], prec, digits)
    elif cmd == "base":
        body = dom.do_base(
            str(job.get("value", "")),
            int(job["from"]) if job.get("from") is not None else None,
            int(job.get("to", 16)),
            int(job.get("digits", 40)),
            prec,
        )
    elif cmd == "units":
        body = dom.do_units(str(job.get("value", "")), str(job.get("from", "")), str(job.get("to", "")), prec, digits)
    elif cmd == "fraction":
        body = dom.do_fraction(str(job.get("value", "")), prec, digits)
    elif cmd == "decimal":
        body = dom.do_decimal(str(job.get("value", "")), int(job.get("digits", 50)), prec)
    elif cmd == "factor":
        body = dom.do_factor(str(job.get("value", "")), prec, digits)
    else:
        raise CalcError(f"unknown batch command {cmd!r}")
    return {"line": lineno, "ok": True, "cmd": cmd, **body}


# --------------------------------------------------------------------------
# help
# --------------------------------------------------------------------------


def cmd_help(args) -> int:
    topic = (args.topic or "").lower()
    topics = {
        "eval": "eval '<expr>' [--var x=2] [--prec 30] [--digits 30]\n"
        "  Evaluate one expression. Exact results are reported in `exact`\n"
        "  (fractions, big integers, exact radicals) with `approx` alongside.",
        "solve": "solve '<equation>' [--var-name x] [--complex] [--numeric]\n"
        "  [--range LO HI] [--samples N]\n"
        "  Solve one equation with one unknown. Polynomials of degree <= 2 and\n"
        "  rational roots of higher degree are exact; other roots are numeric.",
        "stats": "stats <numbers...> [--file PATH] [--stdin]\n"
        "  Descriptive statistics with exact mean/median/variance when the data\n"
        "  is rational; the standard deviation stays exact when possible.",
        "base": "base <value> [--from B] [--to B] [--digits N]\n"
        "  Convert between bases 2..36 (big integers and fractional parts included).",
        "fraction": "fraction <decimal|fraction>\n  Exact fraction form, plus decimal expansion and factorisations.",
        "decimal": "decimal <fraction> [--digits N]\n  Decimal expansion with recurring-block detection, e.g. 1/7 -> 0.(142857).",
        "factor": "factor <integer>\n  Prime factorisation, divisors, divisor count/sum and Euler phi.",
        "primes": "primes <lo> <hi> [--limit N]\n  Prime numbers in a range.",
        "units": "units <value> <from> --to <unit>\n  units --list\n  Exact unit conversion (length, mass, time, area, volume, speed, data,\n  energy, pressure, temperature, angle).",
        "round": "round '<expr>' [--digits-places N]\n  Round to N decimal places (half away from zero).",
        "verify": "verify '<expr A>' '<expr B>'\n  Decide whether two expressions are exactly equal, with the exact difference.",
        "batch": "batch [--file PATH]\n  Read JSON-lines jobs (or bare expressions) from stdin and answer them all.",
        "funcs": "calc.py funcs\n  List every supported function and constant.",
    }
    if topic in topics:
        sys.stdout.write(topics[topic] + "\n")
        return EXIT_OK
    sys.stdout.write(
        "calc 1.0.0 - exact calculator for agents\n\n"
        "Commands:\n"
        "  eval '<expr>'         evaluate an expression (exact first)\n"
        "  solve '<equation>'    solve an equation in one unknown\n"
        "  stats <numbers...>    descriptive statistics\n"
        "  base <value>          base conversion (2..36)\n"
        "  fraction <value>      decimal/fraction -> exact fraction\n"
        "  decimal <value>       fraction -> decimal expansion\n"
        "  factor <integer>      prime factorisation and number theory\n"
        "  primes <lo> <hi>      primes in a range\n"
        "  units <v> <from> --to <to>   unit conversion\n"
        "  round '<expr>' -d N   round to N decimal places\n"
        "  verify '<a>' '<b>'    exact equality check\n"
        "  batch                 many jobs from stdin in one process\n"
        "  funcs | help [topic]  reference\n\n"
        "Global options: --prec N (calculation digits, default 30), --digits N\n"
        "(digits printed, default 30), --pretty, --text (human output).\n"
        "Every command answers with a single JSON object on stdout.\n\n"
        "Windows note: a batch launcher (calc.cmd) started from PowerShell loses\n"
        "the caret '^', so write powers as '**' or pow(a, b) there, or call\n"
        "scripts/calc.py directly.\n"
    )
    return EXIT_OK


def cmd_funcs(args) -> int:
    funcs = [
        {
            "name": name,
            "min_args": spec[0],
            "max_args": spec[1],
            "exact": spec[2],
            "description": spec[3],
        }
        for name, spec in sorted(cp.FUNCTIONS.items())
    ]
    payload = {
        "ok": True,
        "command": "funcs",
        "functions": funcs,
        "constants": cp.CONSTANTS,
        "operators": ["+", "-", "*", "/", "//", "%", "^ or **", "!", "implicit multiplication", "sqrt sign"],
        "examples": [
            "2^100",
            "1/3 + 1/6",
            "sqrt(8) + sqrt(18)",
            "1/(sqrt(2)+sqrt(3))",
            "50!",
            "sin(pi/6)",
            "log(1024, 2)",
        ],
    }
    emit(payload, args.pretty)
    return EXIT_OK


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="calc",
        description="Exact scientific calculator for AI agents (JSON output).",
        add_help=True,
    )
    parser.add_argument("--version", action="version", version=f"calc {VERSION}")
    sub = parser.add_subparsers(dest="command")

    def common(p, extra_text=False):
        p.add_argument(
            "--prec", type=int, default=num.DEFAULT_PREC, help="calculation precision in digits (default 30)"
        )
        p.add_argument("--digits", type=int, default=30, help="significant digits to print (default 30)")
        p.add_argument("--pretty", action="store_true", help="indent the JSON output")
        if extra_text:
            p.add_argument("--text", action="store_true", help="human-readable output instead of JSON")
        return p

    p = common(sub.add_parser("eval", help="evaluate an expression"), extra_text=True)
    p.add_argument("expr")
    p.add_argument("--var", action="append", default=[], help="bind a variable, e.g. --var x=2")
    p.set_defaults(func=cmd_eval)

    p = common(sub.add_parser("verify", help="exact equality check"), extra_text=True)
    p.add_argument("left")
    p.add_argument("right")
    p.set_defaults(func=cmd_verify)

    p = common(sub.add_parser("solve", help="solve an equation"), extra_text=True)
    p.add_argument("equation")
    p.add_argument("--var-name", default=None, help="unknown to solve for (default: auto-detect)")
    p.add_argument("--complex", action="store_true", help="also return complex roots")
    p.add_argument("--numeric", action="store_true", help="force numeric root finding")
    p.add_argument("--range", type=float, nargs=2, default=[-50.0, 50.0], metavar=("LO", "HI"))
    p.add_argument("--samples", type=int, default=4000)
    p.set_defaults(func=cmd_solve)

    p = common(sub.add_parser("stats", help="descriptive statistics"), extra_text=True)
    p.add_argument("values", nargs="*")
    p.add_argument("--file", default=None, help="read numbers from a file")
    p.add_argument("--stdin", action="store_true", help="read numbers from stdin")
    p.set_defaults(func=cmd_stats)

    p = common(sub.add_parser("base", help="base conversion"), extra_text=True)
    p.add_argument("value")
    p.add_argument("--from", dest="from_base", type=int, default=None, help="source base 2..36 (auto-detects 0x/0b/0o)")
    p.add_argument("--to", type=int, default=16, help="target base 2..36")
    p.set_defaults(func=cmd_base)

    p = common(sub.add_parser("fraction", help="decimal -> exact fraction"), extra_text=True)
    p.add_argument("value")
    p.set_defaults(func=cmd_fraction)

    p = common(sub.add_parser("decimal", help="fraction -> decimal expansion"), extra_text=True)
    p.add_argument("value")
    p.set_defaults(func=cmd_decimal)

    p = common(sub.add_parser("factor", help="prime factorisation"), extra_text=True)
    p.add_argument("value")
    p.add_argument("--max-steps", type=int, default=2000000, help="effort budget for large factors")
    p.set_defaults(func=cmd_factor)

    p = common(sub.add_parser("primes", help="primes in a range"), extra_text=True)
    p.add_argument("lo")
    p.add_argument("hi")
    p.add_argument("--limit", type=int, default=2000)
    p.set_defaults(func=cmd_primes)

    p = common(sub.add_parser("units", help="unit conversion"), extra_text=True)
    p.add_argument("value", nargs="?", default=None)
    p.add_argument("from_unit", nargs="?", default=None)
    p.add_argument("--to", dest="to_unit", default=None)
    p.add_argument("--list", action="store_true", help="list all known units")
    p.set_defaults(func=cmd_units)

    p = common(sub.add_parser("round", help="round to N decimal places"), extra_text=True)
    p.add_argument("expr")
    p.add_argument("-d", "--digits-places", type=int, default=0)
    p.set_defaults(func=cmd_round)

    p = common(sub.add_parser("batch", help="many jobs from stdin"), extra_text=False)
    p.add_argument("--file", default=None)
    p.set_defaults(func=cmd_batch)

    p = common(sub.add_parser("help", help="command reference"))
    p.add_argument("topic", nargs="?", default=None)
    p.set_defaults(func=cmd_help)

    p = common(sub.add_parser("funcs", help="list supported functions"))
    p.set_defaults(func=cmd_funcs)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_OK
    if hasattr(args, "prec"):
        args.prec = max(1, min(num.MAX_PREC, args.prec))
    if hasattr(args, "digits"):
        args.digits = max(1, min(5000, args.digits))
    try:
        return args.func(args)
    except CalcError as exc:
        emit_error(str(exc), exc.kind, getattr(args, "pretty", False))
        return EXIT_CALC
    except ZeroDivisionError:
        emit_error("division by zero", "zero_division", getattr(args, "pretty", False))
        return EXIT_CALC
    except ArithmeticError as exc:
        emit_error(str(exc), "arithmetic_error", getattr(args, "pretty", False))
        return EXIT_CALC
    except RecursionError:
        emit_error(
            "expression is nested too deeply (parser stack limit reached); "
            "split it into smaller sub-expressions or use batch mode",
            "recursion_limit",
            getattr(args, "pretty", False),
        )
        return EXIT_CALC
    except ValueError as exc:
        message = str(exc)
        if "int_max_str_digits" in message or "integer string conversion" in message:
            message = (
                "the result is too large to render as a decimal string "
                "(limit 200000 digits); compute a scaled or factorised answer instead"
            )
        emit_error(message, "value_error", getattr(args, "pretty", False))
        return EXIT_CALC
    except BrokenPipeError:  # pragma: no cover
        return EXIT_OK
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":
    sys.exit(main())
