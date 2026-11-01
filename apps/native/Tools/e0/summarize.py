"""Aggregate E0 JSON results into a compact summary and Markdown tables."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics


def load(path: Path):
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args()

    results = Path(args.results)
    weights = load(results / "weights.json")
    manifest = load(results / "models" / "LaMa-fp32.manifest.json") if (results / "models" / "LaMa-fp32.manifest.json").exists() else None
    if manifest is None:
        candidate = results.parent / "models" / "LaMa-fp32.manifest.json"
        manifest = load(candidate) if candidate.exists() else None

    tensor = {}
    for path in sorted(results.glob("*.json")):
        if path.name in {"weights.json", "composite.json", "summary.json"} or path.name.startswith("measure_"):
            continue
        data = load(path)
        if "engine" not in data or "cases" not in data:
            continue
        cases = data["cases"]
        warm = [case.get("warm_median_seconds", case.get("seconds", [0])[-1]) for case in cases]
        cold = [case.get("cold_seconds", case.get("seconds", [0])[0]) for case in cases]
        tensor[data["engine"]] = {
            "max": max(case["vs_onnx"]["max"] for case in cases),
            "mean": statistics.mean(case["vs_onnx"]["mean"] for case in cases),
            "gt1": sum(case["vs_onnx"]["gt1"] for case in cases),
            "gt2": sum(case["vs_onnx"]["gt2"] for case in cases),
            "warm_median": statistics.median(warm),
            "warm_p95": sorted(warm)[max(0, int(0.95 * len(warm)) - 1)],
            "cold_median": statistics.median(cold),
            "cases": len(cases),
        }

    composite_path = results / "composite.json"
    composite = {}
    if composite_path.exists():
        data = load(composite_path)
        for engine in data["engines"]:
            rows = [case["engines"][engine] for case in data["cases"]]
            composite[engine] = {
                "changed_outside": sum(row["changed_outside"] for row in rows),
                "changed_alpha": sum(row["changed_alpha"] for row in rows),
                "vs_onnx_max": max(row["vs_onnx_final_max"] for row in rows),
                "vs_onnx_mean": statistics.mean(row["vs_onnx_final_mean"] for row in rows),
                "mae_min": min(row["mae_vs_clean_inside"] for row in rows),
                "mae_max": max(row["mae_vs_clean_inside"] for row in rows),
            }

    memory = {}
    for path in sorted(results.glob("measure_*.json")):
        data = load(path)
        memory[data["engine"]] = {
            "load_seconds": data["load_seconds"],
            "warm_median_seconds": data["warm_median_seconds"],
            "phys_peak_mib": data["phys_peak"] / 1048576.0,
            "rss_peak_mib": data["rss_peak"] / 1048576.0,
            "ru_maxrss_mib": data["ru_maxrss"] / 1048576.0,
        }

    summary = {
        "weights": {
            "onnx_initializers": weights["onnx_initializers"],
            "named_exact": weights["named_exact"],
            "named_max_diff": weights["named_max_diff"],
            "anonymous_onnx_initializers": weights["anonymous_onnx_initializers"],
            "num_batches_tracked": weights["num_batches_tracked"],
            "functional_torch_vs_onnx": weights["functional_torch_vs_onnx"],
        },
        "manifest": None if manifest is None else {
            "onnx_sha256": manifest["onnx_sha256"],
            "checkpoint_sha256": manifest["checkpoint_sha256"],
            "config_sha256": manifest["config_sha256"],
            "source_commit": manifest["source_commit"],
            "source_zip_sha256": manifest["source_zip_sha256"],
            "package_sha256": manifest["package_sha256"],
            "compiled_sha256": manifest["compiled_sha256"],
            "package_bytes": manifest["package_bytes"],
            "compiled_bytes": manifest["compiled_bytes"],
            "conversion_seconds": manifest["conversion"]["seconds"],
            "patch_eager_max_diff": manifest["patch_eager_max_diff"],
            "trace_eager_max_diff": manifest["trace_eager_max_diff"],
            "functional_torch_vs_onnx": manifest["functional_torch_vs_onnx"],
        },
        "tensor": tensor,
        "composite": composite,
        "memory": memory,
    }
    Path(args.out_json).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    lines = ["# E0 summary", ""]
    lines += ["## Weight correspondence", ""]
    lines += [f"- ONNX initializers: {weights['onnx_initializers']}"]
    lines += [f"- Named PyTorch matches: {weights['named_exact']} (max diff {weights['named_max_diff']})"]
    lines += [f"- Anonymous ONNX conv initializers: {weights['anonymous_onnx_initializers']}"]
    lines += [f"- `num_batches_tracked` counters: {weights['num_batches_tracked']}"]
    lines += [f"- PyTorch vs ONNX max/mean: {weights['functional_torch_vs_onnx']['max']:.6f} / {weights['functional_torch_vs_onnx']['mean']:.8f} (0..255 scale)"]
    lines += ["", "## Tensor parity vs ONNX", "", "| engine | max | mean | >1 LSB | >2 LSB | warm median, s |", "|---|---:|---:|---:|---:|---:|"]
    for engine, row in tensor.items():
        lines.append(f"| {engine} | {row['max']:.6f} | {row['mean']:.8f} | {row['gt1']} | {row['gt2']} | {row['warm_median']:.3f} |")
    lines += ["", "## Final composite vs Python reference", "", "| engine | changed outside | changed alpha | max vs ONNX | MAE clean min/max |", "|---|---:|---:|---:|---:|"]
    for engine, row in composite.items():
        lines.append(f"| {engine} | {row['changed_outside']} | {row['changed_alpha']} | {row['vs_onnx_max']} | {row['mae_min']:.3f}/{row['mae_max']:.3f} |")
    lines += ["", "## Memory and speed (fresh process, this Mac)", "", "| engine | load, s | warm, s | phys peak, MiB | RSS peak, MiB |", "|---|---:|---:|---:|---:|"]
    for engine, row in memory.items():
        lines.append(f"| {engine} | {row['load_seconds']:.2f} | {row['warm_median_seconds']:.3f} | {row['phys_peak_mib']:.0f} | {row['rss_peak_mib']:.0f} |")
    if manifest:
        lines += ["", "## Model", ""]
        lines += [f"- ONNX SHA256: `{manifest['onnx_sha256']}`"]
        lines += [f"- Checkpoint SHA256: `{manifest['checkpoint_sha256']}`"]
        lines += [f"- Package SHA256: `{manifest['package_sha256']}`"]
        lines += [f"- Compiled SHA256: `{manifest['compiled_sha256']}`"]
        lines += [f"- Package/compiled bytes: {manifest['package_bytes']} / {manifest['compiled_bytes']}"]
        lines += [f"- Conversion seconds: {manifest['conversion']['seconds']:.2f}"]
    Path(args.out_md).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
