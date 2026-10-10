# calc for agent - complete operation reference

This is the on-demand reference for the `calc-for-agent` skill. `SKILL.md` holds
the working summary; this file holds every command, option, function and edge
case. Entry point: `scripts/calc.py` (launcher `calc.cmd` / `calc` beside
`SKILL.md`).

```
python <skill>/scripts/calc.py <command> [arguments] [options]
```

**Prefer the direct `python ...` form**: argument handling is identical on every
platform. The bundled `calc.cmd` / `calc` launcher resolves its own directory,
but when `calc.cmd` is started *from PowerShell*, `cmd.exe` consumes the caret
`^`, so `eval "2^10"` arrives as `210`. Use `**` or `pow(a, b)` in that case
(`eval "2**10"`, `eval "pow(2,10)"`), or call `scripts/calc.py` directly.

Every command answers with exactly one JSON object on stdout
(`{"ok": true, "command": "<name>", ...}` or
`{"ok": false, "error": {"type": "...", "message": "..."}}`), exit code `0` on
success, `1` on a calculation error and `2` on a usage error (`error.type`
`usage_error`). Only `help`/`help <command>` and argparse's `--help`/`--version`
print plain text; every calculation command - `funcs` included - writes JSON to
stdout, as do all error paths. A nested expression that exceeds the parser stack
is reported as `error.type: recursion_limit`, and an unreadable `--file` path as
`error.type: calc_error` ("cannot read ...").

Global options: `--prec N` (calculation precision in significant digits,
default 30, clamped to 1..2000), `--digits N` (significant digits printed,
default 30, clamped to 1..5000), `--pretty`, `--text` (where documented),
`--version`. `eval` echoes the effective values back as
`"precision": {"calculation_digits": N, "printed_digits": M}`.

---

## 1. eval - expressions

```
calc.cmd eval "<expr>" [--var name=value ...] [--prec 30] [--digits 30] [--text]
```

Grammar (hand-written tokenizer/parser; no `eval`, no code execution):

| Element | Forms |
|---|---|
| integers | `42`, `1_000_000`, `0xFF`, `0b1011`, `0o17` |
| decimals | `1.25`, `.5`, `1e-9`, `2.5e3` (exact: `0.1` is `1/10`, never binary floating point) |
| fractions | `3/4` (exact division), `-22/7` |
| operators | `+ - * / // % ^ **`, unary `+ -`, postfix `!` (factorial) |
| implicit multiplication | `2x`, `3(4+5)`, `2sqrt(2)`, `(x+1)(x-2)` |
| radical sign | `√8` is `sqrt(8)` |
| grouping | `( ... )`, function calls `f(a, b)` |

Precedence: `!` > `^`/`**` (right associative) > unary `-` > `* / // %` and
implicit multiplication (left associative) > `+ -`. So `-2^2 = -4`, `2^3^2 = 512`,
`2/3x = (2/3)*x`.

### Functions

| Function | Exact? | Notes |
|---|---|---|
| `sqrt(x)` | yes* | `sqrt(8)` → `2*sqrt(2)`, `sqrt(1/3)` → `sqrt(3)/3`; negative → error |
| `pow(a, b)` | yes* | caret-free spelling of `a**b`: `pow(2,10)` → `1024` |
| `cbrt(x)`, `root(x, n)` | yes* | exact for perfect powers: `root(27,3)` → `3`, `root(2,3)` → approximate |
| `abs(x)`, `sign(x)` | yes | works on surds too |
| `floor ceil trunc` | yes | exact even for irrational values: `floor(sqrt(2))` → `1` |
| `round(x)`, `round(x, d)` | yes | half away from zero: `round(2.5)` → `3`, `round(-2.5)` → `-3` |
| `min(...)`, `max(...)` | yes | 1..8 arguments, exact comparisons |
| `gcd(...)`, `lcm(...)` | yes | integers |
| `factorial(n)` | yes | `n!` for 0 ≤ n ≤ 100000; results beyond ~200000 digits are described, not printed |
| `comb(n,k)`, `perm(n,k)`, `fib(n)` | yes | binomial, k-permutations, Fibonacci |
| `isprime(n)` | yes | `1`/`0` |
| `mod(a,b)` | yes | sign follows the divisor, like `a % b` |
| `exp ln log(x[,base]) log2 log10` | no | high-precision `decimal` implementation |
| `asin acos atan` | no | radians, high-precision `decimal` implementation |
| `sin cos tan` | partly | radians; **exact** at multiples of `pi/6` and `pi/4` (`sin(pi/6)` → `1/2`, `cos(pi/3)` → `1/2`, `tan(pi/4)` → `1`, `sin(pi)` → `0`), approximate otherwise (high-precision series with exact argument reduction) |
| `sinh cosh tanh asinh acosh atanh` | no | |
| `gamma(x)` | no | Lanczos, rounded to its real accuracy of ~15 significant digits |

