"""Composite each engine's 512x512 output through the exact Python/Qt pipeline.

Run this with the existing PhotoPrep Python environment. This is the bridge
that keeps the comparison honest: the model output is fed back through
photoprep.inference.inpaint, so context rect, Qt SmoothTransformation, mask
coverage, rounding and alpha handling are exactly the Python reference.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lama_common import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--app-python", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    app_python = Path(args.app_python).resolve() if args.app_python else Path(__file__).resolve().parents[4] / "apps/python"
    sys.path.insert(0, str(app_python))
    from PySide6.QtGui import QImage
    from photoprep import inference

    fixtures = Path(args.fixtures).resolve()
    meta = json.loads((fixtures / "meta.json").read_text())
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    engine_files = {
        "onnx": "onnx_out.npy",
        "torch": "torch.npy",
        "coreml_cpu_only": "coreml_cpu_only.npy",
        "coreml_cpu_gpu": "coreml_cpu_gpu.npy",
        "coreml_all": "coreml_all.npy",
        "coreml_compiled_cpu_gpu": "coreml_compiled_cpu_gpu.npy",
        "coreml_compiled_all": "coreml_compiled_all.npy",
    }
    available = {name: filename for name, filename in engine_files.items() if (fixtures / meta["cases"][0]["name"] / filename).exists()}
    if "onnx" not in available:
        raise SystemExit("onnx_out.npy is required as the reference")

    rows = {"engines": list(available), "cases": []}
    for case in meta["cases"]:
        name = case["name"]
        folder = fixtures / name
        source = QImage(str(folder / "source.png"))
        mask = QImage(str(folder / "mask.png"))
        source_rgba = np.load(folder / "source_rgba.npy")
        coverage = np.load(folder / "coverage.npy")
        clean = np.load(folder / "clean_rgba.npy")
        reference_final = np.load(folder / "final_onnx.npy")
        outside = coverage == 0
        inside = coverage > 0
        row = {"name": name, "engines": {}}

        for engine, filename in available.items():
            model_output = np.load(folder / filename)
            started = time.perf_counter()
            result = inference.inpaint(source, mask, lambda image, mask, out=model_output: out)
            seconds = time.perf_counter() - started
            if not result.save(str(folder / f"final_{engine}.png")):
                raise RuntimeError(f"cannot save final_{engine}.png for {name}")
            final = inference.image_array(result)
            np.save(folder / f"final_{engine}.npy", final)
            changed_outside = int(np.count_nonzero(np.any(final[outside] != source_rgba[outside], axis=1)))
            changed_alpha = int(np.count_nonzero(final[:, :, 3] != source_rgba[:, :, 3]))
            diff_reference = np.abs(final.astype(np.int16) - reference_final.astype(np.int16))
            mae_clean = float(
                np.abs(final[:, :, :3].astype(np.float32) - clean[:, :, :3].astype(np.float32))[inside].mean()
            )
            row["engines"][engine] = {
                "composite_seconds": seconds,
                "changed_outside": changed_outside,
                "changed_alpha": changed_alpha,
                "vs_onnx_final_max": int(diff_reference.max()),
                "vs_onnx_final_mean": float(diff_reference.mean()),
                "mae_vs_clean_inside": mae_clean,
            }
        rows["cases"].append(row)
        print(name, {engine: {"out": value["changed_outside"], "alpha": value["changed_alpha"],
                             "max": value["vs_onnx_final_max"], "mae": round(value["mae_vs_clean_inside"], 3)}
                     for engine, value in row["engines"].items()}, flush=True)

    write_json(output, rows)
    print(json.dumps({"engines": rows["engines"], "cases": len(rows["cases"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
