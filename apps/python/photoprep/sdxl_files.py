"""Official SDXL FP16 files pinned to one immutable revision."""
SDXL_REPOSITORY = 'diffusers/stable-diffusion-xl-1.0-inpainting-0.1'
SDXL_REVISION = '115134f363124c53c7d878647567d04daf26e41e'
SDXL_FILES = (
    ('model_index.json', 690, '308a792b15086bf89807b88729ef80d33d5b8264b14a96b57d2c92b5ab7f5a53'),
    ('scheduler/scheduler_config.json', 479, 'a8e9a8517e8739938ea85819012bad195d41ccb3e11e2501cf196da64099b1f6'),
    ('text_encoder/config.json', 746, '46ae51fa8bde7817168d97faa0556cc0ac42ec0a7a53248bab4a52f8f5866f13'),
    ('text_encoder/model.fp16.safetensors', 246144867, 'fc83cf401d930147807e7c44021c164bcc5508c9d4cc0ff35f4e354685ca9cd0'),
    ('text_encoder_2/config.json', 758, 'fbcd3aad07a99e28d4c51550bd798903922083527ec69ad026f25699518af82d'),
    ('text_encoder_2/model.fp16.safetensors', 1389382884, 'a8622bd41f8d359df484fdf9de091edb9337a2fd747f0a5c9c320a62e24d1fd3'),
    ('tokenizer/merges.txt', 524619, '9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a'),
    ('tokenizer/special_tokens_map.json', 472, 'c4864a9376a8401918425bed71fc14fc0e81f9b59ec45c1cf96cccb2df508eac'),
    ('tokenizer/tokenizer_config.json', 737, '19d7b034cb0cc3ce9766c2231373ab8aa8991fc72e2c8f76558bfaae3de0d563'),
    ('tokenizer/vocab.json', 1059962, 'e089ad92ba36837a0d31433e555c8f45fe601ab5c221d4f607ded32d9f7a4349'),
    ('tokenizer_2/merges.txt', 524619, '9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a'),
    ('tokenizer_2/special_tokens_map.json', 460, 'f118ab3a983206e4f32583448de6bd6aae4ee21869135cef1f5848a753cdaab6'),
    ('tokenizer_2/tokenizer_config.json', 725, 'c9d23941f76a41cbd50eda9290f57be7828f0a7a677939e9ef181f7e12bd1bdf'),
    ('tokenizer_2/vocab.json', 1059962, 'e089ad92ba36837a0d31433e555c8f45fe601ab5c221d4f607ded32d9f7a4349'),
    ('unet/config.json', 1932, 'aaedf41fbcb29d2d8725241413b8525bd97005dea3f86d8056199469032537e9'),
    ('unet/diffusion_pytorch_model.fp16.safetensors', 5135178560, '6470840731e98cc16713ddf3ac7ee458c9fdbcb881a98c6727cd4a938f227d3f'),
    ('vae/config.json', 659, 'b822341e6125efedebffb8e3f35e7288aab06bb4c49853d50a16964bf104a727'),
    ('vae/diffusion_pytorch_model.fp16.safetensors', 167335338, '4ad62825e5c8b31eefb77355ba6693785619bf7d669d9b1a6fd9f19dec6d65b3'),
)
