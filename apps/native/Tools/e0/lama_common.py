"""Shared helpers for the E0 LaMa conversion and parity scripts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_dir(path: str | Path) -> str:
    """Stable hash of a directory tree, including relative names and bytes."""
    root = Path(path)
    digest = hashlib.sha256()
    for file in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = file.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(file)))
    return digest.hexdigest()


def metrics(actual: np.ndarray, expected: np.ndarray) -> dict:
    """Compare two float arrays on the 0..255 code-value scale."""
    diff = np.abs(np.asarray(actual, dtype=np.float64) - np.asarray(expected, dtype=np.float64))
    return {
        "max": float(diff.max()) if diff.size else 0.0,
        "mean": float(diff.mean()) if diff.size else 0.0,
        "p99": float(np.percentile(diff, 99)) if diff.size else 0.0,
        "gt1": int((diff > 1.0).sum()),
        "gt2": int((diff > 2.0).sum()),
        "count": int(diff.size),
    }


def load_config(config_path: str | Path):
    from omegaconf import OmegaConf
    from yaml import safe_load

    return OmegaConf.create(safe_load(open(config_path)))


def load_generator(lama_src: str | Path, config_path: str | Path, checkpoint: str | Path):
    """Load the pinned big-lama generator with the JIT FourierUnit.

    The returned module is the raw 4-channel generator (sigmoid output in
    [0,1]); wrap it in export_lama_wrapper.ExportLama for the ONNX/Core ML
    interface.
    """
    import torch

    src = str(Path(lama_src).resolve())
    if src not in sys.path:
        sys.path.insert(0, src)
    from saicinpainting.training.modules.ffc import FFCResNetGenerator

    config = load_config(config_path)
    generator_cfg = dict(config.generator)
    generator_cfg.pop("kind")
    generator_cfg["resnet_conv_kwargs"] = dict(generator_cfg["resnet_conv_kwargs"])
    generator_cfg["resnet_conv_kwargs"]["use_jit"] = True
    generator = FFCResNetGenerator(**generator_cfg).eval()

    state = torch.load(checkpoint, map_location="cpu", weights_only=False)
    state_dict = state["state_dict"] if isinstance(state, dict) and "state_dict" in state else state
    generator.load_state_dict(
        {k[len("generator.") :]: v for k, v in state_dict.items() if k.startswith("generator.")},
        strict=True,
    )
    return generator


def wrapped_generator(generator):
    from export_lama_wrapper import ExportLama

    return ExportLama(generator).eval()


def trace_wrapper(wrapper, size: int = 512):
    """Trace with a fixed 512x512 batch-1 input."""
    import torch

    torch.manual_seed(0)
    image = torch.zeros(1, 3, size, size, dtype=torch.float32)
    mask = torch.zeros(1, 1, size, size, dtype=torch.float32)
    mask[:, :, size // 4 : size * 3 // 4, size // 4 : size * 3 // 4] = 1.0
    with torch.no_grad():
        eager = wrapper(image, mask)
    traced = torch.jit.trace(wrapper, (image, mask), strict=False).eval()
    with torch.no_grad():
        traced_out = traced(image, mask)
    return traced, float((eager - traced_out).abs().max())


def write_json(path: str | Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
