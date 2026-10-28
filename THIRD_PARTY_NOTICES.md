# Third-party components

PhotoPrep is MIT-licensed. Its bundled libraries retain their own licences.
The macOS package includes the licence and notice files supplied by the installed
ONNX Runtime, NumPy, protobuf and certifi distributions under `third-party/`.
PySide6/Qt remains subject to its upstream LGPL/GPL/commercial licensing terms.

## LaMa model (downloaded separately)

- LaMa: Roman Suvorov, Elizaveta Logacheva, Anton Mashikhin, Anastasia Remizova,
  Arsenii Ashukha, Aleksei Silvestrov, Naejin Kong, Harshith Goka, Kiwoong Park,
  Victor Lempitsky. *Resolution-robust Large Mask Inpainting with Fourier
  Convolutions*, WACV 2022.
- Original source: https://github.com/advimman/lama
- ONNX export: https://github.com/Carve-Photos/lama
- Model card / Apache-2.0 declaration: https://huggingface.co/Carve/LaMa-ONNX
- Pinned revision: `c3c0c9e468934d62e79c329e35d82dd09ff8c444`
- File: `lama_fp32.onnx`, 208,044,816 bytes
- SHA256: `1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6`

The model is not included in the DMG or repository. First processing downloads
this exact public model from Hugging Face over HTTPS and verifies its size and
SHA256. Photos and masks are never sent to Hugging Face. Inference uses the local
CPU. The model processes a 512 × 512 context region; PhotoPrep composites only
inside the full-resolution mask and preserves all pixels outside it.
