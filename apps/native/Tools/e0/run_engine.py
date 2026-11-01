"""Run one inference engine over the E0 fixtures, in its own process.

One engine per process is intentional: loading several Core ML compute-unit
variants and PyTorch in one process produced a reproducible SIGSEGV during E0
measurement. This script never imports torch for Core ML runs and never imports
coremltools for ONNX/PyTorch runs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lama_common import metrics, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--engine", required=True,
                        choices=["onnx", "torch", "coreml_cpu_only", "coreml_cpu_gpu", "coreml_all"])
    parser.add_argument("--onnx", help="pinned ONNX model for --engine onnx")
    parser.add_argument("--model", help=".mlpackage or .mlmodelc for Core ML engines")
    parser.add_argument("--compiled", action="store_true", help="load an already compiled .mlmodelc")
    parser.add_argument("--lama-src")
    parser.add_argument("--config")
    parser.add_argument("--checkpoint")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    fixtures = Path(args.fixtures).resolve()
    meta = json.loads((fixtures / "meta.json").read_text())
    output = Path(args.out).resolve()
    output.mkdir(parents=True, exist_ok=True)

    tag = args.engine
    model = None
    load_seconds = None
    started = time.perf_counter()

    if args.engine == "onnx":
        if not args.onnx:
            raise SystemExit("--onnx is required for --engine onnx")
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        model = ort.InferenceSession(args.onnx, sess_options=options, providers=["CPUExecutionProvider"])
        load_seconds = time.perf_counter() - started

        def run(image, mask):
            return model.run(None, {"image": image, "mask": mask})[0]

    elif args.engine == "torch":
        if not (args.lama_src and args.config and args.checkpoint):
            raise SystemExit("--lama-src, --config and --checkpoint are required for --engine torch")
        import torch
        from lama_common import load_generator, wrapped_generator
        import patch_ffc

        torch.set_num_threads(4)
        generator = load_generator(args.lama_src, args.config, args.checkpoint)
        patch_ffc.apply()
        wrapper = wrapped_generator(generator)
        load_seconds = time.perf_counter() - started

        def run(image, mask):
            with torch.no_grad():
                return wrapper(torch.from_numpy(image), torch.from_numpy(mask)).numpy()

    else:
        if not args.model:
            raise SystemExit("--model is required for Core ML engines")
        import coremltools as ct
        units = {
            "coreml_cpu_only": ct.ComputeUnit.CPU_ONLY,
            "coreml_cpu_gpu": ct.ComputeUnit.CPU_AND_GPU,
            "coreml_all": ct.ComputeUnit.ALL,
        }[args.engine]
        path = Path(args.model)
        if args.compiled:
            model = ct.models.CompiledMLModel(str(path), compute_units=units)
        else:
            model = ct.models.MLModel(str(path), compute_units=units)
        load_seconds = time.perf_counter() - started

        def run(image, mask):
            return model.predict({"image": image, "mask": mask})["output"]

    rows = {"engine": args.engine, "model": Path(args.model).name if args.model else None, "load_seconds": load_seconds, "cases": []}
    for case in meta["cases"]:
        name = case["name"]
        folder = fixtures / name
        image = np_load(folder / "image_512.npy")
        mask = np_load(folder / "mask_512.npy")
        reference = np_load(folder / "onnx_out.npy")
        times = []
        output_array = None
        for _ in range(args.runs):
            start = time.perf_counter()
            output_array = run(image, mask)
            times.append(time.perf_counter() - start)
        output_array = as_float_array(output_array)
        np_save(folder / f"{tag}.npy", output_array)
        row = {
            "name": name,
            "seconds": times,
            "cold_seconds": times[0],
            "warm_median_seconds": statistics.median(times[1:]) if len(times) > 1 else times[0],
            "vs_onnx": metrics(output_array, reference),
        }
        rows["cases"].append(row)
        print(name, "cold", round(times[0], 3), "warm", round(row["warm_median_seconds"], 3), "max", round(row["vs_onnx"]["max"], 6), flush=True)
    write_json(output / f"{tag}.json", rows)
    print(json.dumps(rows["cases"], indent=2))
    return 0


def np_load(path: Path):
    import numpy as np
    return np.load(path)


def np_save(path: Path, value) -> None:
    import numpy as np
    np.save(path, value)


def as_float_array(value):
    import numpy as np
    return np.asarray(value, dtype=np.float32)


if __name__ == "__main__":
    raise SystemExit(main())
