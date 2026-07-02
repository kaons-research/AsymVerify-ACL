#!/usr/bin/env python3
"""Regenerate camera-ready tables from public aggregate artifacts.

This script is intentionally API-free and raw-log-free. It reads the small CSV
files in outputs/camera_ready and regenerates the LaTeX table fragments used
for release auditing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "camera_ready"


def pct(value: float, digits: int = 1) -> str:
    return f"{100 * float(value):.{digits}f}"


def signed_pct(value: float, digits: int = 1) -> str:
    return f"{100 * float(value):+.{digits}f}"


def write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def table_glm_ablation(ablation: pd.DataFrame) -> None:
    glm = ablation[ablation["model"] == "GLM-4.7"].copy()
    order = ["P1", "P1+P2", "P1+P3", "P1+P2+P3"]
    glm["configuration"] = pd.Categorical(glm["configuration"], categories=order, ordered=True)
    glm = glm.sort_values("configuration")
    rows = []
    for row in glm.itertuples(index=False):
        rows.append(
            f"{row.configuration} & {pct(row.macro_f1)} & {pct(row.accuracy)} & "
            f"{float(row.calls_per_example):.2f} & {int(row.p2_activations)} & {int(row.p3_activations)} \\\\"
        )
    write(
        OUT / "table_glm_ablation.tex",
        r"""
\begin{tabular}{lccccc}
\toprule
\textbf{Config.} & \textbf{Macro F1} & \textbf{Acc.} & \textbf{Calls/ex.} & \textbf{P2} & \textbf{P3} \\
\midrule
"""
        + "\n".join(rows)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def table_model_family(ablation: pd.DataFrame) -> None:
    rows = []
    for model in ["GLM-4.7", "DeepSeek-V3.2", "Llama-3.3-70B"]:
        subset = ablation[ablation["model"] == model]
        p1 = subset[subset["configuration"] == "P1"].iloc[0]
        p3 = subset[subset["configuration"] == "P1+P3"].iloc[0]
        full_rows = subset[subset["configuration"] == "P1+P2+P3"]
        full = full_rows.iloc[0] if not full_rows.empty else None
        full_f1 = pct(full.macro_f1) if full is not None else "--"
        rows.append(
            f"{model} & {pct(p1.macro_f1)} & {pct(p3.macro_f1)} & "
            f"{signed_pct(p3.macro_f1 - p1.macro_f1)} & {full_f1} \\\\"
        )
    write(
        OUT / "table_model_family_replication.tex",
        r"""
\begin{tabular}{lcccc}
\toprule
\textbf{Model} & \textbf{P1} & \textbf{P1+P3} & \textbf{$\Delta$} & \textbf{P1+P2+P3} \\
\midrule
"""
        + "\n".join(rows)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def table_confusion(confusion: pd.DataFrame) -> None:
    label_map = {"CR": "CR", "AMB": "AMB", "CNR": "CNR"}
    rows = []
    for row in confusion.itertuples(index=False):
        rows.append(
            f"{label_map[row.true]} & {int(row.pred_cr)} & {int(row.pred_amb)} & {int(row.pred_cnr)} \\\\"
        )
    write(
        OUT / "table_confusion_glm_full.tex",
        r"""
\begin{tabular}{lccc}
\toprule
\textbf{Gold} & \textbf{Pred. CR} & \textbf{Pred. AMB} & \textbf{Pred. CNR} \\
\midrule
"""
        + "\n".join(rows)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def table_confidence(confidence: pd.DataFrame) -> None:
    rows = []
    for row in confidence.itertuples(index=False):
        rows.append(
            f"{row.bin} & {int(row.count)} & {pct(row.accuracy)} & {pct(row.macro_f1)} & {pct(row.error_rate)} \\\\"
        )
    write(
        OUT / "table_confidence_bins_glm.tex",
        r"""
\begin{tabular}{lrrrr}
\toprule
\textbf{Confidence bin} & \textbf{N} & \textbf{Acc.} & \textbf{Macro F1} & \textbf{Error} \\
\midrule
"""
        + "\n".join(rows)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def table_prefilter(prefilter: pd.DataFrame) -> None:
    rows = []
    for row in prefilter.itertuples(index=False):
        rows.append(
            f"{row.variant} & {pct(row.macro_f1)} & {pct(row.accuracy)} & "
            f"{int(row.p3_calls)} & {int(row.false_upgrades)} \\\\"
        )
    write(
        OUT / "table_prefilter_glm.tex",
        r"""
\begin{tabular}{lrrrr}
\toprule
\textbf{Variant} & \textbf{Macro F1} & \textbf{Acc.} & \textbf{P3 calls} & \textbf{False upgrades} \\
\midrule
"""
        + "\n".join(rows)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def table_per_class(per_class: pd.DataFrame) -> None:
    rows = []
    for row in per_class.itertuples(index=False):
        rows.append(
            f"{row.model} & {row.configuration} & {pct(row.clear_reply)} & "
            f"{pct(row.ambivalent)} & {pct(row.clear_non_reply)} \\\\"
        )
    write(
        OUT / "table_per_class_f1_best_variants.tex",
        r"""
\begin{tabular}{llccc}
\toprule
\textbf{Model} & \textbf{Config.} & \textbf{CR F1} & \textbf{AMB F1} & \textbf{CNR F1} \\
\midrule
"""
        + "\n".join(rows)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def table_bootstrap(bootstrap: pd.DataFrame) -> None:
    rows = []
    for row in bootstrap.itertuples(index=False):
        rows.append(
            f"{row.comparison} & {signed_pct(row.delta)} & "
            f"[{signed_pct(row.ci_low)}, {signed_pct(row.ci_high)}] & {int(row.samples)} \\\\"
        )
    write(
        OUT / "table_bootstrap_ci.tex",
        r"""
\begin{tabular}{lrrr}
\toprule
\textbf{Comparison} & \textbf{$\Delta$ Macro F1} & \textbf{95\% CI} & \textbf{Samples} \\
\midrule
"""
        + "\n".join(rows)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def main() -> None:
    ablation = pd.read_csv(OUT / "ablation_summary.csv")
    confidence = pd.read_csv(OUT / "confidence_bins_glm.csv")
    confusion = pd.read_csv(OUT / "confusion_glm_full.csv")
    prefilter = pd.read_csv(OUT / "prefilter_simulation_glm.csv")
    per_class = pd.read_csv(OUT / "per_class_f1_best_variants.csv")
    bootstrap = pd.read_csv(OUT / "bootstrap_ci.csv")

    table_glm_ablation(ablation)
    table_model_family(ablation)
    table_confusion(confusion)
    table_confidence(confidence)
    table_prefilter(prefilter)
    table_per_class(per_class)
    table_bootstrap(bootstrap)

    glm_full = ablation[
        (ablation["model"] == "GLM-4.7") & (ablation["configuration"] == "P1+P2+P3")
    ].iloc[0]
    summary = {
        "n_dev": int(glm_full.n),
        "glm_full_macro_f1": float(glm_full.macro_f1),
        "glm_full_accuracy": float(glm_full.accuracy),
        "glm_full_calls_per_example": float(glm_full.calls_per_example),
        "confidence_bin_count_total": int(confidence["count"].sum()),
        "confidence_ge_095_count": int(confidence[confidence["bin"] == ">=0.95"]["count"].iloc[0]),
        "low_confidence_count": int(confidence[confidence["bin"] != ">=0.95"]["count"].sum()),
    }
    write(OUT / "summary_public.json", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"Regenerated tables in {OUT}")


if __name__ == "__main__":
    main()
