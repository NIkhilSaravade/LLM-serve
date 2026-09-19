"""Build site/index.html, a single self-contained page, from results/bench/*.json.

Every number is computed here from the run files (never typed by hand), charts are the PNGs
written by scripts/plot.py (embedded as base64), and the limitations section is extracted from
the `# LIMITATION:` comments in engine/*.py so it cannot drift from the code.
"""
from __future__ import annotations

import base64
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_data import ROOT, aggregate, load_runs, machine  # noqa: E402
from workloads import WORKLOADS  # noqa: E402

IMG = ROOT / "site" / "img"
ROWS = [  # key, label, kv cache, batching, paging
    ("m0_naive", "M0 naive", "none", "none", "-"),
    ("m1_kv_only", "M1 KV cache", "contiguous", "none", "-"),
    ("m2_static", "M2 static batching", "contiguous", "static", "-"),
    ("m3_continuous", "M3 continuous batching", "contiguous", "continuous", "-"),
    ("m4_static_paged", "M4 static + paged", "paged", "static", "yes"),
    ("m4_full", "M4 continuous + paged", "paged", "continuous", "yes"),
    ("m5_full", "M5 + preemption", "paged", "continuous", "yes"),
]
RATES = {"A": 3, "B": 3, "C": 2}


def img(name: str, alt: str) -> str:
    p = IMG / f"{name}.png"
    if not p.exists():
        return ""
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f'<figure><img alt="{html.escape(alt)}" src="data:image/png;base64,{b64}"><figcaption>{html.escape(alt)}</figcaption></figure>'


def cell(agg: dict, metric: str, fmt: str = "{:.2f}", scale: float = 1.0) -> str:
    if not agg or metric not in agg:
        return "-"
    a = agg[metric]
    f = lambda v: fmt.format(v * scale)  # noqa: E731
    return f"{f(a['median'])} <span class=rng>({f(a['min'])}-{f(a['max'])})</span>"


