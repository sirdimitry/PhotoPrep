#!/usr/bin/env python3
"""Compare RGB/mask preprocessing inputs through the same Core ML model.

Usage:
  python compare_inputs.py --native-dump DIR --python-dump DIR \
      --model path/to/LaMa-fp32.mlpackage

Native dump must contain image512-native.f32 and mask512-native.f32;
Python dump must contain image512-python.npy and mask512-python.npy.
"""
import argparse, json
from pathlib import Path
import numpy as np
import coremltools as ct

p = argparse.ArgumentParser()
p.add_argument("--native-dump", required=True)
p.add_argument("--python-dump", required=True)
p.add_argument("--model", required=True)
args = p.parse_args()
nd, pd = Path(args.native_dump), Path(args.python_dump)
nr = np.fromfile(nd / "image512-native.f32", dtype=np.float32).reshape(1, 3, 512, 512)
nm = np.fromfile(nd / "mask512-native.f32", dtype=np.float32).reshape(1, 1, 512, 512)
pr = np.load(pd / "image512-python.npy").reshape(1, 3, 512, 512)
pm = np.load(pd / "mask512-python.npy").reshape(1, 1, 512, 512)
ref = np.load(pd / "model-python.npy").reshape(1, 3, 512, 512)
model = ct.models.MLModel(args.model, compute_units=ct.ComputeUnit.CPU_AND_GPU)

def predict(image, mask):
    return model.predict({"image": image.astype(np.float32), "mask": mask.astype(np.float32)})["output"].reshape(1, 3, 512, 512)

combos = {
    "python_rgb_python_mask": predict(pr, pm),
    "native_rgb_python_mask": predict(nr, pm),
    "python_rgb_native_mask": predict(pr, nm),
    "native_rgb_native_mask": predict(nr, nm),
    "rounded_native_rgb_python_mask": predict(np.rint(nr * 255.0) / 255.0, pm),
    "floor_native_rgb_python_mask": predict(np.floor(nr * 255.0) / 255.0, pm),
}
out = {}
for key, value in combos.items():
    d = np.abs(value - ref)
    out[key] = {"max": float(d.max()), "mean": float(d.mean()), "gt1": int((d > 1).sum())}
for key, image in (("rgb_raw", nr), ("rgb_round", np.rint(nr * 255.0) / 255.0),
                   ("rgb_floor", np.floor(nr * 255.0) / 255.0)):
    d = np.abs(image - pr)
    out[key] = {"max": float(d.max()), "mean": float(d.mean()), "gt0": int((d > 0).sum())}
d = np.abs(nm - pm)
out["mask"] = {"max": float(d.max()), "mean": float(d.mean()), "gt0": int((d > 0).sum())}
print(json.dumps(out, indent=2))
