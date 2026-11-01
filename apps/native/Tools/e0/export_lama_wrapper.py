"""Exact inference wrapper used by the pinned LaMa ONNX export.

The ONNX graph receives RGB [0,1] and mask {0,1}, concatenates the masked image
and mask for the 4-channel generator, blends the prediction with the source by
the mask, and scales to the 0..255 range used by PhotoPrep's compositor.
"""
from __future__ import annotations

import torch


class ExportLama(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, image, mask):
        masked = image * (1.0 - mask)
        generator_input = torch.cat([masked, mask], dim=1)
        prediction = self.model(generator_input)
        inpainted = mask * prediction + (1.0 - mask) * image
        return torch.clamp(inpainted * 255.0, 0.0, 255.0)
