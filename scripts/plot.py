"""Regenerate every chart from results/bench/*.json:  python scripts/plot.py  (or `make results`).

Design follows the dataviz reference palette (fixed categorical slot order, thin marks,
recessive grid, direct labels plus legend, no dual axes). Each entity keeps one colour on
every chart. Charts whose data does not exist yet are skipped, so this runs on partial results.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_data import ROOT, aggregate, load_runs  # noqa: E402

IMG = ROOT / "site" / "img"
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"

# One colour per system, fixed in the reference palette's slot order, on every chart.
SYSTEMS = [("m0_naive", "Naive (no cache)", BLUE),
           ("m2_static", "Static batching", ORANGE),
           ("m3_continuous", "Continuous, contiguous KV", AQUA),
           ("m5_full", "Continuous + paged KV", YELLOW)]
LABELS = {
    "m0_naive": "M0 naive", "m1_kv_only": "M1 KV cache", "m2_static": "M2 static",
    "m3_continuous": "M3 continuous", "m4_static_paged": "M4 static + paged",
    "m4_full": "M4 continuous + paged", "m5_full": "M5 + preemption",
}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": "#c3c2b7", "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans"], "font.size": 10, "axes.titlesize": 11,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False,
    "axes.axisbelow": True,
})


def med(agg, key, metric):
    a = agg.get(key)
    return a[metric]["median"] if a and metric in a else None


def line(ax, xs, agg_for, metric, color, label, lo_hi=True):
    """Median across seeds as a 2px line with 8px markers; whiskers show min-max."""
    pts = [(x, agg_for(x)) for x in xs]
    pts = [(x, a[metric]) for x, a in pts if a and metric in a]
    if not pts:
        return
    x = [p[0] for p in pts]
    ax.plot(x, [p[1]["median"] for p in pts], color=color, lw=2, marker="o", ms=8,
            mec=SURFACE, mew=2, label=label, zorder=3)
    if lo_hi:
        ax.vlines(x, [p[1]["min"] for p in pts], [p[1]["max"] for p in pts], color=color,
                  lw=1.2, alpha=0.55, zorder=2)


def save(fig, name):
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / f"{name}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def load_chart(agg, metric, ylabel, title, name, logy=False, ref=None):
    rates = sorted({k[2] for k in agg if k[1] == "B" and k[0] in dict((s[0], 1) for s in SYSTEMS)})
    if not rates:
        return
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for cfg, label, color in SYSTEMS:
        line(ax, rates, lambda r, c=cfg: agg.get((c, "B", r)), metric, color, label)
    ax.set_xlabel("Offered load (requests / second, Poisson)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if logy:
        ax.set_yscale("log")
    if ref is not None:
        ax.axhline(ref, color=MUTED, lw=1, ls=(0, (4, 3)))
        ax.text(rates[0], ref, "  SLO", color=INK2, va="bottom", fontsize=9)
    ax.legend(loc="best")
    save(fig, name)


def ablation_chart(agg, wl, name, title):
    cfgs = [c for c in LABELS if (c, wl, 2 if wl == "C" else 3) in agg]
    if not cfgs:
        return
    rate = 2 if wl == "C" else 3
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    for i, c in enumerate(cfgs):
        a = agg[(c, wl, rate)]["goodput_req_per_s"]
        ax.bar(i, a["median"], width=0.6, color=BLUE, zorder=2)
        ax.scatter([i] * len(a["values"]), a["values"], color=INK, s=14, zorder=3)
        ax.text(i, a["max"] + 0.03, f"{a['median']:.2f}", ha="center", va="bottom", fontsize=9, color=INK2)
    ax.set_xticks(range(len(cfgs)), [LABELS[c] for c in cfgs], rotation=25, ha="right")
    ax.set_ylabel("Goodput @ SLO (requests / s)")
    ax.set_title(title)
    ax.grid(axis="x", visible=False)
    save(fig, name)


def sweep_chart(runs_agg, xs, xlabel, series, name, title, metric="throughput_tok_per_s",
                ylabel="Throughput (tokens / s)", logx=False):
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    drawn = False
    for label, color, get in series:
        before = len(ax.lines)
        line(ax, xs, get, metric, color, label)
        drawn = drawn or len(ax.lines) > before
    if not drawn:
        plt.close(fig)
        return
    if logx:
        ax.set_xscale("log", base=2)
    ax.set_xticks(xs, [str(x) for x in xs])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc="best")
    save(fig, name)


def main() -> None:
    runs = load_runs()
    if not runs:
        print("no results in results/bench yet; run scripts/run_bench.sh")
        return
    agg = aggregate(runs)

    load_chart(agg, "goodput_req_per_s", "Goodput @ SLO (requests / s)",
               "Goodput vs offered load (workload B)", "headline_goodput")
    load_chart(agg, "throughput_tok_per_s", "Output tokens / s",
               "Throughput vs offered load (workload B)", "throughput_vs_load")
    load_chart(agg, "ttft_s_p99", "p99 time to first token (s)",
               "Tail TTFT vs offered load (workload B)", "ttft_vs_load", logy=True, ref=2.0)
    for wl, name in (("B", "ablation_B"), ("A", "ablation_A"), ("C", "ablation_C")):
        ablation_chart(agg, wl, name,
                       {"A": "Ablation, workload A (uniform)", "B": "Ablation, workload B (realistic)",
                        "C": "Ablation, workload C (high variance)"}[wl])

    # Overload behaviour of the full system: what happens past saturation.
    rates = sorted({k[2] for k in agg if k[0] == "m5_full" and k[1] == "B"})
    if rates:
        fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
        line(axes[0], rates, lambda r: agg.get(("m5_full", "B", r)), "ttft_s_p99", YELLOW, "p99 TTFT")
        axes[0].set_title("Latency past saturation")
        axes[0].set_ylabel("p99 TTFT (s)")
        line(axes[1], rates, lambda r: agg.get(("m5_full", "B", r)), "rejected", ORANGE, "rejected (queue cap 64)")
        line(axes[1], rates, lambda r: agg.get(("m5_full", "B", r)), "incomplete", BLUE, "unfinished at cutoff")
        axes[1].set_title("Work shed instead of queued")
        axes[1].set_ylabel("Requests per run")
        axes[1].legend(loc="best")
        for ax in axes:
            ax.set_xlabel("Offered load (req / s)")
        save(fig, "overload")

    def by_exp(exp, prefix):
        return lambda x: next((v for k, v in agg.items() if k[0] == f"{prefix}{x}"
                               and any(r["_exp"] == exp for r in v["runs"])), None)

    sweep_chart(agg, [4, 8, 16, 32, 64], "Block size (tokens)",
                [("Continuous + paged, 256 MiB", BLUE, by_exp("sweep_block", "block"))],
                "block_size", "Block-size sweep", logx=True)
    sweep_chart(agg, [4, 8, 16, 32, 64], "Block size (tokens)",
                [("Continuous + paged, 256 MiB", BLUE, by_exp("sweep_block", "block"))],
                "block_size_kv", "KV memory used per stored token, by block size", metric="kv_eff",
                ylabel="Live tokens / allocated capacity", logx=True)
    budgets = [128, 256, 512, 1024, 2048]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    for be, label, color in (("contiguous", "Contiguous slots", AQUA), ("paged", "Paged blocks", YELLOW)):
        line(ax, budgets, lambda m, be=be: agg.get((f"budget{m}_{be}", "B", 3.0)) or agg.get((f"budget{m}_{be}", "B", 3)),
             "throughput_tok_per_s", color, label)
    if ax.lines:
        ax.set_xscale("log", base=2)
        ax.set_xticks(budgets, [str(b) for b in budgets])
        ax.set_xlabel("KV memory budget (MiB)")
        ax.set_ylabel("Throughput (tokens / s)")
        ax.set_title("Throughput vs KV memory budget (3 req/s)")
        ax.legend(loc="best")
        save(fig, "budget_sweep")
    else:
        plt.close(fig)

    mbs = [1, 2, 4, 8, 16, 32]
    sweep_chart(agg, mbs, "Max batch size (rows per step)",
                [("Continuous + paged, offered 8 req/s", BLUE, by_exp("sweep_maxbatch", "maxbatch"))],
                "maxbatch", "Max-batch sweep: where the CPU stops scaling", logx=True)

    # Long-prefill stall: inter-token gaps seen by ordinary requests, seed 1.
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    drawn = False
    for label, color, name in (("steady load", BLUE, "stall_baseline"), ("+ one 800-token prompt at t=15 s", ORANGE, "stall_injected")):
        rs = [r for r in runs if r["label"] == name and r["seed"] == 1 and r.get("itl_events")]
        if rs:
            ev = rs[0]["itl_events"]
            ax.scatter([e[0] for e in ev], [e[1] for e in ev], s=6, color=color, alpha=0.6, label=label)
            drawn = True
    if drawn:
        ax.set_xlabel("Time since start (s)")
        ax.set_ylabel("Gap between consecutive tokens (s)")
        ax.set_title("Long-prefill stall (seed 1)")
        ax.legend(loc="upper right", markerscale=3)
        save(fig, "stall")
    else:
        plt.close(fig)


if __name__ == "__main__":
    main()
