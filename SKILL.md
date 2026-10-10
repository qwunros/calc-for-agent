---
name: calc-for-agent
description: Exact scientific calculator CLI (Python, standard library only) for arithmetic with fractions/big integers/exact radicals, equation solving, statistics, base conversion, unit conversion and number theory. Use it whenever a task requires computing or verifying a number.
whenToUse: Use for ANY arithmetic, algebra or numeric work — fractions, decimals, percentages, powers, roots, factorials, big integers, equations, systems of one unknown, statistics (mean/variance/stddev), base conversion (hex/bin/oct/base-N), unit conversion, primality/factorisation — instead of doing arithmetic mentally, in the shell, or with floating-point code. Also use it to verify a numeric claim before stating it.
---

# calc for agent

`calc` is a command-line calculator written for agents. It keeps **fractions,
finite decimals, arbitrary-size integers and square roots exact**, and it always
answers with one parseable JSON object.

## Rule 0 - never compute mentally

If the answer to any part of a task is a number, get that number from `calc`
(or check it with `calc`). Language-model arithmetic is unreliable; this tool is
exact. Do not use shell `expr`/PowerShell `[math]::`/Python floats for maths that
needs to be right - they lose precision on decimals, fractions and big integers.

## How to run it

The entry point is `scripts/calc.py` inside this skill bundle (next to this
`SKILL.md`). **Call Python directly** - arguments pass through untouched:

```powershell
python "<skill>/scripts/calc.py" eval "sqrt(8) + sqrt(18)"
```

`calc.cmd` (Windows) and `calc` (POSIX shell) sit beside `SKILL.md`, resolve
their own directory, and work from any working directory:

```powershell
& "<skill>\calc.cmd" eval "1/3 + 1/6"
```

> Warning: when a batch file is launched **from PowerShell**, `cmd.exe` treats
> `^` as an escape character and deletes it, so `calc.cmd eval "2^256"` silently
> becomes `2256`. Always write powers as `**` or `pow(a, b)` (`2**256`,
> `pow(2,256)`) when using `calc.cmd`, or call `scripts/calc.py` directly.

In this workspace the skill is installed at
`C:\Users\asus\Desktop\calc_for_agent\.dsh\skills\calc-for-agent`. If you cannot
see it, locate it with:
`Get-ChildItem -Recurse -Filter calc.cmd | Where-Object FullName -like '*calc-for-agent*'`.

## Output contract

Every command prints **one JSON object** on stdout:

```json
{"ok": true, "command": "eval", "kind": "exact", "exact": "5*sqrt(2)",
 "approx": "7.07106781186547524400844362105", "float": 7.071067811865476,
 "input": "sqrt(8)+sqrt(18)", "exact_available": true}
```

* `exact` - mathematically exact form (integer, `n/d` fraction, or radical such
  as `2*sqrt(2)`, `sqrt(3)/3`, `sqrt(5)/2 + 1/2`). **Report this when present.**
* `approx` - high-precision decimal of the same value (`--digits`, default 30).
* `kind` - `"exact"` or `"approximate"`. For `"approximate"` there is no exact
  form; say so if the user needs one.
* `ok: false` + `error.type`/`error.message` on failure; exit code `1` for a
  calculation error, `2` for a usage error. Nothing but JSON is written to
  stdout, so parse it directly.
* `--text` gives readable output instead of JSON; `--pretty` indents the JSON.

## Everyday commands

The examples below use `**` for powers so they are safe to paste into
PowerShell via `calc.cmd` (see the caret caveat above).

