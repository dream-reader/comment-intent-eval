"""对比同一数据集上的两次运行（如提示词 v1 vs v2，或 flash vs pro），生成 reports/compare-<a>-vs-<b>.md。

- 配对比较：只看两次都有结果、标准答案可靠（非 uncertain）的样本，取每条的第一次运行
- 翻转清单：从错变对、从对变错的样本
- 显著性：McNemar 精确检验（只看两次结果不一致的样本，检验「变好」和「变坏」是否对称）
- 契约层与花费并排

用法：python -m evals.compare --a holdout-v1-deepseek-flash --b holdout-v2-deepseek-flash
"""
from __future__ import annotations

import argparse
from pathlib import Path

from scipy.stats import binomtest

from evals.contract import CHECK_NAMES, CHECKS
from evals.report import evaluate, pct

ROOT = Path(__file__).resolve().parents[1]


def compare(a: str, b: str) -> str:
    ea, eb = evaluate(a), evaluate(b)
    assert ea["split"] == eb["split"], "两次运行必须是同一个数据集"
    pa = {s["id"]: (s, p) for s, p in ea["rows"]}
    pb = {s["id"]: (s, p) for s, p in eb["rows"]}
    ids = sorted(set(pa) & set(pb))
    fixed = [i for i in ids if pa[i][1] != pa[i][0]["label"] and pb[i][1] == pb[i][0]["label"]]
    broken = [i for i in ids if pa[i][1] == pa[i][0]["label"] and pb[i][1] != pb[i][0]["label"]]
    acc_a = sum(pa[i][1] == pa[i][0]["label"] for i in ids) / len(ids)
    acc_b = sum(pb[i][1] == pb[i][0]["label"] for i in ids) / len(ids)
    n_disc = len(fixed) + len(broken)
    p_value = binomtest(len(fixed), n_disc, 0.5).pvalue if n_disc else 1.0
    verdict = "差异显著（p < 0.05）" if p_value < 0.05 else "差异不显著，可能是随机波动"

    ma, mb = ea["meta"], eb["meta"]
    out = [f"# 对比：{a} → {b}", "",
           f"- 数据集：`{ea['split']}`，配对样本 {len(ids)} 条（排除 uncertain）",
           f"- A：`{ma['model']}` + 提示词 `{ma['prompt_version']}`；B：`{mb['model']}` + 提示词 `{mb['prompt_version']}`", "",
           "## 结论", "",
           f"| 指标 | A | B | 变化 |", "| ---- | --: | --: | --: |",
           f"| 准确率 | {pct(acc_a)} | {pct(acc_b)} | {(acc_b - acc_a) * 100:+.1f} 个百分点 |",
           f"| 宏平均 F1 | {ea['cls']['macro_f1']:.3f} | {eb['cls']['macro_f1']:.3f} | {eb['cls']['macro_f1'] - ea['cls']['macro_f1']:+.3f} |",
           f"| 契约不通过样本 | {ea['sample_fail']} | {eb['sample_fail']} | {eb['sample_fail'] - ea['sample_fail']:+d} |",
           f"| 平均每条花费 | ¥{ea['cost'] / ea['n_all']:.4f} | ¥{eb['cost'] / eb['n_all']:.4f} | ×{(eb['cost'] / eb['n_all']) / max(ea['cost'] / ea['n_all'], 1e-9):.1f} |",
           "",
           f"从错变对 **{len(fixed)}** 条，从对变错 **{len(broken)}** 条；McNemar 精确检验 p = {p_value:.4f}，{verdict}。", "",
           "## 各类召回率", "", "| 类别 | A | B |", "| ---- | --: | --: |"]
    for label in ["high", "medium", "low", "spam"]:
        out.append(f"| `{label}` | {pct(ea['cls']['per_class'][label]['recall'])} | {pct(eb['cls']['per_class'][label]['recall'])} |")

    out += ["", "## 契约层通过率", "", "| 检查 | A | B |", "| ---- | --: | --: |"]
    for name in CHECKS:
        ca, cb = ea["contract"][name], eb["contract"][name]
        ra = pct(ca["passed"] / ca["applicable"]) if ca["applicable"] else "-"
        rb = pct(cb["passed"] / cb["applicable"]) if cb["applicable"] else "-"
        out.append(f"| {CHECK_NAMES[name]} | {ra} | {rb} |")

    for title, group in [("从错变对", fixed), ("从对变错", broken)]:
        out += ["", f"## {title}（{len(group)} 条）", ""]
        if group:
            out += ["| id | 标准答案 | A | B | 评论 |", "| -- | -- | -- | -- | -- |"]
            for i in group:
                s = pa[i][0]
                text = s["comment"].replace("|", "/").replace("\n", " ")
                out.append(f"| `{i}` | `{s['label']}` | `{pa[i][1]}` | `{pb[i][1]}` | {text[:70]}{'…' if len(text) > 70 else ''} |")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    args = ap.parse_args()
    path = ROOT / "reports" / f"compare-{args.a}-vs-{args.b}.md"
    text = compare(args.a, args.b)
    path.write_text(text, encoding="utf-8")
    print(text.split("## 各类召回率")[0])
    print("报告：", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
