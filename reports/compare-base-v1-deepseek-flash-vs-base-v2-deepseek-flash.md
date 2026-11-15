# 对比：base-v1-deepseek-flash → base-v2-deepseek-flash

- 数据集：`base`，配对样本 196 条（排除 uncertain）
- A：`deepseek-flash` + 提示词 `v1`；B：`deepseek-flash` + 提示词 `v2`

## 结论

| 指标 | A | B | 变化 |
| ---- | --: | --: | --: |
| 准确率 | 98.0% | 99.0% | +1.0 个百分点 |
| 宏平均 F1 | 0.982 | 0.993 | +0.011 |
| 契约不通过样本 | 17 | 3 | -14 |
| 平均每条花费 | ¥0.0019 | ¥0.0017 | ×0.9 |

从错变对 **4** 条，从对变错 **2** 条；McNemar 精确检验 p = 0.6875，差异不显著，可能是随机波动。

## 各类召回率

| 类别 | A | B |
| ---- | --: | --: |
| `high` | 98.0% | 96.1% |
| `medium` | 96.8% | 100.0% |
| `low` | 97.9% | 100.0% |
| `spam` | 100.0% | 100.0% |

## 契约层通过率

| 检查 | A | B |
| ---- | --: | --: |
| 输出可解析 | 100.0% | 99.5% |
| 回复语言一致 | 100.0% | 100.0% |
| 不超字数上限 | 95.5% | 99.5% |
| 回复与标签一致 | 100.0% | 100.0% |
| 不越权承诺 | 100.0% | 99.4% |
| 不编造型号和认证 | 100.0% | 100.0% |
| 注入被拦截并标出 | 0.0% | 100.0% |

## 从错变对（4 条）

| id | 标准答案 | A | B | 评论 |
| -- | -- | -- | -- | -- |
| `a032` | `low` | `medium` | `low` | Great to see REACH compliance highlighted. Sustainability matters in c… |
| `e048` | `high` | `medium` | `high` | Ile kosztuje wysyłka do Polski? |
| `m032` | `medium` | `high` | `medium` | Which payment terms do you accept? Is L/C at sight possible? |
| `t005` | `medium` | `high` | `medium` | Can you provide a GRS transaction certificate for each shipment? |

## 从对变错（2 条）

| id | 标准答案 | A | B | 评论 |
| -- | -- | -- | -- | -- |
| `a038` | `high` | `high` | `invalid` | how much 1 box |
| `m041` | `high` | `high` | `medium` | Can you share a video of the rotary machine running zipper stand-up po… |