\* exact whenever the exact-arithmetic field supports it; otherwise `calc`
reports `kind: "approximate"` and a high-precision decimal instead of a wrong
"exact" label.

Constants: `pi`, `e`, `tau` (approximate, computed to `--prec`); `phi` is exact
(`sqrt(5)/2 + 1/2`). Unknown identifiers are treated as variables and must be
bound with `--var name=value`, e.g. `--var x=3`.

### Result fields

```json
{"ok": true, "command": "eval", "kind": "exact", "exact": "sqrt(5)/2 + 1/2",
 "latex": "\\frac{\\sqrt{5}}{2} + \\frac{1}{2}", "approx": "1.61803398874989484820458683437",
 "type": "irrational_exact", "float": 1.618033988749895,
 "input": "phi", "exact_available": true}
```

* exact integers/rationals also carry `fraction`, `mixed`, `decimal`,
  `decimal_kind` (`integer` | `terminating` | `recurring` | `rounded`), and for
  integers up to 10^12 a `factorization` and `is_prime`.
* `kind: "approximate"` carries `approx` + `float`, `exact: null`, and a `note`.
* `type` is one of `integer`, `rational`, `irrational_exact`, `approximate`.

### Worked examples

```
eval "1/3 + 1/6"                    -> exact 1/2
eval "0.1 + 0.2"                    -> exact 3/10          (not 0.30000000000000004)
eval "2^256"                        -> exact 115792089237316195423570985008687907853269984665640564039457584007913129639936
eval "100!"                         -> exact, 158 digits
eval "sqrt(8)+sqrt(18)"             -> exact 5*sqrt(2)
eval "1/(sqrt(2)+sqrt(3))"          -> exact -sqrt(2) + sqrt(3)   (rationalised)
eval "(1+sqrt(5))/2"                -> exact sqrt(5)/2 + 1/2
eval "sin(pi/6)" --digits 20        -> exact 1/2 (special angles are exact)
eval "sin(pi/4)"                    -> exact sqrt(2)/2
eval "cos(pi)"                      -> exact -1
eval "sin(1)"                       -> approximate 0.841470984807896506652502321630
eval "log(1024, 2)"                 -> approximate 10
eval "1e-3 * 1e3"                   -> exact 1
eval "1/7" --digits 12              -> exact 1/7, decimal "0.(142857)"
eval "pi" --prec 60 --digits 50     -> 50 correct digits
```

---

## 2. solve - equations in one unknown

```
calc.cmd solve "<equation>" [--var-name x] [--complex] [--numeric]
              [--range LO HI] [--samples N] [--prec 30] [--digits 30] [--text]
```

* `=` separates the two sides; a bare expression is taken as `expr = 0`.
* The unknown is auto-detected; name it with `--var-name`.
* Solving paths, in order:
  1. **polynomial** with exact coefficients (radical coefficients such as
     `sqrt(2)x-1=0` included) - degree 1 and 2 exact, discriminant handled with
     exact square roots (`x^2-x-1=0` → `sqrt(5)/2 + 1/2`, `-sqrt(5)/2 + 1/2`).
  2. **rational equation** cross-multiplication (`1/x=4` → `1/4`,
     `(x+1)/(x-2)=3` → `7/2`), with extraneous roots listed in
     `excluded_extraneous_roots`.
  3. **higher degree**: exact rational roots (rational root theorem), then the
     remaining polynomial numerically (Durand-Kerner + Newton polish).
  4. **anything else**: numeric scan + bisection over `--range` (default
     -50..50) with `--samples` (default 4000) samples. Roots outside the range
     are not found; the `method` field says what happened.
