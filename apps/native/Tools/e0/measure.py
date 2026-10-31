"""Measure one engine's load time, warm prediction time, RSS and physical footprint.

One engine per process. The sampler records task_vm_info.phys_footprint (the
metric the Native admission policy should use) and RSS. It is intentionally a
small, single-machine experiment, not a cross-Mac benchmark.
"""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import resource
import statistics
import threading
import time

import numpy as np
import psutil


class TaskVMInfo(ctypes.Structure):
    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("region_count", ctypes.c_int32),
        ("page_size", ctypes.c_int32),
        ("resident_size", ctypes.c_uint64),
        ("resident_size_peak", ctypes.c_uint64),
        ("device", ctypes.c_uint64),
        ("device_peak", ctypes.c_uint64),
        ("internal", ctypes.c_uint64),
        ("internal_peak", ctypes.c_uint64),
        ("external", ctypes.c_uint64),
        ("external_peak", ctypes.c_uint64),
        ("reusable", ctypes.c_uint64),
        ("reusable_peak", ctypes.c_uint64),
        ("purgeable_volatile_pmap", ctypes.c_uint64),
        ("purgeable_volatile_resident", ctypes.c_uint64),
        ("purgeable_volatile_virtual", ctypes.c_uint64),
        ("compressed", ctypes.c_uint64),
        ("compressed_peak", ctypes.c_uint64),
        ("compressed_lifetime", ctypes.c_uint64),
        ("phys_footprint", ctypes.c_uint64),
    ]


_LIB = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
_LIB.mach_task_self.restype = ctypes.c_uint32
_LIB.task_info.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
_LIB.task_info.restype = ctypes.c_int


def physical_footprint() -> int | None:
    info = TaskVMInfo()
    count = ctypes.c_uint32(38)
    if _LIB.task_info(_LIB.mach_task_self(), 22, ctypes.byref(info), ctypes.byref(count)) != 0:
        return None
    return int(info.phys_footprint)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--engine", required=True,
                        choices=["onnx", "torch", "coreml_cpu_only", "coreml_cpu_gpu", "coreml_all"])
    parser.add_argument("--case", default="texture")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--onnx")
    parser.add_argument("--model")
    parser.add_argument("--compiled", action="store_true")
    parser.add_argument("--lama-src")
    parser.add_argument("--config")
    parser.add_argument("--checkpoint")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    fixtures = Path(args.fixtures).resolve()
    folder = fixtures / args.case
    image = np.load(folder / "image_512.npy").astype(np.float32)
    mask = np.load(folder / "mask_512.npy").astype(np.float32)
    process = psutil.Process()

    stop = threading.Event()
    peaks = {"phys": 0, "rss": 0}

    def sampler():
        while not stop.is_set():
            footprint = physical_footprint()
            rss = process.memory_info().rss
            if footprint:
                peaks["phys"] = max(peaks["phys"], footprint)
            peaks["rss"] = max(peaks["rss"], rss)
            time.sleep(0.01)

    sampler_thread = threading.Thread(target=sampler, daemon=True)
    sampler_thread.start()
    rows = {
        "engine": args.engine,
        "case": args.case,
        "phys_before": physical_footprint(),
        "rss_before": process.memory_info().rss,
        "runs": [],
    }
    started = time.perf_counter()

    if args.engine == "onnx":
        if not args.onnx:
            raise SystemExit("--onnx is required")
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        model = ort.InferenceSession(args.onnx, sess_options=options, providers=["CPUExecutionProvider"])

        def run():
            return model.run(None, {"image": image, "mask": mask})[0]

    elif args.engine == "torch":
        if not (args.lama_src and args.config and args.checkpoint):
            raise SystemExit("--lama-src, --config and --checkpoint are required")
        import torch
        from lama_common import load_generator, wrapped_generator
        import patch_ffc

        torch.set_num_threads(4)
        generator = load_generator(args.lama_src, args.config, args.checkpoint)
        patch_ffc.apply()
        wrapper = wrapped_generator(generator)
        image_tensor = torch.from_numpy(image)
        mask_tensor = torch.from_numpy(mask)

        def run():
            with torch.no_grad():
                return wrapper(image_tensor, mask_tensor).numpy()

    else:
        if not args.model:
            raise SystemExit("--model is required")
        import coremltools as ct
        units = {
            "coreml_cpu_only": ct.ComputeUnit.CPU_ONLY,
            "coreml_cpu_gpu": ct.ComputeUnit.CPU_AND_GPU,
            "coreml_all": ct.ComputeUnit.ALL,
        }[args.engine]
        path = str(Path(args.model).resolve())
        model = ct.models.CompiledMLModel(path, compute_units=units) if args.compiled else ct.models.MLModel(path, compute_units=units)

        def run():
            return np.asarray(model.predict({"image": image, "mask": mask})["output"])

    rows["load_seconds"] = time.perf_counter() - started
    rows["phys_after_load"] = physical_footprint()
    rows["rss_after_load"] = process.memory_info().rss
    for _ in range(args.runs):
        started = time.perf_counter()
        output = run()
        seconds = time.perf_counter() - started
        rows["runs"].append(
            {
                "seconds": seconds,
                "phys": physical_footprint(),
                "rss": process.memory_info().rss,
                "sum": float(np.sum(output)),
            }
        )
    rows["phys_final"] = physical_footprint()
    rows["rss_final"] = process.memory_info().rss
    stop.set()
    sampler_thread.join(timeout=1.0)
    rows["phys_peak"] = peaks["phys"]
    rows["rss_peak"] = peaks["rss"]
    rows["ru_maxrss"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rows["warm_median_seconds"] = statistics.median([r["seconds"] for r in rows["runs"][1:]]) if len(rows["runs"]) > 1 else rows["runs"][0]["seconds"]

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in rows.items() if k != "runs"}, indent=2, sort_keys=True))
    print("warm seconds", [round(r["seconds"], 3) for r in rows["runs"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
