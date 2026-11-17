# comment-intent-eval

外贸社媒评论意向分级 Agent，以及围绕它的一套分层评测。

> English: An LLM agent that classifies purchase intent in B2B social media comments and drafts replies, with a layered evaluation harness (contract checks, classification metrics, stability runs, and regression comparison with significance testing). Runs on DeepSeek.
>
> **Read the English case study: [docs/case-study-en.md](docs/case-study-en.md)**. On a held-out set the prompt never saw, accuracy went from 84.7% to 98.0% (13 fixed, 0 broken, McNemar p = 0.0002), spam recall from 40.9% to 100%, and 8/8 prompt injections were flagged.

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
- [ ] M4 LLM 裁判评回复质量及校准（精简版；蜕变测试不做）
- [x] M5 提示词 v2 + 留出集验证 + 版本对比（McNemar）+ 稳定性
- [ ] M6 文档整理

## 数据说明

`data/sellers/` 下的公司和产品**全部是虚构的**，评测集里的评论也全部是构造的，不来自任何真实企业或用户。

评测集分三部分：

| 数据集 | 位置 | 条数 | 来源与标注 |
| ------ | ---- | ---- | ---------- |
| 基础集 | `data/eval/` | 200 | AI（Claude）按[标注指南](docs/labeling-guide.md)构造并标注 |
| 难例集 | `data/eval_hard/` | 80 | `deepseek-v4-pro` 针对 9 类难点出题 160 条 → Agent v1 每条跑 3 次探测 → 选出判错或不稳定的 38 条，再随机补 42 条 |
| 留出集 | `data/eval_holdout/` | 100 | `deepseek-v4-pro` 每个卖家重新出题 25 条，**不按任何版本的失败挑选**、全部保留，提示词 v2 改版时没见过 |

基础集上 Agent v1 的分类准确率约 98%，区分度不够，所以补了难例集。

**难例集的标准答案**由两个不同厂商的模型独立标注后交叉验证：Claude 只看评论原文按指南盲标，与出题方 `deepseek-v4-pro` 的预期标签对比，一致率 87.5%，Cohen's Kappa = 0.83；10 条分歧逐条按指南裁决，裁决结论已补进指南。以 Claude 的标注为主，是为了避免被测模型和标准答案出自同一家厂商。

**留出集的标准答案**用同样的方法：Claude 盲标，与出题方预期标签一致 98/100，Cohen's Kappa = 0.97，以 Claude 的标注为准。原始标签在 `data/holdout/candidates.jsonl`（出题方预期）和 `data/holdout/labels-claude.jsonl`（盲标）。

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

## 当前结果：提示词 v1 → v2（deepseek-flash）

| 数据集 | v1 准确率 | v2 准确率 | 翻转（错→对 / 对→错） | McNemar p | 契约不通过 | 每条花费 |
| ------ | --------: | --------: | --------------------: | --------: | ---------: | -------: |
| 留出集（100，改版时没见过） | 84.7% | **98.0%** | 13 / 0 | 0.0002 | 24 → 1 | ¥0.0027 → ¥0.0021 |
| 难例集（80） | 66.7% | 100% | 26 / 0 | <0.0001 | 27 → 3 | ¥0.0026 → ¥0.0018 |
| 基础集（200） | 98.0% | 99.0% | 4 / 2 | 0.69（不显著） | 17 → 3 | ¥0.0019 → ¥0.0017 |

同一条样本跑 3 次结果一致的比例：难例集 v1 82.5% → v2 96.2%，留出集 v2 98.0%。花费按空闲时段价格折算。

**怎么读这张表**

- v1 的主要问题：包装成询盘的推销、夹在询价里的提示词注入，会被当成高意向询盘（难例集 27 条 `spam` 只识别 7 条），注入一条都没标出，回复常超字数
- v2 针对这些写了通用规则（注入识别、「在推销就是 spam」、边界规则、回复限长），并新增 `injection` 输出
- **难例集上的 100% 有过拟合嫌疑**：v2 的边界规则是在裁决难例集标注分歧时总结出来的。所以另做了留出集：重新出题、不按任何版本的失败挑选、全部保留，v2 改版时没见过。留出集上 84.7% → 98.0%、13 条改对 0 条改错，才是改进成立的证据
- 基础集已经饱和，v1 和 v2 的差异不显著

**v2 仍有的问题**：基础集 `a038`（"how much 1 box"）输出了不合法的 JSON；`m041`（要分享视频并在比较供应商）被降成 `medium`；留出集 2 条判错。

**一处标准答案修订（如实记录）**：v2 对比时发现指南自相矛盾：基础集 `e048`「运费多少」原标 `medium`，与后来补充的「价格条款算询价」冲突。统一口径为「问运费也是询价，`high`」，在看到 v2 结果之后修改，修订前后基础集 v2 准确率为 98.5% / 99.0%。

各次运行的详细报告和对比报告都在 [reports/](reports/)。
