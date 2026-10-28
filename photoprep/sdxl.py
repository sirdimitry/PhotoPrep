"""Optional SDXL engine. Loads verified local safetensors, never a remote pipeline."""
import os


class SDXLPredictor:
    resolution=1024
    steps=20

    def __init__(self,path):
        # Isolate hub telemetry/cache behavior in the inference child process.
        os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1',TOKENIZERS_PARALLELISM='false')
        try:
            import torch
            from diffusers import StableDiffusionXLInpaintPipeline
        except ImportError as exc:raise ValueError('sdxl_runtime_missing') from exc
        if not torch.backends.mps.is_available():raise ValueError('sdxl_requires_mps')
        self.torch=torch
        self.pipe=StableDiffusionXLInpaintPipeline.from_pretrained(str(path),variant='fp16',torch_dtype=torch.float16,use_safetensors=True,local_files_only=True,add_watermarker=False)
        self.pipe.to('mps')
        self.pipe.enable_attention_slicing()
        self.pipe.vae.enable_slicing();self.pipe.vae.enable_tiling()
        self.pipe.set_progress_bar_config(disable=True)

    def __call__(self,image,mask):
        import numpy as np
        from PIL import Image
        from .inference import progress
        source=Image.fromarray(np.rint(image[0].transpose(1,2,0)*255).clip(0,255).astype(np.uint8))
        selection=Image.fromarray(np.rint(mask[0,0]*255).clip(0,255).astype(np.uint8))
        def tick(pipe,index,timestep,values):
            progress('processing',round((index+1)*100/getattr(pipe,'num_timesteps',self.steps)));return values
        try:
            with self.torch.inference_mode():
                result=self.pipe(prompt='photograph, clean natural background consistent with surrounding scene, realistic lighting, continuous textures',negative_prompt='text, watermark, logo, letters, artifacts, blurry',image=source,mask_image=selection,width=self.resolution,height=self.resolution,strength=.99,num_inference_steps=self.steps,guidance_scale=5.,generator=self.torch.Generator(device='cpu').manual_seed(0),callback_on_step_end=tick).images[0]
            return np.asarray(result.convert('RGB'),dtype=np.float32).transpose(2,0,1)[None]
        except RuntimeError as exc:
            if 'out of memory' in str(exc).lower():raise ValueError('sdxl_memory_error') from exc
            raise

    def close(self):
        self.pipe=None
        import gc
        gc.collect()
        self.torch.mps.empty_cache()
