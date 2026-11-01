"""Convert the pinned big-lama PyTorch model to a fixed-shape Core ML FP32 package.

This is an E0 developer tool, not part of the application. It deliberately
uses the traced wrapper (not TorchScript) because the Carve FourierUnitJIT
contains a tuple construct that TorchScript rejects. The two conversion-only
patches in patch_ffc.py are verified to be exactly equivalent in eager mode.

Example:
  python Tools/e0/convert_lama.py \
    --lama-src /path/to/Carve-Photos-lama \
    --config /path/to/big-lama/config.yaml \
    --checkpoint /path/to/big-lama/models/best.ckpt \
    --onnx /path/to/lama_fp32.onnx \
    --out-dir work/e0/models
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lama_common import (
    load_generator,
    metrics,
    sha256_dir,
    sha256_file,
    trace_wrapper,
    wrapped_generator,
    write_json,
)
import patch_ffc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lama-src", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--onnx", help="optional pinned ONNX for a functional pre-check")
    parser.add_argument("--source-repo", default="https://github.com/Carve-Photos/lama")
    parser.add_argument("--source-commit", default="f5fb39a18022c34a71bf9a47a6ec393c804b49ca")
    parser.add_argument("--source-zip", help="optional source zip for a recorded hash")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--name", default="LaMa-fp32")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--developer-dir", default=os.environ.get("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer"))
    args = parser.parse_args()

    import coremltools as ct
    import numpy as np
    import torch

    torch.set_num_threads(4)
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    generator = load_generator(args.lama_src, args.config, args.checkpoint)
    wrapper = wrapped_generator(generator)

    torch.manual_seed(0)
    image = torch.zeros(1, 3, args.size, args.size)
    mask = torch.zeros(1, 1, args.size, args.size)
    mask[:, :, args.size // 4 : args.size * 3 // 4, args.size // 4 : args.size * 3 // 4] = 1.0
    with torch.no_grad():
        before_patch = wrapper(image, mask)

    patch_ffc.apply()
    with torch.no_grad():
        after_patch = wrapper(image, mask)
    patch_diff = float((before_patch - after_patch).abs().max())

    traced, trace_diff = trace_wrapper(wrapper, size=args.size)

    functional = None
    if args.onnx:
        import onnxruntime as ort

        rng = np.random.default_rng(123)
        test_image = rng.random((1, 3, args.size, args.size), dtype=np.float32)
        test_mask = np.zeros((1, 1, args.size, args.size), dtype=np.float32)
        test_mask[:, :, 180:330, 190:340] = 1.0
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        session = ort.InferenceSession(args.onnx, sess_options=options, providers=["CPUExecutionProvider"])
        onnx_output = session.run(None, {"image": test_image, "mask": test_mask})[0]
        with torch.no_grad():
            torch_output = wrapper(torch.from_numpy(test_image), torch.from_numpy(test_mask)).numpy()
        functional = metrics(torch_output, onnx_output)

    started = time.perf_counter()
    mlmodel = ct.convert(
        traced,
        convert_to="mlprogram",
        minimum_deployment_target=ct.target.macOS14,
        compute_precision=ct.precision.FLOAT32,
        inputs=[
            ct.TensorType(name="image", shape=(1, 3, args.size, args.size)),
            ct.TensorType(name="mask", shape=(1, 1, args.size, args.size)),
        ],
        outputs=[ct.TensorType(name="output")],
        skip_model_load=True,
    )
    convert_seconds = time.perf_counter() - started
    package = out_dir / f"{args.name}.mlpackage"
    mlmodel.save(package)

    # Inspect the saved package (this also verifies that it is loadable).
    loaded = ct.models.MLModel(str(package))
    spec = loaded.get_spec()
    inputs = []
    for item in spec.description.input:
        inputs.append(
            {
                "name": item.name,
                "type": item.type.WhichOneof("Type"),
                "shape": list(item.type.multiArrayType.shape) if item.type.WhichOneof("Type") == "multiArrayType" else None,
            }
        )
    outputs = []
    for item in spec.description.output:
        outputs.append(
            {
                "name": item.name,
                "type": item.type.WhichOneof("Type"),
                "shape": list(item.type.multiArrayType.shape) if item.type.WhichOneof("Type") == "multiArrayType" else None,
            }
        )

    compiled = None
    if not args.skip_compile:
        compiled = out_dir / f"{args.name}.mlmodelc"
        if compiled.exists():
            shutil.rmtree(compiled)
        environment = os.environ.copy()
        environment["DEVELOPER_DIR"] = args.developer_dir
        subprocess.run(
            ["xcrun", "coremlcompiler", "compile", str(package), str(out_dir)],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )

    package_weight = package / "Data/com.apple.CoreML/weights/weight.bin"
    package_files = [p for p in package.rglob("*") if p.is_file()]
    manifest = {
        "tool": "convert_lama.py",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_repo": args.source_repo,
        "source_commit": args.source_commit,
        "source_zip_sha256": sha256_file(args.source_zip) if args.source_zip else None,
        "checkpoint": Path(args.checkpoint).name,
        "checkpoint_sha256": sha256_file(args.checkpoint),
        "config": Path(args.config).name,
        "config_sha256": sha256_file(args.config),
        "onnx": Path(args.onnx).name if args.onnx else None,
        "onnx_sha256": sha256_file(args.onnx) if args.onnx else None,
        "weights_layout": "fixed batch 1, RGB NCHW float32 [0,1], mask N1HW float32 {0,1}, output NCHW float32 [0,255]",
        "wrapper": "masked = image*(1-mask); concat(masked, mask); blend mask*pred+(1-mask)*image; clamp(*255)",
        "patch": [
            "sqrt of static int shape normalized as Python float sqrt (Core ML sqrt rejects int32)",
            "tensordot in ifft1d replaced by equivalent einsum for axes H/W (no coremltools lowering)",
        ],
        "patch_eager_max_diff": patch_diff,
        "trace_eager_max_diff": trace_diff,
        "functional_torch_vs_onnx": functional,
        "conversion": {
            "convert_to": "mlprogram",
            "minimum_deployment_target": "macOS14",
            "compute_precision": "FLOAT32",
            "input_shapes": [[1, 3, args.size, args.size], [1, 1, args.size, args.size]],
            "output_shape": [1, 3, args.size, args.size],
            "seconds": convert_seconds,
        },
        "package": str(package.relative_to(out_dir)),
        "package_sha256": sha256_dir(package),
        "package_bytes": sum(p.stat().st_size for p in package_files),
        "package_files": len(package_files),
        "package_weights_sha256": sha256_file(package_weight) if package_weight.exists() else None,
        "compiled": compiled.name if compiled else None,
        "compiled_sha256": sha256_dir(compiled) if compiled and compiled.exists() else None,
        "compiled_bytes": sum(p.stat().st_size for p in compiled.rglob("*") if p.is_file()) if compiled and compiled.exists() else None,
        "specification_version": spec.specificationVersion,
        "inputs": inputs,
        "outputs": outputs,
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "coremltools": ct.__version__,
            "numpy": np.__version__,
        },
        "licenses": {
            "code": "Apache-2.0 (Carve-Photos/lama)",
            "weights_card": "Apache-2.0 (Carve/LaMa-ONNX model card); redistribution/legal review still required",
        },
        "warnings": [
            "coremltools 9.0 was tested with torch 2.7.0; this run used torch 2.7.1.",
            "TorchScript failed on the Carve FourierUnitJIT tuple construct; a fixed-shape trace was used.",
            "The package contains no personal data or source photos.",
        ],
    }
    write_json(out_dir / f"{args.name}.manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
