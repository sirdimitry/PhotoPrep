> Developer-only model conversion tools. The current app and download are documented in [PhotoPrep Native](../../README.md). No test photos or checkpoints belong in Git.

# E0 — LaMa → Core ML conversion and parity lab

Developer-only tooling for the first LaMa Core ML experiment. It is **not**
wired into the app: no UI, worker, canvas, sessions, export or release changes.
Weights and generated models stay outside the repository (and `work/` is
ignored).

## Result in one line

A fixed-shape, FP32 LaMa `.mlpackage` was produced from the original PyTorch
big-lama checkpoint. On 8 synthetic fixtures its tensor output and final Qt
composite match the pinned Python/ONNX reference within one 8-bit code value;
outside-mask pixels and alpha are unchanged. This proves conversion parity on
that set, not universal logo-removal quality.

## Separate environment

Use Python 3.12 and a venv outside the application:

```bash
python3.12 -m venv <e0-venv>
<e0-venv>/bin/python -m pip install -r apps/native/Tools/e0/requirements-e0.txt
```

`coremltools==9.0` is tested with torch 2.7.0; this experiment used torch 2.7.1
and records the warning. Do not install these packages into the PhotoPrep
application environment.

## Inputs

Pinned source and weights used by E0:

* source: `https://github.com/Carve-Photos/lama` at
  `f5fb39a18022c34a71bf9a47a6ec393c804b49ca` (Apache-2.0);
* weights: `https://huggingface.co/smartywu/big-lama/resolve/main/big-lama.zip`
  (SHA256 `f1b358ca24093b93a106183b98a3dea6e8ed09f3b43ea7251eb2c81e7b4575f6`);
  `models/best.ckpt` SHA256 `fccb7adffd53ec0974ee5503c3731c2c2f1e7e07856fd9228cdcc0b46fd5d423`;
* ONNX oracle: `lama_fp32.onnx` SHA256
  `1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6`.

The ONNX model card documents a custom `FourierUnitJIT`, fixed 512×512 input and
opset 17. The ONNX is the quality oracle; the PyTorch checkpoint is the source
for conversion.

## Commands

All paths below are examples; use the actual checkout and data directories.

### 1. Check that the checkpoint matches the ONNX

```bash
<e0-venv>/bin/python apps/native/Tools/e0/check_weights.py \
  --lama-src <e0-data>/src/lama \
  --config <e0-data>/big-lama/config.yaml \
  --checkpoint <e0-data>/big-lama/models/best.ckpt \
  --onnx <models>/lama_fp32.onnx \
  --out <e0-data>/work/e0/results/weights.json
```

### 2. Convert to Core ML FP32

```bash
TORCH_HOME=<e0-data> PYTHONPATH=<e0-data>/src/lama \
<e0-venv>/bin/python apps/native/Tools/e0/convert_lama.py \
  --lama-src <e0-data>/src/lama \
  --config <e0-data>/big-lama/config.yaml \
  --checkpoint <e0-data>/big-lama/models/best.ckpt \
  --onnx <models>/lama_fp32.onnx \
  --source-zip <e0-data>/src/carve_lama.zip \
  --out-dir <e0-data>/work/e0/models
```

`convert_lama.py` uses `xcrun coremlcompiler`; it sets `DEVELOPER_DIR` to
`/Applications/Xcode.app/Contents/Developer` by default. Use `--developer-dir`
if Xcode is elsewhere, or `--skip-compile` to only produce the `.mlpackage`.
The generated package and compiled model are ignored and must not be committed.

### 3. Build fixtures and the ONNX oracle

Run with the **existing application Python environment** (PySide6 +
onnxruntime), not the E0 venv:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=<repo>/apps/python \
<app-python> apps/native/Tools/e0/oracle.py \
  --app-python <repo>/apps/python \
  --onnx <models>/lama_fp32.onnx \
  --out <e0-data>/work/e0/fixtures
```

### 4. Run one engine per process

One engine per process is deliberate: loading several Core ML compute-unit
variants plus PyTorch in one process produced a SIGSEGV during E0. Use:

```bash
# ONNX reference re-run
<e0-venv>/bin/python apps/native/Tools/e0/run_engine.py \
  --fixtures <e0-data>/work/e0/fixtures --engine onnx \
  --onnx <models>/lama_fp32.onnx --out <e0-data>/work/e0/results

# PyTorch
TORCH_HOME=<e0-data> PYTHONPATH=<e0-data>/src/lama \
<e0-venv>/bin/python apps/native/Tools/e0/run_engine.py \
  --fixtures <e0-data>/work/e0/fixtures --engine torch \
  --lama-src <e0-data>/src/lama --config <e0-data>/big-lama/config.yaml \
  --checkpoint <e0-data>/big-lama/models/best.ckpt \
  --out <e0-data>/work/e0/results