| Goal | Command |
|---|---|
| exact arithmetic | `calc.cmd eval "1/3 + 1/6"` → `1/2` |
| high-precision constant | `calc.cmd eval "pi" --prec 60 --digits 50` |
| exact radicals | `calc.cmd eval "sqrt(8)+sqrt(18)"` → `5*sqrt(2)` |
| big integers / factorials | `calc.cmd eval "2**256"`, `calc.cmd eval "100!"` |
| percentage / ratio | `calc.cmd eval "0.15*240"`, `calc.cmd eval "(37-32)/32*100"` |
| round / floor / ceil | `calc.cmd round "1/3" -d 4`, `calc.cmd eval "ceil(7/2)"` |
| trig / log / exp | `calc.cmd eval "sin(pi/6)"`, `calc.cmd eval "log(1024,2)"` |
| check a claim | `calc.cmd verify "sqrt(2)**2" "2"` → `equal: true` |
| solve an equation | `calc.cmd solve "x**2-5x+6=0"` → `2`, `3` |
| statistics | `calc.cmd stats 1 2 3 4 5 6` |
| base conversion | `calc.cmd base 255 --to 2`, `calc.cmd base 0.1 --from 10 --to 2` |
| decimal ↔ fraction | `calc.cmd fraction 0.375`, `calc.cmd decimal 1/7` |
| number theory | `calc.cmd factor 360`, `calc.cmd primes 100 120` |
| unit conversion | `calc.cmd units 100 km --to mi`, `calc.cmd units 100 c --to f` |

Expression syntax: `+ - * / // % ^ **`, parentheses, implicit multiplication
(`2x`, `3(4+5)`, `2sqrt(2)`), postfix `!`, and the constants/functions below.
`^` and `**` mean power; `/` is always exact rational division.

Functions: `sqrt cbrt root(x,n) pow(a,b) abs sign floor ceil trunc round(x[,d])
min max gcd lcm factorial comb perm fib isprime mod exp ln log(x[,base]) log2
log10 sin cos tan asin acos atan sinh cosh tanh asinh acosh atanh gamma`.
Constants: `pi e tau phi` (`phi` is exact; `pi`/`e` are approximate).
Full details, options and edge cases: read `references/operations.md`.

## Precision rules you must respect

* **Exact** (keep and report verbatim): integers of any size, fractions,
  finite decimals, and any `+ - * / // % ^` combination of them, including
  `sqrt()` of rationals (`sqrt(8)` → `2*sqrt(2)`), integer roots of perfect
  powers (`root(27,3)` → `3`) and `sin`/`cos`/`tan` at multiples of `pi/6` and
  `pi/4` (`sin(pi/6)` → `1/2`, `cos(pi)` → `-1`).
* **Approximate** (mark it, do not present as exact): `pi`, `e`, `ln`, `exp`,
  `sin`/`cos`/`tan` at other angles, inverse/hyperbolic functions, non-perfect
  roots, `sqrt` of an irrational expression, decimals built from `pi`. Raise
  `--prec`/`--digits` (up to 2000) when more digits are needed; never round
  early.
* Default calculation precision is 30 significant digits. `--prec` changes the
  maths, `--digits` only changes how many digits are printed.

## Command notes

* `solve` takes one unknown (`x`, or `--var-name`). Linear, quadratic and
  rational equations are **exact**; higher-degree polynomials combine exact
  rational roots with numeric ones (real roots carry `accuracy`); everything
  else is scanned numerically over `--range LO HI` (default -50..50) - report
  those as "numeric root in the scanned interval". `--complex` applies to the
  polynomial solver only.
* `stats` (integers, decimals, `"1/3"`; also `--file`/`--stdin`): mean, median
  and variance are exact, the standard deviation is exact when its root is
  (`sqrt(14)/2`), quantiles interpolate linearly.
* `base` converts integers and fractional parts in bases 2..36, reporting
  recurring expansions like `0.0(0011)`; `--from` auto-detects `0x`/`0b`/`0o`.
* `units` is exact for multiplicative units and affine temperature; radian
  conversions involve `pi` and are approximate. Use `units --list`.

## Working efficiently

* `batch` answers many jobs in one process: one bare expression or
  `{"cmd": "eval", "expr": "..."}` JSON object per stdin line, results in order.
* Ask for what you need: `--digits 6` for a report, `--prec 60 --digits 50` for
  high-precision constants.
* Check `ok`/`kind` before using a value, and quote `error.message` on failure
  instead of inventing a result.
* Results above ~200000 digits (e.g. `factorial(100000)`) come back with
  `exact: null` plus `approx`, `numerator_digits` and a `note`.
* `help <command>` and `funcs` answer usage questions; tests live in
  `tests/test_calc.py`.
