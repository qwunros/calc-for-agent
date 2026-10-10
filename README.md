# calc for agent — 科学计算 Skill

给 AI Agent 使用的**精确科学计算**技能。核心是一个纯 Python 标准库实现的命令行计算器
（无需 sympy / mpmath / numpy），**尽可能保留精确值**：分数、有限小数、任意规模整数、
根号（如 `sqrt(8) = 2*sqrt(2)`）以及特殊角的三角函数值都保持精确形式；只有真正无法
精确表示的结果才会标注为近似值，并给出高精度小数（最高 2000 位）。

## 安装位置

```
calc-for-agent\
├── SKILL.md                    # Agent 使用契约（触发条件 + 使用方法）
├── references\operations.md    # 完整命令/函数/边界情况参考（按需读取）
├── scripts\                    # 计算实现（纯标准库）
│   ├── calc.py                 # CLI 入口（JSON 输出）
│   ├── calc_core.py            # 精确算术内核（分数/整数/根式/进制/数论）
│   ├── calc_num.py             # Decimal 高精度数值引擎（pi、exp/ln、三角、n 次根）
│   ├── calc_parse.py           # 表达式解析与“先精确后数值”求值
│   └── calc_domains.py         # 方程求解、统计、进制、单位、数论
├── tests\test_calc.py          # 95 项测试
├── calc.cmd / calc             # 启动器（自动定位自身目录）
```

在任意目录下都能调用（Windows）：

```powershell
& "calc-for-agent\calc.cmd" eval "1/3 + 1/6"
```

或直接调用 Python（参数传递最稳，推荐）：

```powershell
python "calc-for-agent\scripts\calc.py" eval "1/3 + 1/6"
```

> Windows 提示：从 PowerShell 经 `calc.cmd` 调用时，`cmd.exe` 会吞掉 `^`，
> `eval "2^256"` 会变成 `2256`。幂运算请写 `**` 或 `pow(a,b)`
> （`2**256`、`pow(2,256)`），或直接调用 `scripts\calc.py`（直接调用时 `^` 正常）。

## 功能与示例

| 能力 | 命令 | 结果 |
|---|---|---|
| 精确分数 | `eval "1/3 + 1/6"` | `1/2` |
| 十进制精确运算 | `eval "0.1 + 0.2"` | `3/10`（不是 0.30000000000000004） |
| 大整数 / 阶乘 | `eval "2**256"`、`eval "100!"` | 精确整数（`factorial(20000)` 亦可） |
| 精确根号 | `eval "sqrt(8)+sqrt(18)"` | `5*sqrt(2)` |
| 分母有理化 | `eval "1/(sqrt(2)+sqrt(3))"` | `-sqrt(2) + sqrt(3)` |
| 高精度常数 | `eval "pi" --prec 60 --digits 50` | 50 位正确数字 |
| 特殊角精确值 | `eval "sin(pi/6)"` | `1/2`（精确） |
| 三角/对数 | `eval "log(1024,2)"` | 高精度近似（Decimal 级数） |
| 方程求解 | `solve "x**2-5x+6=0"` | 精确根 `2`、`3` |
| 无理根 | `solve "x**2-x-1=0"` | `sqrt(5)/2 + 1/2`、`-sqrt(5)/2 + 1/2` |
| 复数根 | `solve "x**2+1=0" --complex` | `i`、`-i` |
| 超越方程 | `solve "cos(x)=x" --range -5 5` | 数值根 `0.739085133215160641655312088` |
| 统计 | `stats 1 2 3 4 5 6` | 均值 `7/2`、总体方差 `35/12`、样本标准差 `sqrt(14)/2` |
| 统计（根式） | `stats 1 2` | 几何平均 `sqrt(2)`（精确） |
| 进制转换 | `base 255 --to 2`、`base 0.1 --from 10 --to 2` | `11111111`、`0.0(0011)`（循环节精确） |
| 小数↔分数 | `fraction 0.375`、`decimal 1/7` | `3/8`、`0.(142857)` |
| 数论 | `factor 360`、`primes 100 120` | `2^3 * 3^2 * 5`、`divisor_count 24`、`euler_phi 96` |
| 单位换算 | `units 100 km --to mi`、`units 100 c --to f` | `781250/12573`、`212` |
| 单位（压力） | `units 1 psi --to pa` | `8896443230521/1290320000`（精确定义） |
| 校验断言 | `verify "sqrt(2)**2" "2"` | `equal: true` |
| 批量计算 | `batch` | 每行一个表达式/JSON，一个进程算完 |

完整参考见 `references/operations.md`（函数表、全部选项、精确性对照表、边界情况、排错表）。

## 输出契约（Agent 用）

每条命令在 stdout 输出**一个 JSON 对象**：

```json
{"ok": true, "command": "eval", "kind": "exact", "exact": "5*sqrt(2)",
 "approx": "7.07106781186547524400844362105", "float": 7.071067811865476,
 "input": "sqrt(8)+sqrt(18)", "exact_available": true}
```

* `exact`：精确形式（整数 / `n/d` 分数 / 根式）；`kind` 为 `approximate` 时
  `exact` 为 `null`，应把结果说明为近似值。
* 出错时 `{"ok": false, "error": {"type": ..., "message": ...}}`；
  计算错误退出码 `1`，用法错误退出码 `2`，stdout 始终是 JSON
  （仅 `help` 与 `--help`/`--version` 输出纯文本）。
* `--text` 输出人类可读格式，`--pretty` 美化 JSON；`--prec` 控制计算精度，
  `--digits` 控制打印位数（默认均为 30，分别上限 2000 / 5000）。

## 精确与近似的边界

* **精确**：任意大整数、分数、有限小数及其 `+ - * / // % **` 组合；有理数的
  `sqrt` 与完全幂的整数次根；`sin/cos/tan` 在 `pi/6`、`pi/4` 倍数处；
  `floor/ceil/round`；有理数据的均值/方差/调和平均；平方根可开尽的标准差
  （如 `sqrt(14)/2`）。
* **近似**：`pi`、`e`、`ln`、`exp`、非特殊角的三角函数、反三角/双曲函数、
  非完全根、无理表达式的平方根、弧度换算、`gamma`（约 15 位有效数字）。
  近似结果一律带 `kind: "approximate"`，可提高 `--prec`/`--digits` 获取更多位数。
* 超过约 20 万位的结果（如 `factorial(100000)`）不会展开成字符串，而是返回
  `exact: null` 并附带 `approx`、`numerator_digits` 与说明字段。

## 测试与验证

覆盖精确算术恒等式、解析器边界、高精度常数（与独立实现比对）、方程各求解路径、
统计、进制、单位换算，以及 CLI 的 JSON 契约与退出码。此外该技能经过一轮独立的
对抗性验证（sqrt 恒等式、pi/e 等常数 55 位以上比对、大角度三角、8 组统计数据、
16 组进制转换、单位因子、数论分解与 CLI 契约），发现的问题均已修复并回归测试。

## Contributors  

由Cozylime想出的主意。  
> 现在的LLM经常算错，不如给Agent配个计算器吧！  
> ——Cozylime

使用了`DeepSeek Harness`和`DeepSeek V4.1 Flash`制作。  