* `--complex` returns complex roots from the polynomial solver (negative
  discriminants, and the Durand-Kerner complex roots of higher-degree
  polynomials). The scan-based numeric path finds **real** roots only and says
  so in its `note` when `--complex` was requested.
* Each solution carries `exact`/`value`, `approx`, `solution_kind`
  (`exact`, `exact-complex`, `numeric`, `numeric-complex`), `multiplicity`,
  `residual` (the polynomial value at the root, normally `0`) and `accuracy`.
  Real numeric roots are refined with Newton's method in Decimal arithmetic, so
  they really do carry `--prec` correct digits; complex roots stay in double
  precision and report `accuracy: "double precision (~15 significant digits)"`
  instead of printing fabricated digits.
* `solutions` is the string `"all numbers"` for an identity and `[]` with a note
  for a contradiction.

```
solve "2x+3=7"                 -> exact 2
solve "x^2-5x+6=0"             -> exact 2, 3
solve "x^2-x-1=0"              -> exact sqrt(5)/2 + 1/2, -sqrt(5)/2 + 1/2
solve "x^2-4x+4=0"             -> exact 2 with multiplicity 2
solve "x^2+1=0" --complex      -> exact i, -i
solve "x^3-6x^2+11x-6=0"       -> exact 1, 2, 3
solve "x^4-10x^2+1=0"          -> 4 numeric roots, real ones Newton-polished to --prec
                                 (root sqrt(3)-sqrt(2) correct to every digit requested)
solve "sin(x)-0.5=0" --range 0 3   -> 0.523598775598299, 2.61799387799149 (numeric)
solve "cos(x)=x" --range -5 5      -> 0.739085133215161 (numeric)
solve "2^x=8" --range 0 10         -> 3
```

---

## 3. stats - descriptive statistics

```
calc.cmd stats <number> [<number> ...] [--file PATH] [--stdin] [--digits 30]
```

Inputs may be integers, decimals (`0.375`) or fractions (`1/3`), separated by
spaces, commas, newlines or a file. All internal work is exact rational
arithmetic.

Reported: `count`, `sum`, `mean`, `median`, `mode` (list, empty when every value
is unique), `min`, `max`, `range`, `q1`, `q3`, `iqr`, `variance_population`,
`variance_sample`, `stddev_population`, `stddev_sample`, `sum_of_squares`,
`geometric_mean`, `harmonic_mean`, `sorted`, plus the plain-fraction strings
`variance_population_exact` / `variance_sample_exact`.

* Sample variance needs n ≥ 2 (`null` otherwise).
* Standard deviation is exact when the square root is exact (`sqrt(14)/2`);
  otherwise it is high-precision approximate with a note.
* Quantiles: linear interpolation, `index = p*(n-1)` between order statistics.
* Geometric mean is exact only when the n-th root of the product is exact.

```
stats 1 2 3 4 5 6        -> mean 7/2, variance_population 35/12, stddev_sample sqrt(14)/2
stats 1/3 2/3 1          -> mean 2/3, harmonic_mean 6/11, stddev_population sqrt(6)/9
stats 1 2 2 3            -> mode ["2"], q1 7/4, q3 9/4
stats --file data.txt    -> one number or thousands-separated tokens per line
```

---

## 4. base - base conversion (2..36)

```
calc.cmd base <value> [--from B] [--to B] [--digits N]
```

* `--from` defaults to auto-detection (`0x`/`0b`/`0o`, otherwise decimal).
* Integers of any size convert exactly; fractional parts convert with exact
  recurring-block detection.
* Result fields: `result` (with `(...)` marking the repeating block),
  `exact`, `integer_part`, `fractional_digits`
  (`terminating` | `recurring` | `truncated`), `fraction`, `decimal_value`,
  `round_trip_value` (independent verification), `note`.

