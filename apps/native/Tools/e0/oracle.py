"""Build the E0 oracle from the existing Python/ONNX reference pipeline.

Run this with the existing PhotoPrep Python environment (the one that already
has PySide6 and onnxruntime). It does not modify the Python application; it
imports photoprep.inference and the existing quality fixtures.

For each fixture it writes:
  source.png, mask.png, clean.png
  source_rgba.npy, coverage.npy, clean_rgba.npy
  image_512.npy, mask_512.npy       exact tensors passed to LaMa
  onnx_out.npy, final_onnx.npy      model output and exact Qt composite
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lama_common import sha256_file, write_json

import quality_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-python", default=None, help="apps/python directory of the PhotoPrep checkout")
    parser.add_argument("--onnx", required=True, help="pinned lama_fp32.onnx")
    parser.add_argument("--out", required=True, help="output fixtures directory")
    args = parser.parse_args()

    app_python = Path(args.app_python).resolve() if args.app_python else Path(__file__).resolve().parents[4] / "apps/python"
    sys.path.insert(0, str(app_python))
    from PySide6.QtGui import QImage
    from photoprep import inference
    import onnxruntime as ort

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    session = ort.InferenceSession(args.onnx, sess_options=options, providers=["CPUExecutionProvider"])

    cases = []
    for name, clean, damaged, mask in quality_benchmark.fixtures():
        folder = out / name
        folder.mkdir(parents=True, exist_ok=True)
        clean.save(folder / "clean.png")
        damaged.save(folder / "source.png")
        mask.save(folder / "mask.png")

        source = QImage(str(folder / "source.png"))
        mask_image = QImage(str(folder / "mask.png"))
        source_rgba = inference.image_array(source)
        coverage = inference.mask_array(mask_image)
        captured = {}

        def predict(image_input, mask_input):
            captured["image"] = image_input.copy()
            captured["mask"] = mask_input.copy()
            output = session.run(None, {"image": image_input, "mask": mask_input})[0]
            captured["output"] = output.copy()
            return output

        result = inference.inpaint(source, mask_image, predict)
        if not result.save(str(folder / "final_onnx.png")):
            raise RuntimeError(f"cannot save final_onnx.png for {name}")
        final = inference.image_array(result)
        clean_rgba = np.asarray(clean.convert("RGBA"))
        np.save(folder / "source_rgba.npy", source_rgba)
        np.save(folder / "coverage.npy", coverage)
        np.save(folder / "clean_rgba.npy", clean_rgba)
        np.save(folder / "image_512.npy", captured["image"])
        np.save(folder / "mask_512.npy", captured["mask"])
        np.save(folder / "onnx_out.npy", captured["output"])
        np.save(folder / "final_onnx.npy", final)

        cases.append(
            {
                "name": name,
                "width": int(source.width()),
                "height": int(source.height()),
                "hashes": {
                    "source_png": sha256_file(folder / "source.png"),
                    "mask_png": sha256_file(folder / "mask.png"),
                    "clean_png": sha256_file(folder / "clean.png"),
                    "image_512": sha256_file(folder / "image_512.npy"),
                    "mask_512": sha256_file(folder / "mask_512.npy"),
                    "onnx_out": sha256_file(folder / "onnx_out.npy"),
                    "final_onnx": sha256_file(folder / "final_onnx.npy"),
                },
            }
        )
        print(name, "done", tuple(captured["image"].shape), flush=True)

    meta = {
        "onnx": Path(args.onnx).name,
        "onnx_sha256": sha256_file(args.onnx),
        "cases": cases,
    }
    write_json(out / "meta.json", meta)
    print(json.dumps({"cases": len(cases), "out": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
