# Python reference — 29.10.2026

Synthetic benchmark, **not Native Core ML results**. Eight authored 768×512 RGBA
fixtures, one rectangular mask per image; 2 runs per case. Existing pinned ONNX
weights were read without copying/modifying them. No download. Local CPU provider,
intra_op=4, inter_op=1, macOS 27.2 arm64, Python 3.12.4, PySide6 6.12.0,
NumPy 2.5.4, ONNX Runtime 1.31.1, Pillow 13.0.0.

| Metric | LaMa | MI-GAN |
|---|---:|---:|
| Load model, seconds | 4.340 | 0.108 |
| Median second run, seconds | 1.908 | 0.197 |
| Peak process RSS, MiB | 1216.5 | 1014.4 |
| Changed pixels outside mask (all cases) | 0 | 0 |
| Changed alpha pixels (all cases) | 0 | 0 |
| Original source SHA256 preserved | yes | yes |

RSS includes imports, buffers and the model, excludes other processes and does not
describe total system/GPU footprint. Load timing includes predictor setup. No speed
claim for Core ML or other Macs follows from these figures; this is a small sample,
not a p95 or stability benchmark.

| Masked RGB MAE versus known clean image (0–255) | LaMa | MI-GAN |
|---|---:|---:|
| flat | 1.362 | 1.015 |
| gradient | 1.049 | 1.157 |
| repeated texture | 4.579 | 17.364 |
| thin diagonal lines | 2.655 | 22.085 |
| contrasting boundary | 1.813 | 1.533 |
| edge of frame | 5.085 | 5.399 |
| translucent logo | 1.049 | 1.157 |
| translucent source | 1.036 | 1.159 |

Local visual inspection of 1:1 crops confirmed visible bright remnants/patches
for the current MI-GAN pipeline on texture/lines. LaMa continued the lines much
better; some texture smoothing and edge shading remain. Neither is accepted as
Native quality or exact reconstruction. MAE alone cannot approve a model.
Smaller model size is not proof of worse quality; this choice is based on actual
outputs. **LaMa remains the primary quality candidate**. MI-GAN requires separate
pre/postprocessing and quality review before becoming an optional Native engine.

Reproduction (one fresh process per model; use an existing compatible developer
Python, not the shipped app runtime; no installs required):

```bash
python apps/native/Tools/quality_benchmark.py --model lama \
  --weights /path/to/lama_fp32.onnx --output work/native-quality/lama-reference
python apps/native/Tools/quality_benchmark.py --model migan \
  --weights /path/to/migan_pipeline_v2.onnx --output work/native-quality/migan-reference
```

The tool refuses an existing output directory and verifies catalog SHA256/size.
It emits PNGs and report.json with input/model hashes, per-run timings and gates.
`work/` is ignored. No models, personal images, logs or absolute home paths are
included in this report. External real-photo acceptance and Core ML comparison
remain required by [QUALITY-SAFETY.md](QUALITY-SAFETY.md).
