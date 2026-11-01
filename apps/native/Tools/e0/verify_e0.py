"""Strict E0 re-verification: hashes first, then shapes/finite/parity/outside/alpha.

This is deliberately fail-closed. It never claims success from conversion alone.
Run with the separate E0 environment (coremltools + onnxruntime + numpy).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lama_common import metrics, sha256_dir, sha256_file, write_json

EXPECTED = {
    "onnx": "1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6",
    "checkpoint": "fccb7adffd53ec0974ee5503c3731c2c2f1e7e07856fd9228cdcc0b46fd5d423",
    "config": "4fdeed49926e13b101c4dd9e193acec9e58677dfdb4ba49dd6a3a8927964e2a7",
    "source_zip": "87ae34629d745e16f186f848fc676e7d0142c78a9783cf7099336396c3c4c398",
    "package": "eaaaa45fe2c58fe7395f6c634813ce75944837e3b177c743b51ad73e56169cf0",
    "compiled": "5df23cc8fc3959032d2e634c41d602e3ef1e2d387047ea167fe102c144836f2a",
}

TENSOR_MAX = 1.0
TENSOR_MEAN = 0.1
TENSOR_P99 = 1.0
FINAL_MAX = 1


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise SystemExit(f"missing file: {path}")
    return path


def require_dir(path: Path) -> Path:
    if not path.is_dir():
        raise SystemExit(f"missing directory: {path}")
    return path


def check_hash(label: str, path: Path, expected: str, directory: bool = False) -> str:
    actual = sha256_dir(path) if directory else sha256_file(path)
    if actual != expected:
        raise SystemExit(f"HASH MISMATCH {label}: expected {expected}, got {actual}")
    print(f"hash ok {label}: {actual}", flush=True)
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--source-zip", required=True)
    parser.add_argument("--model", required=True, help=".mlpackage or .mlmodelc")
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    onnx_path = require_file(Path(args.onnx))
    checkpoint = require_file(Path(args.checkpoint))
    config = require_file(Path(args.config))
    source_zip = require_file(Path(args.source_zip))
    model = Path(args.model)
    is_compiled = model.suffix == ".mlmodelc"
    if is_compiled:
        require_dir(model)
    else:
        require_dir(model)

    # Hashes are checked before any model/session is created.
    check_hash("ONNX", onnx_path, EXPECTED["onnx"])
    check_hash("checkpoint", checkpoint, EXPECTED["checkpoint"])
    check_hash("config", config, EXPECTED["config"])
    check_hash("source zip", source_zip, EXPECTED["source_zip"])
    check_hash("model", model, EXPECTED["compiled"] if is_compiled else EXPECTED["package"], directory=True)

    import numpy as np
    import onnxruntime as ort
    import coremltools as ct

    fixtures = require_dir(Path(args.fixtures))
    meta = json.loads((fixtures / "meta.json").read_text())
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    session = ort.InferenceSession(str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"])
    coreml = ct.models.CompiledMLModel(str(model), compute_units=ct.ComputeUnit.CPU_AND_GPU) if is_compiled else ct.models.MLModel(str(model), compute_units=ct.ComputeUnit.CPU_AND_GPU)

    cases = []
    failures = []
    for case in meta["cases"]:
        name = case["name"]
        folder = fixtures / name
        image = np.load(folder / "image_512.npy")
        mask = np.load(folder / "mask_512.npy")
        saved_onnx = np.load(folder / "onnx_out.npy")
        source = np.load(folder / "source_rgba.npy")
        coverage = np.load(folder / "coverage.npy")
        final = np.load(folder / "final_coreml_cpu_gpu.npy")
        if image.shape != (1, 3, 512, 512) or image.dtype != np.float32:
            failures.append(f"{name}: image shape/dtype {image.shape}/{image.dtype}")
            continue
        if mask.shape != (1, 1, 512, 512) or mask.dtype != np.float32:
            failures.append(f"{name}: mask shape/dtype {mask.shape}/{mask.dtype}")
            continue
        if saved_onnx.shape != (1, 3, 512, 512) or saved_onnx.dtype != np.float32:
            failures.append(f"{name}: onnx_out shape/dtype")
            continue
        if not np.isfinite(image).all() or not np.isfinite(mask).all() or not np.isfinite(saved_onnx).all():
            failures.append(f"{name}: non-finite oracle tensors")
            continue
        if final.shape != source.shape or coverage.shape != source.shape[:2]:
            failures.append(f"{name}: final/coverage shape")
            continue

        onnx_output = session.run(None, {"image": image, "mask": mask})[0]
        coreml_output = np.asarray(coreml.predict({"image": image, "mask": mask})["output"])
        for label, value in (("onnx_live", onnx_output), ("coreml_live", coreml_output)):
            if value.shape != (1, 3, 512, 512):
                failures.append(f"{name}: {label} shape {value.shape}")
            if value.dtype != np.float32:
                failures.append(f"{name}: {label} dtype {value.dtype}")
            if not np.isfinite(value).all():
                failures.append(f"{name}: {label} contains NaN/Inf")
        parity = metrics(coreml_output, onnx_output)
        if parity["max"] > TENSOR_MAX or parity["mean"] > TENSOR_MEAN or parity["p99"] > TENSOR_P99 or parity["gt2"] != 0:
            failures.append(f"{name}: tensor parity failed {parity}")

        outside = coverage == 0
        changed_outside = int(np.count_nonzero(np.any(final[outside] != source[outside], axis=1)))
        changed_alpha = int(np.count_nonzero(final[:, :, 3] != source[:, :, 3]))
        final_diff = np.abs(final.astype(np.int16) - np.load(folder / "final_onnx.npy").astype(np.int16))
        if changed_outside or changed_alpha or int(final_diff.max()) > FINAL_MAX:
            failures.append(f"{name}: outside/alpha/final failed outside={changed_outside} alpha={changed_alpha} final_max={int(final_diff.max())}")

        cases.append(
            {
                "name": name,
                "onnx_live_shape": list(onnx_output.shape),
                "coreml_live_shape": list(coreml_output.shape),
                "coreml_finite": bool(np.isfinite(coreml_output).all()),
                "parity": parity,
                "changed_outside": changed_outside,
                "changed_alpha": changed_alpha,
                "final_max_vs_onnx": int(final_diff.max()),
            }
        )
        print(name, "max", round(parity["max"], 6), "outside", changed_outside, "alpha", changed_alpha, "final_max", int(final_diff.max()), flush=True)

    actual = {
        "expected_hashes": EXPECTED,
        "model_kind": "compiled" if is_compiled else "package",
        "cases": cases,
        "failures": failures,
        "thresholds": {"tensor_max": TENSOR_MAX, "tensor_mean": TENSOR_MEAN, "tensor_p99": TENSOR_P99, "final_max": FINAL_MAX},
    }
    write_json(args.out, actual)
    if failures:
        print("FAILED", json.dumps(failures, indent=2), flush=True)
        return 1
    worst = max((case["parity"]["max"] for case in cases), default=0.0)
    print(f"PASS: {len(cases)} cases; worst tensor max {worst:.6f}; outside/alpha exact", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