```
base 255 --to 2              -> 11111111
base 0xFF --to 10            -> 255
base 0.1 --from 10 --to 2    -> 0.0(0011)   exact recurring
base 0.1 --from 10 --to 3    -> 0.(0022)
base 0.5 --from 10 --to 2    -> 0.1         terminating
base 1/3 --from 10 --to 2    -> error: base conversion needs a plain numeral; use decimal/fraction for rationals
base 1000000000000000000000000 --to 36
base 12 --from 2 --to 10     -> error: digit '2' invalid in base 2
```

---

## 5. fraction / decimal - exact representation

```
calc.cmd fraction <decimal|fraction>      # 0.375 -> 3/8, "0.1(6)" -> 1/6
calc.cmd decimal <fraction|decimal> [--digits N]   # 1/7 -> 0.(142857)
```

`fraction` adds `numerator`, `denominator`, their prime factorisations, and
`is_terminating_decimal`. `decimal` reports `kind`
(`integer`|`terminating`|`recurring`|`rounded`) and `exact`. Recurring input
notation `0.1(6)` and `-3.(142857)` is accepted everywhere numbers are.

---

## 6. factor / primes - number theory

```
calc.cmd factor <integer> [--max-steps N]
calc.cmd primes <lo> <hi> [--limit N]
```

`factor` returns `factorization` (`2^3 * 3^2 * 5`), `factors`, `prime_factors`,
`is_prime`, `is_perfect_square` (+ `square_root`), `divisor_count`,
`divisor_sum`, `euler_phi`, and `divisors` when there are at most 100.
Trial division + Miller-Rabin + Pollard's rho handle large integers;
`--max-steps` bounds the rho effort and a hard semiprime returns
`"factorization": null` with a `note` instead of hanging.

```
factor 360                        -> 2^3 * 3^2 * 5, divisor_count 24, euler_phi 96
factor 1                          -> "1 (no prime factors)", divisor_count 1, euler_phi 1
factor 2^127-1                    -> prime (detected instantly)
primes 100 120                    -> 101, 103, 107, 109, 113
```

---

## 7. units - unit conversion

```
calc.cmd units <value> <from_unit> --to <to_unit>
calc.cmd units --list
```

Categories and sample units:

| Category | Units |
|---|---|
| length | `m km cm mm um nm in ft yd mi nmi` |
| mass | `kg g mg ug t lb oz` |
| time | `s min h day week year` |
| area | `m2 km2 cm2 ft2 ha acre` |
| volume | `m3 l ml cm3 cc gal qt pt cup` |
| speed | `mps kph mph knot` |
| data | `bit b B byte kb mb gb tb kib mib gib` |
| energy | `j kj cal kcal wh kwh` |
| pressure | `pa kpa mpa bar atm mmhg psi` |
| temperature | `c f k` (affine, exact) |
| angle | `deg grad turn rad` |

Multiplicative conversions are exact fractions (`100 km` → `781250/12573 mi`);
temperature is affine and exact (`100 c` → `212 f`, `0 c` → `5463/20 k`);
radians involve `pi` and are approximate (`180 deg` → `3.14159... rad`).
Mixing categories (or unknown units) is an error.
Pressure definitions use their exact values: `1 psi` → `8896443230521/1290320000 Pa`,
`1 atm` → `101325 Pa`, `1 bar` → `100000 Pa`, `1 mmHg` → `26664477483/200000000 Pa`
(133.322387415 Pa) and `1 torr` → `20265/152 Pa` (1/760 atm) - mmHg and torr are
deliberately **not** conflated.

---

## 8. round / verify

```
calc.cmd round "<expr>" -d <decimal places>     # half away from zero
calc.cmd verify "<expr A>" "<expr B>"
```

`verify` decides equality **symbolically** when both sides are exact
(`sqrt(2)^2` = `2` → `exact_equal: true`, difference `0`; `1/3` vs `0.333` →
`false`, difference `1/3000`) and otherwise compares at `--prec` digits
(tolerance `10^-(prec-5)`).

---

## 9. batch - many jobs in one process

```
calc.cmd batch [--file PATH]     # reads stdin (or a file), one job per line
```

Each line is either a bare expression (evaluated) or a JSON job object:

