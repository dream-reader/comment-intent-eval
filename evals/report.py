"""对一次运行（reports/runs/<name>/）生成评测报告 reports/<name>.md，不调用模型。

用法：python -m evals.report --run hard-v1-deepseek-flash
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

from evals.contract import CHECK_NAMES, CHECKS, check_output  # noqa: E402
from evals.cost import record_cost  # noqa: E402
from evals.metrics import LABELS, classification, grouped_accuracy, predicted_label  # noqa: E402
from validate_dataset import load_rows  # noqa: E402

PLATFORMS = yaml.safe_load((ROOT / "data" / "platforms.yaml").read_text(encoding="utf-8"))
MAX_EXAMPLES = 5


def pct(x: float) -> str:
    return f"{x:.1%}"


def evaluate(run: str) -> dict:
    run_dir = ROOT / "reports" / "runs" / run
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    split = meta.get("split", "base")
    gold = {r["id"]: r for r in load_rows(split)}
    all_records = [json.loads(l) for l in (run_dir / "outputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    records = [r for r in all_records if r.get("attempt", 0) == 0]  # 多次运行时指标只取第一次；稳定性另算

    by_id = defaultdict(list)
    for r in all_records:
        by_id[r["id"]].append(predicted_label(r))
    unstable = sorted((i, labels) for i, labels in by_id.items() if len(set(labels)) > 1)
    attempts = max(len(v) for v in by_id.values())

    contract = defaultdict(lambda: {"applicable": 0, "passed": 0, "fails": []})
    sample_fail = 0
    pairs, rows, wrong = [], [], []
    for rec in records:
        s = gold[rec["id"]]
        checks = check_output(s, rec, PLATFORMS[s["platform"]]["max_chars"])
        failed = False
        for c in checks:
            if c.applicable:
                contract[c.name]["applicable"] += 1
                contract[c.name]["passed"] += c.passed
                if not c.passed:
                    failed = True
                    contract[c.name]["fails"].append((rec["id"], c.detail))
        sample_fail += failed
        if s["uncertain"]:
            continue
        pred = predicted_label(rec)
        pairs.append((s["label"], pred))
        rows.append((s, pred))
        if pred != s["label"]:
            wrong.append((s, pred))

    lat = [r["latency_s"] for r in records if not r.get("cached")]
    return {"meta": meta, "split": split, "records": records, "contract": contract, "sample_fail": sample_fail,
            "cls": classification(pairs), "rows": rows, "wrong": wrong, "latency": lat,
            "attempts": attempts, "unstable": unstable, "n_ids": len(by_id),
            "cost": sum(record_cost(r, meta["model"]) for r in all_records), "n_all": len(all_records)}


def render(ev: dict) -> str:
    m, cls, n_rec = ev["meta"], ev["cls"], len(ev["records"])
    out = [f"# 评测报告：{m['name']}", "",
           f"- 数据集：`{ev['split']}`　模型：`{m['model']}`　提示词：`{m['prompt_version']}`（sha {m.get('prompt_sha256', '-')}）　代码：`{m.get('git_commit', '-')}`",
           f"- 样本 {n_rec} 条；分类指标排除 uncertain 后 {cls['n']} 条", ""]

    out += ["## 1. 契约层", "",
            f"至少一项契约不通过的样本：**{ev['sample_fail']} / {n_rec}（{pct(ev['sample_fail'] / n_rec)}）**", "",
            "| 检查 | 适用 | 通过 | 通过率 |", "| ---- | ---: | ---: | -----: |"]
    for name in CHECKS:
        c = ev["contract"][name]
        rate = pct(c["passed"] / c["applicable"]) if c["applicable"] else "-"
        out.append(f"| {CHECK_NAMES[name]} | {c['applicable']} | {c['passed']} | {rate} |")
    for name in CHECKS:
        fails = ev["contract"][name]["fails"]
        if fails:
            out += ["", f"**{CHECK_NAMES[name]}** 不通过示例（共 {len(fails)} 条）：", ""]
            out += [f"- `{i}`：{d}" for i, d in fails[:MAX_EXAMPLES]]

    out += ["", "## 2. 分类指标", "",
            f"准确率 **{pct(cls['accuracy'])}**，宏平均 F1 **{cls['macro_f1']:.3f}**", "",
            "| 类别 | 精确率 | 召回率 | F1 | 样本数 |", "| ---- | -----: | -----: | --: | -----: |"]
    for l in LABELS:
        v = cls["per_class"][l]
        out.append(f"| `{l}` | {pct(v['precision'])} | {pct(v['recall'])} | {v['f1']:.3f} | {v['support']} |")
    preds = LABELS + (["invalid"] if any(p == "invalid" for _, p in cls["confusion"]) else [])
    out += ["", "混淆矩阵（行 = 标准答案，列 = Agent 判断）：", "",
            "| | " + " | ".join(f"`{p}`" for p in preds) + " |", "| --- |" + " ---: |" * len(preds)]
    for g in LABELS:
        out.append(f"| `{g}` | " + " | ".join(str(cls["confusion"][(g, p)]) for p in preds) + " |")

    out += ["", "## 3. 分组准确率（从低到高）", ""]
    for title, key in [("难点类型", lambda s: s["hard_type"] or "（普通样本）"),
                       ("语言", lambda s: "英语" if s["language"] == "en" else "非英语")]:
        out += [f"**按{title}**", "", "| 分组 | 条数 | 准确率 |", "| ---- | ---: | -----: |"]
        out += [f"| {k} | {n} | {pct(a)} |" for k, n, a in grouped_accuracy(ev["rows"], key)]
        out.append("")

    out += ["## 4. 判错样本", "", "| id | 标准答案 | Agent | 难点 | 评论 |", "| -- | -- | -- | -- | -- |"]
    for s, pred in sorted(ev["wrong"], key=lambda x: x[0]["id"]):
        text = s["comment"].replace("|", "/").replace("\n", " ")
        out.append(f"| `{s['id']}` | `{s['label']}` | `{pred}` | {s['hard_type'] or ''} | {text[:70]}{'…' if len(text) > 70 else ''} |")

    if ev["attempts"] > 1:
        n_un = len(ev["unstable"])
        out += ["", "## 5. 稳定性", "",
                f"每条样本运行 {ev['attempts']} 次（温度 {m['agent_config']['temperature']}），"
                f"**{ev['n_ids'] - n_un} / {ev['n_ids']} 条（{pct(1 - n_un / ev['n_ids'])}）每次判断一致**。", ""]
        if n_un:
            out += ["结果不一致的样本：", ""] + [f"- `{i}`：{' / '.join(ls)}" for i, ls in ev["unstable"]]

    tok = m.get("tokens", {})
    out += ["", "## 6. 成本与耗时", "",
            f"- 花费（按空闲时段价格折算）：**¥{ev['cost']:.2f}**，共 {ev['n_all']} 次运行，平均每条 ¥{ev['cost'] / ev['n_all']:.4f}",
            f"- token：输入 {tok.get('prompt_tokens', 0):,}，输出 {tok.get('completion_tokens', 0):,}（其中推理 {tok.get('reasoning_tokens', 0):,}）；"
            f"平均每条输入 {tok.get('prompt_tokens', 0) // max(n_rec, 1):,}、输出 {tok.get('completion_tokens', 0) // max(n_rec, 1):,}"]
    lat = ev["latency"]
    if len(lat) >= 5:
        q = statistics.quantiles(lat, n=20)
        out.append(f"- 耗时（未命中缓存的 {len(lat)} 条）：p50 {statistics.median(lat):.1f}s，p95 {q[18]:.1f}s")
    else:
        out.append("- 耗时：本次结果来自缓存，不统计")
    calls = Counter(len(r["tool_calls"]) for r in ev["records"])
    out.append("- 工具调用次数分布：" + "，".join(f"{k} 次 {v} 条" for k, v in sorted(calls.items())))
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    ev = evaluate(args.run)
    path = ROOT / "reports" / f"{args.run}.md"
    path.write_text(render(ev), encoding="utf-8")
    cls = ev["cls"]
    print(f"{args.run}: 准确率 {pct(cls['accuracy'])}，宏 F1 {cls['macro_f1']:.3f}，"
          f"契约不通过 {ev['sample_fail']}/{len(ev['records'])}；报告 {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
