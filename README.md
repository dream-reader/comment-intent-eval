# comment-intent-eval

外贸社媒评论意向分级 Agent，以及围绕它的一套分层评测。

> English: An LLM agent that classifies purchase intent in B2B social media comments and drafts replies, with a layered evaluation harness (contract checks, classification metrics, stability, metamorphic tests, calibrated LLM-as-judge, and regression comparison). Runs on DeepSeek.

**项目重点是评测，不是 Agent。** Agent 刻意做得很简单，评测体系才是主角。

## 场景

外贸企业在 LinkedIn、Facebook、Instagram、TikTok 上发产品帖，评论区里有各种语言的评论：有询价的，有问规格的，有点赞的，也有同行来引流的。Agent 读一条评论，结合帖子内容和卖家的产品目录，完成两件事：

1. 判断意向等级：`high` / `medium` / `low` / `spam`
2. 起草一条建议回复（`spam` 不回复）

## 评测分层

| 层       | 检查什么                                     | 方法                         |
| -------- | -------------------------------------------- | ---------------------------- |
| 契约层   | 结构、语言、字数、规格不编造、不越权承诺     | 确定性断言，每次都跑         |
| 分类指标 | 准确率、精确率、召回率、F1、混淆矩阵         | 对照人工标注                 |
| 稳定性   | 同一输入多次运行，结果是否一致               | 重复采样                     |
| 方向层   | 输入按规则变换后，结论是否按预期变化         | 蜕变测试                     |
| 质量层   | 回复写得好不好                               | LLM 裁判 + 人工标注校准       |
| 回归对比 | 换提示词或模型后，到底变好还是变坏           | 翻转样本清单 + 显著性检验     |

## 进度

- [x] M0 标签定义、[标注指南](docs/labeling-guide.md)、虚构卖家与产品目录
- [x] M1 评测集：基础集 200 条 + 对抗难例集 80 条
- [ ] M2 Agent v1
- [x] M3 契约层 + 分类指标 + 报告
- [ ] M4 稳定性 + 蜕变测试 + LLM 裁判及校准
- [ ] M5 实验与结论
- [ ] M6 文档整理

## 数据说明

`data/sellers/` 下的公司和产品**全部是虚构的**，评测集里的评论也全部是构造的，不来自任何真实企业或用户。

评测集分两部分：

| 数据集 | 位置 | 条数 | 来源与标注 |
| ------ | ---- | ---- | ---------- |
| 基础集 | `data/eval/` | 200 | AI（Claude）按[标注指南](docs/labeling-guide.md)构造并标注 |
| 难例集 | `data/eval_hard/` | 80 | `deepseek-v4-pro` 针对 9 类难点出题 160 条 → Agent v1 每条跑 3 次探测 → 选出判错或不稳定的 38 条，再随机补 42 条 |

基础集上 Agent v1 的分类准确率约 98%，区分度不够，所以补了难例集。

**难例集的标准答案**由两个不同厂商的模型独立标注后交叉验证：Claude 只看评论原文按指南盲标，与出题方 `deepseek-v4-pro` 的预期标签对比，一致率 87.5%，Cohen's Kappa = 0.83；10 条分歧逐条按指南裁决，裁决结论已补进指南。以 Claude 的标注为主，是为了避免被测模型和标准答案出自同一家厂商。

**局限**：标签全部由 AI 给出，没有经过大规模人工标注；基础集只有一个标注者。

校验评测集：`python scripts/validate_dataset.py base`、`python scripts/validate_dataset.py hard`

## 运行

```bash
pip install -e ".[dev]" langdetect
cp .env.example .env                                   # 填入 DeepSeek API Key

python scripts/validate_dataset.py hard                # 校验评测集
python scripts/run_agent.py --split hard --prompt v1   # 跑 Agent，结果在 reports/runs/<名称>/
python -m evals.report --run hard-v1-deepseek-flash    # 生成评测报告 reports/<名称>.md
python -m pytest tests                                 # 评测代码自身的测试
```

模型调用结果缓存在本地 `cache/llm.sqlite`，重跑报告不会重复花钱。

## 当前结果（v1，deepseek-flash）

| 数据集 | 准确率 | 宏平均 F1 | 契约不通过 | 报告 |
| ------ | -----: | --------: | ---------: | ---- |
| 基础集 | 98.5% | 0.987 | 17 / 200 | [base-v1-deepseek-flash](reports/base-v1-deepseek-flash.md) |
| 难例集 | 66.7% | 0.672 | 27 / 80 | [hard-v1-deepseek-flash](reports/hard-v1-deepseek-flash.md) |

- 难例集上 27 条 `spam` 只识别出 7 条，16 条被当成 `high`：包装成询盘的推销和提示词注入能骗过 Agent
- 含提示词注入的 23 条没有一条被标出（v1 提示词没有这项要求），其中难例集的大多数还给了回复
- 契约层主要问题是回复超过平台字数上限（基础集 9 条、难例集 14 条）
- 难例集有一半是专门挑 v1 判错的样本，这个准确率不代表真实水平，只用于比较版本间的改进
