"""Conversion-only compatibilty patch for LaMa's custom FourierUnitJIT.

This patch is applied only while producing the Core ML package. It changes
neither the architecture nor the weights; it only rewrites two operations that
coremltools cannot lower from the traced PyTorch graph:

1. Normalization by ``torch.sqrt(N)`` where ``N`` is a Python/int shape was
   traced as an int32 sqrt. Core ML's ``sqrt`` accepts only fp16/fp32. ``N`` is
   static (512), so normalizing by the Python float ``sqrt(N)`` is identical.
2. ``torch.tensordot`` has no coremltools lowering. It is replaced by an
   equivalent ``torch.einsum`` for the two axes used by LaMa (H and W).

The conversion tool verifies eager-before vs eager-after and eager vs traced
output parity; both are expected to be exactly zero on the pinned model.
"""
from __future__ import annotations

import torch
import saicinpainting.training.modules.ffc as ffc


def _norm(n) -> float | torch.Tensor:
    if isinstance(n, torch.Tensor):
        return torch.sqrt(n.to(torch.float32))
    return float(n) ** 0.5


def rfft(x):
    n = x.shape[-1]
    rows = torch.arange(n, dtype=torch.float32, device=x.device)
    cols = torch.arange(n // 2 + 1, dtype=torch.float32, device=x.device)
    cos_part = torch.cos(-2 * torch.pi * rows[:, None] * cols / n)
    sin_part = torch.sin(-2 * torch.pi * rows[:, None] * cols / n)
    real_part = torch.matmul(x, cos_part)
    imag_part = torch.matmul(x, sin_part)
    norm = _norm(n)
    return real_part / norm, imag_part / norm


def fft(real, imag):
    n = real.shape[-1]
    rows = torch.arange(n, dtype=torch.float32, device=real.device)
    cols = rows.unsqueeze(1)
    cos_part = torch.cos(-2 * torch.pi * cols * rows / n)
    sin_part = torch.sin(-2 * torch.pi * cols * rows / n)
    real_out = torch.matmul(cos_part, real.unsqueeze(-1)) - torch.matmul(sin_part, imag.unsqueeze(-1))
    imag_out = torch.matmul(sin_part, real.unsqueeze(-1)) + torch.matmul(cos_part, imag.unsqueeze(-1))
    norm = _norm(n)
    return real_out.squeeze(-1) / norm, imag_out.squeeze(-1) / norm


def ifft1d(real, imag, n=None, axis=-1):
    if n is None:
        n = real.shape[axis]
    axis = axis % real.ndim

    rows = torch.arange(n, dtype=torch.float32, device=real.device)
    cols = torch.arange(n, dtype=torch.float32, device=real.device)
    cos_matrix = torch.cos(2 * torch.pi * rows.unsqueeze(-1) * cols / n)
    sin_matrix = torch.sin(2 * torch.pi * rows.unsqueeze(-1) * cols / n)

    def contract(matrix, value):
        if axis == 2:
            return torch.einsum("ij,bcjw->ibcw", matrix, value)
        if axis == 3:
            return torch.einsum("ij,bchj->ibch", matrix, value)
        raise ValueError(f"unsupported ifft axis {axis}")

    real_part = contract(cos_matrix, real) - contract(sin_matrix, imag)
    imag_part = contract(sin_matrix, real) + contract(cos_matrix, imag)
    norm = _norm(n)
    real_part = real_part / norm
    imag_part = imag_part / norm

    perm = list(range(len(real.shape)))
    perm[2], perm[0] = perm[0], perm[2]
    perm[0], perm[1] = perm[1], perm[0]
    return real_part.permute(perm), imag_part.permute(perm)


def apply() -> None:
    """Monkeypatch the imported LaMa module in this process only."""
    ffc.rfft = rfft
    ffc.fft = fft
    ffc.ifft1d = ifft1d
