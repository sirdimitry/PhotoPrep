# Third-party components

## Native 0.3.0 distribution

PhotoPrep Native source is MIT-licensed. The native application uses Apple frameworks; it does not bundle the Python runtime or Python libraries described in the historical sections below.

The bundled `LaMa-fp32.mlmodelc` is a Core ML conversion of big-lama. Changes: exportable Fourier operations, fixed 512×512 tensors, FP32 Core ML conversion/compilation. Original authors: Roman Suvorov, Elizaveta Logacheva, Anton Mashikhin, Anastasia Remizova, Arsenii Ashukha, Aleksei Silvestrov, Naejin Kong, Harshith Goka, Kiwoong Park, Victor Lempitsky.

- Original code and model instructions: https://github.com/advimman/lama
- Conversion source: https://github.com/Carve-Photos/lama, revision `f5fb39a18022c34a71bf9a47a6ec393c804b49ca`.
- Checkpoint source and Apache-2.0 model-card declaration: https://huggingface.co/smartywu/big-lama
- Checkpoint SHA256: `fccb7adffd53ec0974ee5503c3731c2c2f1e7e07856fd9228cdcc0b46fd5d423`.
- Full Apache-2.0 text: [LICENSE-LaMa.txt](apps/native/PhotoPrepNative/Resources/LICENSE-LaMa.txt), also included inside the app's `Contents/Resources/Licenses` directory with this notice and PhotoPrep's MIT licence.

The native DMG includes only the app, compiled model, public UI artwork and licence notices. User photos, test pictures, user PNG branding, caches and preferences are not bundled. The model is not committed to Git.

## Historical Python distribution

PhotoPrep is MIT-licensed. Its bundled libraries retain their own licences.
The macOS package includes the licence and notice files supplied by the installed
ONNX Runtime, NumPy, protobuf, certifi and Pillow distributions under `third-party/`.
PySide6/Qt remains subject to its upstream LGPL/GPL/commercial licensing terms.

### LaMa model (Python: downloaded separately)

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


### MI-GAN model (downloaded separately)

- MI-GAN: Andranik Sargsyan, Shant Navasardyan, Xingqian Xu, Humphrey Shi.
  *MI-GAN: A Simple Baseline for Image Inpainting on Mobile Devices*, ICCV 2023.
- Original implementation: https://github.com/Picsart-AI-Research/MI-GAN
- Weights licence: MIT, copyright 2024 Picsart AI Research (PAIR).
  Full text: `apps/python/assets/licenses/MI-GAN-LICENSE` and bundled `third-party/MI-GAN-LICENSE`.
- Author's ONNX export: https://huggingface.co/andraniksargsyan/migan
- Pinned revision: `406830d0fa60666da0071c342ad2fbc8f30c5c64`
- File: `migan_pipeline_v2.onnx`, 28,079,181 bytes
- SHA256: `6f1f3530a1a2324b19752018ce756088b07973cda8d7d890034ace5c8a48c40b`

PhotoPrep adapts MI-GAN's uint8 inputs and inverted mask convention to the same
512px-context, mask-only compositor. Each saved removal pass records its model.
Both model files are kept separately from the app and are verified before use.

Pillow supplies JPEG/PNG encoding from fresh pixel buffers; its licence and
third-party notices are included under `third-party/pillow/`.

### SDXL Inpainting (optional weights)

Official model: https://huggingface.co/diffusers/stable-diffusion-xl-1.0-inpainting-0.1
Developed by the Diffusers team, initialized from Stability AI SDXL Base 1.0.
Weights are downloaded separately as FP16 safetensors from a pinned revision.
Model licence: CreativeML Open RAIL++-M (not the application's MIT licence).
Full terms: apps/python/assets/licenses/SDXL-LICENSE.md, included in the app's third-party notices.
PyTorch, Diffusers, Transformers, Accelerate and their dependencies retain their
own licences, included with the application. No user images are sent to these projects.