```json
{"cmd": "eval",    "expr": "2^10",  "prec": 30, "digits": 30}
{"cmd": "verify",  "left": "sqrt(2)^2", "right": "2"}
{"cmd": "solve",   "equation": "x^2-4=0", "complex": false}
{"cmd": "stats",   "values": ["1", "2", "3"]}
{"cmd": "base",    "value": "255", "from": 10, "to": 2}
{"cmd": "units",   "value": "100", "from": "km", "to": "mi"}
{"cmd": "fraction","value": "0.375"}
{"cmd": "decimal", "value": "1/7", "digits": 50}
{"cmd": "factor",  "value": "360"}
```

The response is `{"ok": true, "count": N, "results": [...]}` in input order;
one failing job does not abort the rest (`{"ok": false, "error": {...}}` in its
slot). Blank lines and `#` comments are ignored.

---

## 10. help / funcs

```
calc.cmd help [command]      # usage for one command or the command list
calc.cmd funcs               # machine-readable function catalogue + examples
```

---

## 11. Exactness cheat sheet

| Stays exact | Becomes approximate |
|---|---|
| any-size integers, `n!`, `2^1000` | `pi`, `e`, `tau` |
| fractions `3/4`, finite decimals `0.1` | `sin cos tan asin acos atan`, `exp ln log` |
| `+ - * / // % ^` over the above | `sqrt` of an irrational expression (`sqrt(1+sqrt(2))`) |
| `sqrt(3/4)` → `sqrt(3)/2`, `sqrt(8)` → `2*sqrt(2)` | `root(2,3)`, non-perfect roots |
| integer roots of perfect powers | radian unit conversions, `gamma` |
| rationalised denominators `1/(1+sqrt(2))` → `sqrt(2)-1` | numeric roots of non-polynomial equations |
| `floor/ceil/round` of any exact value | |
| mean/variance/harmonic mean of rational data; stddev when the root is exact | geometric mean unless the root is exact |

When a value is approximate, either report it as approximate or raise `--prec`
and `--digits`; never present a rounded decimal as if it were exact.

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `error.type: calc_error`, "unknown variable" | bind it: `--var x=2` |
| `error.type: calc_error`, "unknown function" | run `calc.cmd funcs` |
| `error.type: calc_error`, "division by zero" | the expression divides by zero; reformulate |
| `error.type: usage_error`, exit code 2 | wrong flags/arguments; `calc.cmd help <command>` |
| `kind: "approximate"` when exactness was expected | the expression leaves the exact field (`pi`, `sin`, non-perfect roots); say so or restructure the maths |
| `solve` returns fewer roots than expected | numeric scanning only covers `--range`; widen it or raise `--samples` |
| `factor` returns `factorization: null` | the number has very large prime factors; raise `--max-steps` or factor parts separately |
| `base` says `fractional_digits: truncated` | the expansion does not terminate; raise `--digits` or keep the exact `fraction` |
| `exact: null` with a `numerator_digits` field | the result has more than ~200000 digits and is described instead of printed |
| `error.type: recursion_limit` | the expression is nested too deeply; split it or use `batch` |
| `--complex` changed nothing | the equation is not polynomial, so the scan only finds real roots (see the `note`) |
| "result is too large to render as a decimal string" | more than 200000 digits; report a scaled, factored or logarithmic form instead |
| Non-zero exit with JSON error | read `error.message`; do not invent a value |

Edge cases worth knowing: `0^0` is `1` (Python convention), `0^-1` is an error,
`-2^2` is `-4`, `2^3^2` is `512`, `-7 % 3` is `2` and `-7 // 3` is `-3` (floor
semantics), `round(x)` rounds half away from zero, `sqrt()` of a negative number
is an error (use `solve ... --complex` for complex roots), and results with more
than 200000 digits are refused rather than truncated.

## 13. Verification harness

```
python <skill>/tests/test_calc.py            # 95 tests, ~10 s
python -m unittest discover -s <skill>/tests -t <skill>
```

Covers exact arithmetic identities, parser edge cases, high-precision constants,
solver paths, statistics, base conversion, units and the CLI JSON contract.
