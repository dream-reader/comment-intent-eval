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
- [ ] M1 构造并标注评测集（初稿 200 条已完成，人工复核中）
- [ ] M2 Agent v1
- [ ] M3 契约层 + 分类指标 + 报告
- [ ] M4 稳定性 + 蜕变测试 + LLM 裁判及校准
- [ ] M5 实验与结论
- [ ] M6 文档整理

## 数据说明

`data/sellers/` 下的公司和产品**全部是虚构的**，评测集里的评论也全部是构造的，不来自任何真实企业或用户。

评测集（`data/eval/`）由 AI 辅助构造并按[标注指南](docs/labeling-guide.md)预标注，再由作者人工逐条复核。为检验标签本身是否可靠，另抽 50 条由作者在不看预标注的情况下盲标（`data/blind/`），计算一致率。

校验评测集：`python scripts/validate_dataset.py`

## 运行

```bash
pip install -e ".[dev]"
cp .env.example .env   # 填入 DeepSeek API Key
```

（运行命令随 M2、M3 补充）