# Core ML (compiled model is faster to load; package also works)
<e0-venv>/bin/python apps/native/Tools/e0/run_engine.py \
  --fixtures <e0-data>/work/e0/fixtures --engine coreml_cpu_gpu \
  --model <e0-data>/work/e0/models/LaMa-fp32.mlmodelc --compiled \
  --out <e0-data>/work/e0/results
```

Repeat for `coreml_cpu_only`, `coreml_all`; each invocation is a fresh process.

### 5. Composite through the exact Python/Qt pipeline

Run with the existing application environment:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=<repo>/apps/python \
<app-python> apps/native/Tools/e0/composite.py \
  --fixtures <e0-data>/work/e0/fixtures \
  --app-python <repo>/apps/python \
  --out <e0-data>/work/e0/results/composite.json
```

### 6. Measure memory and speed

```bash
<e0-venv>/bin/python apps/native/Tools/e0/measure.py \
  --fixtures <e0-data>/work/e0/fixtures --engine coreml_cpu_gpu \
  --model <e0-data>/work/e0/models/LaMa-fp32.mlmodelc --compiled \
  --out <e0-data>/work/e0/results/measure_coreml_cpu_gpu.json --runs 3
```

Repeat for each engine. The script samples `task_vm_info.phys_footprint` and
RSS in a separate thread. `load_seconds` includes the library import and model
load; compiled-model load alone is reported separately in the E0 report.

### 7. Inspect the compute plan

```bash
<e0-venv>/bin/python apps/native/Tools/e0/compute_plan.py \
  --model <e0-data>/work/e0/models/LaMa-fp32.mlmodelc \
  --compute-units all --out <e0-data>/work/e0/results/compute_plan_all.json
```

### 8. Summarize

```bash
<e0-venv>/bin/python apps/native/Tools/e0/summarize.py \
  --results <e0-data>/work/e0/results \
  --out-json <e0-data>/work/e0/results/summary.json \
  --out-md <e0-data>/work/e0/results/summary.md
```

## Strict E0 re-verification

`verify_e0.py` fails closed: it checks the expected hashes of ONNX, checkpoint,
config, source zip and the saved model **before** creating an ONNX session or
Core ML model; then it validates tensor shapes, dtype, NaN/Infinity, the parity
thresholds, and `changed_outside == 0` / `changed_alpha == 0` on the final
composite.

```bash
<e0-venv>/bin/python apps/native/Tools/e0/verify_e0.py \
  --onnx <models>/lama_fp32.onnx \
  --checkpoint <e0-data>/big-lama/models/best.ckpt \
  --config <e0-data>/big-lama/config.yaml \
  --source-zip <e0-data>/src/carve_lama.zip \
  --model <e0-data>/work/e0/models/LaMa-fp32.mlmodelc \
  --fixtures <e0-data>/work/e0/fixtures \
  --results <e0-data>/work/e0/results \
  --out <e0-data>/work/e0/results/verify_e0.json
```

Actual result on 31.10.2026: 8/8 cases passed; worst tensor max `0.000664`,
all outside/alpha changes zero; final max vs ONNX 1 LSB. Full values are in the
E1 report.

## Acceptance scale and thresholds

All model and composite comparisons use **8-bit code values 0..255**, not the
0..1 normalized input range. `d = |a - b|`; `MAE = mean(d)`.

* FP32 tensor parity vs ONNX: `max(d) <= 1.0` (one 8-bit LSB), `mean(d) <= 0.1`,
  `p99(d) <= 1.0`, and zero pixels with `d > 2.0`.
  One LSB is the smallest possible difference after the final uint8 conversion;
  a mean of 0.1 prevents a systematic bias. This is deliberately stricter than
  the final image gate because it catches algorithmic/preprocessing errors.
* Final RGBA vs the Python reference: `changed_outside == 0`,
  `changed_alpha == 0`, `max(d) <= 1`, and a very small mean. The strict zero
  outside/alpha gate is the actual product contract; `max <= 1` allows Qt's
  final uint8 truncation to differ by one code value.
* Quality vs the known clean synthetic image: compare MAE inside the mask to
  the ONNX reference and require no visual regression. MAE alone is not a
  quality proof; 100%/200% visual review is required.

Observed FP32 results are far tighter than the gates (see the report).

## Scope and limits

* 8 authored synthetic 768×512 fixtures, one rectangular mask each; no real
  photos, multi-pass recipes, brush masks, 40 MP sources or Native alpha path.
* One Mac (Apple M3 Max, 36 GiB, macOS 27.2 arm64). No other Macs, Intel or
  macOS 14.
* FP32 only; FP16, quantization, palettization and Neural Engine are not
  accepted. `MLComputePlan` reports GPU-preferred operations, not ANE.
* Core ML is run through the Python `CompiledMLModel`/`MLModel` wrapper. App
  integration, XPC/worker, cancellation and hard memory limits are out of scope.
* No weights or generated models are committed. The repository `.gitignore`
  already ignores `*.mlpackage`, `*.mlmodelc` and `work/`.