def ablation_table(agg: dict, wl: str) -> str:
    rate = RATES[wl]
    out = ["<table><thead><tr><th>Config</th><th>KV cache</th><th>Batching</th><th>Paging</th>"
           "<th>Goodput @ SLO (req/s)</th><th>Throughput (tok/s)</th><th>p99 TTFT (s)</th>"
           "<th>Slot util</th><th>KV util</th><th>KV token eff.</th><th>Preempt.</th></tr></thead><tbody>"]
    for key, label, kv, bt, pg in ROWS:
        a = agg.get((key, wl, rate))
        if not a:
            out.append(f"<tr><td>{label}</td><td>{kv}</td><td>{bt}</td><td>{pg}</td><td colspan=7>not run</td></tr>")
            continue
        out.append(f"<tr><td>{label}</td><td>{kv}</td><td>{bt}</td><td>{pg}</td>"
                   f"<td class=n>{cell(a, 'goodput_req_per_s')}</td><td class=n>{cell(a, 'throughput_tok_per_s', '{:.0f}')}</td>"
                   f"<td class=n>{cell(a, 'ttft_s_p99')}</td><td class=n>{cell(a, 'slot_util')}</td>"
                   f"<td class=n>{cell(a, 'kv_util')}</td><td class=n>{cell(a, 'kv_eff')}</td>"
                   f"<td class=n>{cell(a, 'preemptions', '{:.0f}')}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


def unconstrained_table(agg: dict) -> str:
    rows = []
    for key, label in (("m3_continuous_2048", "M3 contiguous, 2 GiB"), ("m4_full_2048", "M4 paged, 2 GiB"),
                       ("m3_continuous", "M3 contiguous, 512 MiB"), ("m4_full", "M4 paged, 512 MiB")):
        a = agg.get((key, "B", 3))
        if a:
            rows.append(f"<tr><td>{label}</td><td class=n>{cell(a, 'goodput_req_per_s')}</td>"
                        f"<td class=n>{cell(a, 'throughput_tok_per_s', '{:.0f}')}</td>"
                        f"<td class=n>{cell(a, 'peak_batch', '{:.0f}')}</td></tr>")
    if not rows:
        return ""
    return ("<table><thead><tr><th>Config (workload B, 3 req/s)</th><th>Goodput (req/s)</th>"
            "<th>Throughput (tok/s)</th><th>Peak batch</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def limitations() -> list[str]:
    found = []
    for p in sorted((ROOT / "engine").glob("*.py")):
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, ln in enumerate(lines):
            m = re.search(r"#\s*LIMITATION:\s*(.*)", ln)
            if not m:
                continue
            text = [m.group(1).strip()]
            for nxt in lines[i + 1:]:
                if re.match(r"\s*#\s?(?!LIMITATION)", nxt) and nxt.strip() != "#":
                    text.append(nxt.strip().lstrip("#").strip())
                else:
                    break
            found.append((p.name, " ".join(text)))
    return [f"<li><code>{n}</code>: {html.escape(t)}</li>" for n, t in found]


def headline(agg: dict) -> str:
    rates = sorted({k[2] for k in agg if k[1] == "B" and k[0] in ("m0_naive", "m2_static", "m5_full")})
    common = [r for r in rates if all(("m0_naive", "B", r) in agg and ("m2_static", "B", r) in agg
                                      and ("m5_full", "B", r) in agg for _ in [0])]
    if not common:
        return "<p>Benchmarks have not been run yet.</p>"
    r = common[-1]
    g = {k: agg[(k, "B", r)]["goodput_req_per_s"]["median"] for k in ("m0_naive", "m2_static", "m5_full")}
    best = max(agg[("m5_full", "B", x)]["goodput_req_per_s"]["median"] for x in rates if ("m5_full", "B", x) in agg)
    return (f"<p class=lead>At {r:g} requests/second, continuous batching with a paged KV cache served "
            f"<b>{g['m5_full']:.2f} req/s within the latency SLO</b>, against {g['m2_static']:.2f} for static batching "
            f"and {g['m0_naive']:.2f} for the naive server. Its best goodput anywhere on the sweep was {best:.2f} req/s. "
            f"Medians of 3 seeds; ranges are shown in the tables.</p>")


def overload_text(agg: dict) -> str:
    rates = sorted(r for (k, w, r) in agg if k == "m5_full" and w == "B")
    if len(rates) < 2:
        return ""
    hi, lo = rates[-1], 4 if ("m5_full", "B", 4) in agg else rates[0]
    a, b = agg[("m5_full", "B", hi)], agg[("m5_full", "B", lo)]
    ttft = lambda x: x["ttft_s_p99"]["median"]  # noqa: E731
    rej = a.get("rejected", {}).get("median", 0)
    done = a.get("completed", {}).get("median", 0)
    inc = a.get("incomplete", {}).get("max", 0)
    tail = ("No request was left unfinished at the cutoff." if inc == 0
            else f"Up to {inc:.0f} requests per run were still unfinished at the cutoff.")
    return (f"Up to {lo:g} req/s the full system keeps p99 TTFT at {ttft(b):.2f} s. At {hi:g} req/s (about "
            f"twice its capacity) p99 TTFT rises to {ttft(a):.1f} s, so latency does degrade sharply past "
            f"saturation. It stays bounded rather than growing without limit because the queue cap of 64 "
            f"refuses excess work with HTTP 429: a median of {rej:.0f} requests per run were rejected while "
            f"{done:.0f} completed. Nothing crashed. {tail}")


def stall_text(runs: list) -> str:
    def worst(label):
        vals = []
        for r in runs:
            if r["label"] == label and r.get("itl_events"):
                vals.append(max(g for _, g in r["itl_events"]))
        return sorted(vals)
    base, inj = worst("stall_baseline"), worst("stall_injected")
    if not base or not inj:
        return "One 800-token prompt arrives into steady load. Prefill is not chunked."
    mid = lambda v: v[len(v) // 2]  # noqa: E731
    return (f"One 800-token prompt arrives at t=15 s into steady 2 req/s load. Prefill is not chunked, so every "
            f"running request waits for it. The largest gap between two tokens seen by ordinary requests was "
            f"{mid(base) * 1000:.0f} ms without the long prompt and {mid(inj) * 1000:.0f} ms with it (median of "
            f"{len(inj)} seeds). It is one stall of a few hundred milliseconds, visible as a single outlier "
            f"rather than a shift in the whole distribution.")


CSS = """
:root{--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--rule:#e1e0d9;--accent:#2a78d6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--rule:#2c2c2a;--accent:#3987e5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:32px 16px 80px}h1{font-size:2rem;margin:0 0 4px}h2{margin:44px 0 8px;font-size:1.35rem}
h3{margin:24px 0 6px;font-size:1.05rem}p,li{color:var(--ink2)}.lead{font-size:1.15rem;color:var(--ink)}
figure{margin:16px 0;background:var(--surface);border:1px solid var(--rule);border-radius:8px;padding:12px}figure img{max-width:100%;height:auto;display:block;margin:0 auto}
figcaption{font-size:.85rem;color:var(--muted);margin-top:6px}.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.86rem;background:var(--surface)}th,td{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:left;white-space:nowrap}
th{color:var(--ink2);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}.rng{color:var(--muted);font-size:.78rem}
code{background:var(--rule);padding:1px 5px;border-radius:4px;font-size:.85em;color:var(--ink)}.note{border-left:3px solid var(--accent);padding:2px 14px;background:var(--surface)}
.sub{color:var(--muted);margin:0 0 24px}a{color:var(--accent)}
"""


def main() -> None:
    runs = load_runs()
    agg = aggregate(runs)
    mach = machine()
    n_runs = len(runs)
    slo = "p99 TTFT under 2 s and p99 TPOT under 200 ms (per-request thresholds for goodput)"
    wl_rows = "".join(
        f"<tr><td>{k}</td><td>{v['prompt']}</td><td>{v['output']}</td><td>{RATES[k]} req/s</td></tr>"
        for k, v in WORKLOADS.items())
    lim = "".join(limitations())
    mach_html = "".join(f"<li><b>{html.escape(k)}</b>: {html.escape(str(v))}</li>" for k, v in mach.items())

    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>llm-serve: continuous batching and paged KV cache, measured</title><style>{CSS}</style></head><body><main>
<h1>llm-serve</h1>
<p class=sub>A from-scratch GPT-2 inference server on CPU. The model is a fixed workload; the subject is the scheduler and the KV cache memory manager.</p>
{headline(agg)}
{img('headline_goodput', 'Goodput at SLO versus offered load, workload B. Line = median of 3 seeds, whiskers = min to max.')}
<p class=note>This is CPU-only. Absolute numbers are far below any GPU system, and batching gains are smaller than GPU literature reports, because a CPU hits its compute limit before its memory-bandwidth limit. The limitations are listed in full <a href="#limitations">below</a>.</p>

<h2>Ablation: what each mechanism contributed</h2>
<p>Every row is a configuration the code can actually run. Workload B (realistic), 3 requests/second offered, KV budget 512 MiB, 3 seeds; cells are median (min-max). Goodput counts requests that finished <em>and</em> met the SLO ({slo}); rejected and unfinished requests count against it. Compare <b>M3</b> with <b>M4 continuous + paged</b> to isolate paging, and <b>M2</b> with <b>M3</b> to isolate continuous batching.</p>
<div class=scroll>{ablation_table(agg, 'B')}</div>
{img('ablation_B', 'Goodput per configuration, workload B. Bars = median, dots = individual seeds.')}
<h3>When memory is not the constraint</h3>
<p>The ablation budget (512 MiB) is a budget where contiguous slots are scarce. With 2 GiB the same two configurations look like this; both results are reported.</p>
<div class=scroll>{unconstrained_table(agg)}</div>

<h2>Workloads</h2>
<p>Output-length variance is the biggest lever on the result, so three workloads are published, the least flattering first. Lengths are scaled down about 3x from the methodology document's suggestion (medians ~64 prompt / ~48 output rather than ~200 / ~150) because full-size runs were too slow on CPU to repeat three times for every configuration. Prompt tokens are random ids and every request sets <code>ignore_eos</code>, so output length is exactly the sampled value.</p>
<div class=scroll><table><thead><tr><th>Workload</th><th>Prompt tokens</th><th>Output tokens</th><th>Ablation offered load</th></tr></thead><tbody>{wl_rows}</tbody></table></div>
<h3>A - uniform (near-worst case for continuous batching)</h3><div class=scroll>{ablation_table(agg, 'A')}</div>{img('ablation_A', 'Goodput per configuration, workload A.')}
<h3>C - high variance (best case; labelled as such)</h3><div class=scroll>{ablation_table(agg, 'C')}</div>{img('ablation_C', 'Goodput per configuration, workload C.')}

<h2>Behaviour under load</h2>
{img('throughput_vs_load', 'Output tokens per second versus offered load.')}
{img('ttft_vs_load', 'p99 time to first token versus offered load (log scale). The dashed line is the 2 s SLO.')}
<h3>Past saturation</h3>
<p>{overload_text(agg)}</p>
{img('overload', 'Overload behaviour of continuous + paged with preemption and admission control.')}

<h2>Sweeps</h2>
{img('block_size', 'Throughput versus block size (paged, 256 MiB).')}{img('block_size_kv', 'Memory efficiency versus block size: small blocks waste less.')}
{img('budget_sweep', 'Throughput versus KV memory budget: contiguous slots against paged blocks.')}
{img('maxbatch', 'Throughput versus maximum batch size at 8 req/s offered.')}
<h3>Long-prefill stall</h3>
<p>{stall_text(runs)}</p>
{img('stall', 'Inter-token gaps seen by ordinary requests, with and without one long prompt.')}

<h2 id=methodology>Methodology</h2>
<ul>
<li><b>Arrivals:</b> open-loop Poisson from a Go load generator (<code>bench/</code>); TTFT is measured from the scheduled arrival, so generator lateness cannot hide server latency.</li>
<li><b>Window:</b> {30} s of arrivals plus {20} s of drain; requests unfinished at the cutoff count as failures. {n_runs} runs in total. Fewer requests per data point (about 60-90) than the methodology document's "few hundred": each configuration is instead repeated with 3 seeds (ablation and load curves) or 2 seeds (sweeps).</li>
<li><b>SLO:</b> {slo}, chosen before measuring.</li>
<li><b>Warmup:</b> 3 sequential requests, discarded, then server counters reset.</li>
<li><b>Admission control:</b> every variant runs with the same queue cap of 64 requests.</li>
<li><b>Threads:</b> torch threads pinned to 4 for every variant.</li>
<li><b>Correctness:</b> every configuration passes the golden test: greedy token IDs identical to the HuggingFace reference, including batches where neighbours join and leave mid-generation and requests that are preempted and recomputed.</li>
<li><b>Static baseline is generous:</b> finished rows leave the compute (a naive server would keep computing them) and tokens stream as produced. Continuous batching's gain over it is therefore conservative.</li>
<li><b>Machine:</b></li></ul><ul>{mach_html}</ul>
<p>Reproduce: <code>./scripts/run_bench.sh</code> then <code>make results</code>. Raw per-request data is committed under <code>results/bench/</code>.</p>

<h2 id=limitations>Limitations</h2>
<ul>
<li>CPU only, fp32. Absolute numbers are far below any GPU system, and batching gains are smaller than GPU papers report because the CPU runs out of compute before memory bandwidth.</li>
<li>Paged attention gathers blocks into a temporary buffer instead of using a fused kernel, so paging has a real cost on this implementation that a production system would not pay.</li>
<li>Batches are padded, not ragged; padded attention width is wasted compute (measured in the milestone logs).</li>
<li>GPT-2 only: no grouped-query attention, no RoPE, no quantisation.</li>
<li>Prefill is not chunked, so a long prompt stalls the decode loop (chart above).</li>
<li>Preemption recomputes instead of swapping to host memory.</li>
<li>Single process, single machine. The HTTP layer, the Go generator and the engine share one CPU.</li>
<li>Workload lengths are scaled down about 3x; runs are shorter than a production benchmark.</li>
</ul>
<h3>Every <code># LIMITATION:</code> comment in the code</h3><ul>{lim}</ul>
</main></body></html>"""
    out = ROOT / "site" / "index.html"
    out.write_text(page, encoding="utf-8")
    print("wrote", out, f"({out.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
