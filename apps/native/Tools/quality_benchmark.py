"""Developer-only Python reference; no downloads, user photos or environment changes.

Run once per model in a fresh process to keep peak RSS attributable to that model.
Outputs are intentionally ignored under work/. This is not the Native engine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
from photoprep import inference


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def fixtures():
    width, height = 768, 512
    y, x = np.mgrid[:height, :width]
    gradient = np.stack((80 + x / 9, 90 + y / 6, 140 + x / 18), axis=2).astype(np.uint8)
    for name in ("flat", "gradient", "texture", "lines", "edge", "border", "soft-logo", "alpha"):
        rgb = gradient.copy()
        if name == "flat":
            rgb[:] = (93, 127, 162)
        elif name == "texture":
            value = (12 * np.sin(x / 5) + 9 * np.cos(y / 7)).astype(np.int16)
            rgb = np.clip(rgb.astype(np.int16) + value[:, :, None], 0, 255).astype(np.uint8)
        elif name == "lines":
            rgb[((x + y // 2) % 42) < 3] = (25, 45, 65)
        elif name == "edge":
            rgb[x > width // 2] = (175, 116, 80)
        rgba = np.concatenate((rgb, np.full((height, width, 1), 255, np.uint8)), axis=2)
        if name == "alpha":
            rgba[:, :, 3] = (x % 256).astype(np.uint8)
        clean = Image.fromarray(rgba)
        mark = Image.new("RGBA", clean.size)
        draw = ImageDraw.Draw(mark)
        font = ImageFont.load_default(size=44)
        at = (0, height - 48) if name == "border" else (width // 2 - 97, height // 2 - 24)
        draw.text(at, "TEST 26", font=font, fill=(255, 255, 255, 110 if name == "soft-logo" else 255),
                  stroke_width=2, stroke_fill=(0, 0, 0, 100 if name == "soft-logo" else 255))
        # Overlay RGB only, retaining original alpha including hidden RGB at alpha=0.
        coverage = np.asarray(mark)[:, :, 3:4].astype(np.float32) / 255
        damaged = rgba.copy()
        damaged[:, :, :3] = np.rint(np.asarray(mark)[:, :, :3] * coverage + rgb * (1 - coverage)).astype(np.uint8)
        bounds = mark.getbbox()
        mask = Image.new("L", clean.size)
        ImageDraw.Draw(mask).rectangle((max(0, bounds[0] - 5), max(0, bounds[1] - 5),
                                        min(width - 1, bounds[2] + 4), min(height - 1, bounds[3] + 4)), fill=255)
        yield name, clean, Image.fromarray(damaged), mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("lama", "migan"), required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not inference.model_verified(args.weights, args.model):
        raise SystemExit("Pinned model size/hash verification failed; nothing downloaded.")
    # Refuse to overwrite a previous benchmark.
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    from PySide6.QtGui import QImage
    import PySide6
    import onnxruntime
    import PIL
    report = dict(engine="python-reference", model=args.model, model_sha256=digest(args.weights),
                  platform=platform.platform(), python=platform.python_version(), pyside=PySide6.__version__,
                  numpy=np.__version__, pillow=PIL.__version__, onnxruntime=onnxruntime.__version__,
                  compute="CPUExecutionProvider, intra=4, inter=1", cases=[])
    start = time.perf_counter()
    predict = inference.create_predictor({args.model: args.weights})(args.model)
    report["load_seconds"] = time.perf_counter() - start
    for name, clean, damaged, mask in fixtures():
        folder = args.output / name
        folder.mkdir(mode=0o700)
        for filename, image in (("clean.png", clean), ("source.png", damaged), ("mask.png", mask)):
            image.save(folder / filename)
        before = digest(folder / "source.png")
        source_image, mask_image = QImage(str(folder / "source.png")), QImage(str(folder / "mask.png"))
        original = inference.image_array(source_image)
        selection = inference.mask_array(mask_image) > 0
        elapsed = []
        for run in range(2):
            start = time.perf_counter()
            output = inference.inpaint(source_image, mask_image, predict)
            elapsed.append(time.perf_counter() - start)
            result = inference.image_array(output)
            outside = int(np.count_nonzero(np.any(result[~selection] != original[~selection], axis=1)))
            alpha = int(np.count_nonzero(result[:, :, 3] != original[:, :, 3]))
            if outside or alpha or digest(folder / "source.png") != before:
                raise RuntimeError(f"Pixel/source preservation gate failed: {name}")
            if not output.save(str(folder / f"result-{run + 1}.png")):
                raise RuntimeError("Cannot save benchmark result")
        mae = float(np.abs(result[:, :, :3].astype(np.float32) - np.asarray(clean)[:, :, :3])[selection].mean())
        case = dict(name=name, seconds=elapsed, masked_rgb_mae=mae,
                    changed_outside_pixels=outside, changed_alpha_pixels=alpha,
                    input_sha256={file: digest(folder / file) for file in ("clean.png", "source.png", "mask.png")})
        report["cases"].append(case)
        print(json.dumps({"case": name, "seconds": elapsed, "masked_rgb_mae": mae}), flush=True)
    report["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    report["limitations"] = "Synthetic fixtures, Python CPU reference only; RSS is not total GPU footprint; first pass includes warm-up; MAE is not visual acceptance."
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
