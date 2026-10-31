"""Report Core ML's anticipated compute-device usage for a compiled model."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import coremltools as ct
from coremltools.models.compute_plan import MLComputePlan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="compiled .mlmodelc")
    parser.add_argument("--compute-units", default="cpu_gpu", choices=["cpu_only", "cpu_gpu", "all"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    units = {
        "cpu_only": ct.ComputeUnit.CPU_ONLY,
        "cpu_gpu": ct.ComputeUnit.CPU_AND_GPU,
        "all": ct.ComputeUnit.ALL,
    }[args.compute_units]
    plan = MLComputePlan.load_from_path(args.model, compute_units=units)
    program = plan.model_structure.program
    if program is None:
        raise SystemExit("not an ML Program")
    operations = program.functions["main"].block.operations
    devices = Counter()
    unknown = 0
    total_cost = 0.0
    for operation in operations:
        usage = plan.get_compute_device_usage_for_mlprogram_operation(operation)
        if usage is None:
            unknown += 1
        else:
            devices[type(usage.preferred_compute_device).__name__] += 1
        cost = plan.get_estimated_cost_for_mlprogram_operation(operation)
        if cost is not None:
            total_cost += cost.weight
    result = {
        "model": Path(args.model).name,
        "compute_units": args.compute_units,
        "operations": len(operations),
        "preferred_devices": dict(devices),
        "unknown_device": unknown,
        "estimated_cost_sum": total_cost,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
