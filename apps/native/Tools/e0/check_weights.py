"""Check that the pinned big-lama PyTorch checkpoint matches the LaMa ONNX model.

Run with the separate E0 environment (torch + onnx + onnxruntime).
The check has three independent parts:

1. Every ONNX initializer with a matching PyTorch name must be bit-exact.
2. The anonymous ``onnx::Conv_*`` initializers from the early/up/FFC layers are
   compared after BatchNorm folding to their PyTorch conv+BN pairs.
3. The full PyTorch wrapper and the ONNX graph must agree on a deterministic
   random 512x512 input/mask (functional check).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import onnx
from onnx import numpy_helper

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lama_common import load_generator, metrics, sha256_file, wrapped_generator, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lama-src", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=123)
    args = parser.parse_args()

    import torch

    torch.set_num_threads(4)
    generator = load_generator(args.lama_src, args.config, args.checkpoint)
    wrapper = wrapped_generator(generator)
    state = torch.load(args.checkpoint, map_location="cpu", weights_only=False)["state_dict"]
    state = {k[len("generator.") :]: v for k, v in state.items() if k.startswith("generator.")}

    model = onnx.load(args.onnx)
    initializers = {i.name: i for i in model.graph.initializer}

    def normalize(name: str) -> str:
        if name.startswith("model.generator."):
            return name[len("model.generator.") :]
        if name.startswith("generator."):
            return name[len("generator.") :]
        return name

    named = {normalize(name): name for name in initializers}
    named_exact = 0
    named_max_diff = 0.0
    shape_mismatch = []
    torch_without_onnx = []
    for key, value in state.items():
        if value.numel() == 0:
            continue
        onnx_name = named.get(key)
        if onnx_name is None:
            torch_without_onnx.append(key)
            continue
        onnx_array = numpy_helper.to_array(initializers[onnx_name])
        torch_array = value.detach().cpu().numpy()
        if onnx_array.shape != torch_array.shape:
            shape_mismatch.append({"name": key, "onnx": list(onnx_array.shape), "torch": list(torch_array.shape)})
            continue
        diff = float(np.max(np.abs(onnx_array.astype(np.float64) - torch_array.astype(np.float64)))) if onnx_array.size else 0.0
        named_max_diff = max(named_max_diff, diff)
        if diff == 0.0:
            named_exact += 1

    anonymous = sorted(name for name in initializers if name.startswith("onnx::"))
    num_batches = sum(name.endswith("num_batches_tracked") for name in state)

    # Representative early/up/FFC layers whose ONNX weights were renamed and
    # folded: conv weight * gamma / sqrt(var + eps), bias - mean * scale.
    fold_pairs = [
        ("model.1.ffc.convl2l.weight", "model.1.bn_l", "onnx::Conv_20204", "onnx::Conv_20205"),
        ("model.2.ffc.convl2l.weight", "model.2.bn_l", "onnx::Conv_20207", "onnx::Conv_20208"),
        ("model.3.ffc.convl2l.weight", "model.3.bn_l", "onnx::Conv_20210", "onnx::Conv_20211"),
        ("model.4.ffc.convl2l.weight", "model.4.bn_l", "onnx::Conv_20213", "onnx::Conv_20214"),
        ("model.4.ffc.convl2g.weight", "model.4.bn_g", "onnx::Conv_20216", "onnx::Conv_20217"),
    ]
    fold_checks = []
    for conv_name, bn_name, weight_name, bias_name in fold_pairs:
        if weight_name not in initializers or bias_name not in initializers:
            fold_checks.append({"conv": conv_name, "status": "missing_in_onnx"})
            continue
        weight = state[conv_name].float()
        gamma = state[f"{bn_name}.weight"].float()
        beta = state[f"{bn_name}.bias"].float()
        mean = state[f"{bn_name}.running_mean"].float()
        variance = state[f"{bn_name}.running_var"].float()
        scale = gamma / torch.sqrt(variance + 1e-5)
        folded_weight = (weight * scale[:, None, None, None]).numpy()
        folded_bias = (beta - mean * scale).numpy()
        onnx_weight = numpy_helper.to_array(initializers[weight_name])
        onnx_bias = numpy_helper.to_array(initializers[bias_name])
        fold_checks.append(
            {
                "conv": conv_name,
                "weight_max_diff": float(np.max(np.abs(folded_weight - onnx_weight))),
                "bias_max_diff": float(np.max(np.abs(folded_bias - onnx_bias))),
            }
        )

    # Functional check on a deterministic synthetic input.
    import onnxruntime as ort

    rng = np.random.default_rng(args.seed)
    image = rng.random((1, 3, 512, 512), dtype=np.float32)
    mask = np.zeros((1, 1, 512, 512), dtype=np.float32)
    mask[:, :, 180:330, 190:340] = 1.0
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    session = ort.InferenceSession(args.onnx, sess_options=options, providers=["CPUExecutionProvider"])
    onnx_output = session.run(None, {"image": image, "mask": mask})[0]
    with torch.no_grad():
        torch_output = wrapper(torch.from_numpy(image), torch.from_numpy(mask)).numpy()
    functional = metrics(torch_output, onnx_output)

    report = {
        "checkpoint_sha256": sha256_file(args.checkpoint),
        "onnx_sha256": sha256_file(args.onnx),
        "onnx_initializers": len(initializers),
        "named_exact": named_exact,
        "named_max_diff": named_max_diff,
        "shape_mismatch": shape_mismatch,
        "torch_tensors_without_onnx_name": len(torch_without_onnx),
        "torch_tensors_without_onnx_sample": torch_without_onnx[:20],
        "anonymous_onnx_initializers": len(anonymous),
        "bn_fold_checks": fold_checks,
        "num_batches_tracked": num_batches,
        "functional_torch_vs_onnx": functional,
        "seed": args.seed,
    }
    write_json(args.out, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if functional["max"] <= 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
