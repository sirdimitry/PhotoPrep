"""Small, pinned catalogue of locally tested ONNX inpainting models."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    filename: str
    size: int
    sha256: str
    repository: str
    revision: str
    license: str

    @property
    def url(self):
        return f'https://huggingface.co/{self.repository}/resolve/{self.revision}/{self.filename}'


MODELS = {
    'lama': ModelSpec('lama','LaMa','lama_fp32.onnx',208044816,
        '1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6',
        'Carve/LaMa-ONNX','c3c0c9e468934d62e79c329e35d82dd09ff8c444','Apache-2.0'),
    'migan': ModelSpec('migan','MI-GAN','migan_pipeline_v2.onnx',28079181,
        '6f1f3530a1a2324b19752018ce756088b07973cda8d7d890034ace5c8a48c40b',
        'andraniksargsyan/migan','406830d0fa60666da0071c342ad2fbc8f30c5c64','MIT'),
}
DEFAULT_MODEL = 'lama'


def get_model(model_id):
    try:
        return MODELS[model_id]
    except (KeyError,TypeError) as exc:
        raise ValueError('unknown_model') from exc
