# E0 — LaMa → Core ML: воспроизводимая конвертация и сравнение с Python/ONNX

**Дата:** 31.10.2026  
**Ветка:** `e0/lama-coreml`, создана от проверенного `d0d3cd4`.  
**Коммиты:** `bf8f7ec` — инструменты; `8303a66` — окружение и команды; `b5bd741` — этот отчёт.  
**Статус:** конвертация FP32 прошла; на 8 синтетических fixtures получен parity с Python/ONNX в пределах 1 LSB; outside-mask и alpha не изменяются. Это **не** доказательство универсального качества и **не** готовность приложения.

## 1. Короткий результат

* Исходный PyTorch big-lama загружен, веса сопоставлены с ONNX: 452 именованных инициализатора совпадают побитово; 154 анонимных `onnx::Conv_*` совпадают с BN-folded весами (≤1.2e-7); PyTorch vs ONNX output max 0.0275 (0..255), mean 0.00014.
* Получен `.mlpackage` FP32, fixed 512×512, ML Program, macOS 14 target, tensor I/O. Package 205 208 906 B, compiled 195.9 MiB; conversion 21.39 s.
* Core ML GPU/ALL vs ONNX на 8 fixtures: max 0.000648 (0..255), mean 4.3e-6, ни одного пикселя >1 LSB. CPU_ONLY: max 0.004692.
* Финальный Qt-композит: `changed_outside = 0`, `changed_alpha = 0` для всех движков; Core ML vs ONNX final max 1 LSB, mean 4e-7.
* Скорость на этом Mac: Core ML GPU/ALL warm median 0.136 s против ONNX CPU 1.918 s и PyTorch CPU 2.189 s. Core ML raw model load ~0.1–0.2 s; Python-обёртка с импортом ~2.7 s.
* Память: Core ML GPU phys peak ~929 MiB, RSS peak ~651 MiB; ONNX 717/958 MiB; PyTorch peak 3.7/3.9 GiB (в основном загрузка checkpoint).
* `MLComputePlan`: 2 954 операции предпочитают `MLGPUComputeDevice`, 4 866 — без определённого устройства; **Neural Engine не указан**. `ALL` и `CPU_AND_GPU` практически одинаковы; ANE не заявляем.

## 2. Что именно проверялось

### 2.1. Происхождение

| Артефакт | Значение |
|---|---|
| Исходный код | `https://github.com/Carve-Photos/lama`, commit `f5fb39a18022c34a71bf9a47a6ec393c804b49ca`, Apache-2.0 |
| Source zip | SHA256 `87ae34629d745e16f186f848fc676e7d0142c78a9783cf7099336396c3c4c398` |
| Веса | `https://huggingface.co/smartywu/big-lama/resolve/main/big-lama.zip` |
| big-lama.zip | SHA256 `f1b358ca24093b93a106183b98a3dea6e8ed09f3b43ea7251eb2c81e7b4575f6` |
| `models/best.ckpt` | SHA256 `fccb7adffd53ec0974ee5503c3731c2c2f1e7e07856fd9228cdcc0b46fd5d423` |
| `config.yaml` | SHA256 `4fdeed49926e13b101c4dd9e193acec9e58677dfdb4ba49dd6a3a8927964e2a7` |
| ONNX oracle | `lama_fp32.onnx`, SHA256 `1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6` |
| Model package | SHA256 `eaaaa45fe2c58fe7395f6c634813ce75944837e3b177c743b51ad73e56169cf0` |
| Compiled model | SHA256 `5df23cc8fc3959032d2e634c41d602e3ef1e2d387047ea167fe102c144836f2a` |

ONNX model card: `https://huggingface.co/Carve/LaMa-ONNX` — custom `FourierUnitJIT`, fixed 512×512, opset 17, Apache-2.0. Код LaMa — Apache-2.0; вопрос распространения самих весов и конвертированного пакета всё равно требует отдельного лицензионного подтверждения. Веса и модели не коммитились.

### 2.2. Окружение

* Отдельный venv, Python 3.12.4, macOS 27.2 arm64, Apple M3 Max, 36 GiB.
* `torch==2.7.1`, `torchvision==0.22.1`, `coremltools==9.0`, `onnx==1.17.0`, `onnxruntime==1.22.0`, `numpy==2.2.6`, `Pillow==11.3.0`; полный pinned список — [requirements-e0.txt](Tools/e0/requirements-e0.txt).
* Coremltools предупреждает, что тестировался с torch 2.7.0; использован 2.7.1. Предупреждение записано; parity проверен.
* Python-приложение и его окружение не изменялись.

### 2.3. Соответствие весов ONNX

`check_weights.py`:

* 606 ONNX initializers; 452 с совпадающим именем — **bit-exact**, max diff 0.
* 154 `onnx::Conv_*` — анонимные веса ранних/up/FFC слоёв; для представительных слоёв (`model.1..4`) BN folding даёт совпадение с ONNX:
  * max diff веса ≤ 5.96e-8;
  * max diff bias ≤ 1.19e-7.
* 152 `num_batches_tracked` — счётчики, в inference не участвуют; в ONNX отсутствуют, это ожидаемо.
* Функциональная проверка на одинаковых случайных 512×512 tensors: PyTorch vs ONNX `max=0.027496`, `mean=0.0001405`, `p99=0.003616`, `>1 LSB = 0`, `>2 LSB = 0`.
* На 8 fixtures PyTorch vs ONNX `max=0.003914`, `mean=1.93e-5`.

Вывод: ONNX является корректным функциональным эквивалентом исходного checkpoint; анонимные веса объясняются BN folding, а не другим чекпоинтом.

## 3. Конвертация

### 3.1. Путь

ONNX → Core ML напрямую не поддерживается Unified Conversion API. Поэтому конвертировался исходный PyTorch LaMa из Carve-репозитория:

1. Загружен `FFCResNetGenerator` с `resnet_conv_kwargs.use_jit=True`.
2. Загружен `best.ckpt` strict; 50 975 875 параметров.
3. Обёртка повторяет ONNX-экспорт: `masked = image*(1-mask)`, `cat(masked,mask)`, `pred = generator(...)`, `blend = mask*pred+(1-mask)*image`, `clamp(*255)`.
4. `torch.jit.trace` с фиксированными 512×512, batch 1.
5. `ct.convert(convert_to="mlprogram", minimum_deployment_target=macOS14, compute_precision=FLOAT32, inputs=TensorType...)`.
6. `.mlpackage` → `coremlcompiler` → `.mlmodelc`.

### 3.2. Препятствия и решения

| Препятствие | Диагностика | Решение | Проверка |
|---|---|---|---|
| `torch.jit.script` не работает | `TupleConstruct cannot be used as a value`, `ffc.py:398` | fixed-shape `torch.jit.trace` | eager vs traced max 0 |
| Core ML `sqrt` не принимает int32 | `sqrt` input `tensor[1,int32]` из `FourierUnitJIT.rttn` | нормализация по Python `float sqrt(N)`; N статичен 512 | eager before/after max 0 |
| Нет lowering для `tensordot` | `NotImplementedError: op 'tensordot'` | эквивалентный `einsum` для осей H/W | eager before/after max 0 |
| Coremltools warning torch 2.7.1 | тестировался 2.7.0 | зафиксировано; parity проверен | все тесты ниже |
| `model.mlmodel`/Manifest не byte-identical при повторной конвертации | metadata/порядок | weights hash одинаков; outputs идентичны | повторная конвертация: `weight.bin` SAME, output max 0 |

`patch_ffc.py` — **только для конвертации**, не меняет архитектуру или веса; обе замены математически эквивалентны и проверены в eager-режиме. Патч не входит в приложение.

### 3.3. Спецификация модели

* `.mlpackage` / `.mlmodelc`; ML Program, spec version 8, target macOS 14.
* Inputs: `image` float32 `[1,3,512,512]`, `mask` float32 `[1,1,512,512]`.
* Output: `output` float32 `[1,3,512,512]`, значения 0..255.
* FP32; без квантования, palettization, FP16.
* Fixed batch 1; flexible shapes не поддерживаются и не нужны для текущего контекста 512.

## 4. Пороги сравнения и их обоснование

Все сравнения — в **8-битной шкале кодовых значений 0..255**, не в 0..1. `d = |a-b|`.

| Gate | Порог | Обоснование |
|---|---|---|
| Tensor max vs ONNX | ≤ 1.0 | 1 LSB — минимальная различимая разница после uint8; если больше, это уже алгоритмическое/препроцессинговое расхождение, а не округление |
| Tensor mean | ≤ 0.1 | исключает систематический сдвиг; при случайных FP-различиях среднее на порядки меньше |
| Tensor p99 | ≤ 1.0 | хвост не должен содержать устойчивых выбросов |
| Pixels > 2 LSB | 0 | два кода уже заметны на градиенте/линиях |
| Final outside mask | 0 changed pixels | обязательный контракт: вне маски RGBA не меняются |
| Final alpha | 0 changed pixels | alpha не меняется никогда |
| Final vs ONNX | max ≤ 1 LSB | Qt-ресемплинг и uint8-усечение могут дать максимум 1 код; больше — реальное расхождение |
| Clean-image MAE | не хуже ONNX + визуальная проверка | MAE поощряет размытие; абсолютное качество нельзя доказать одной метрикой |

Фактические значения значительно строже: Core ML GPU/ALL tensor max 0.000648, mean 4.3e-6; final max 1, mean 4e-7. FP16 в E0 не принимался и не проверялся.

## 5. Результаты

### 5.1. Tensor parity (8 fixtures, 512×512, 0..255)

| Движок | max | mean | p99 | >1 LSB | >2 LSB | warm median, s |
|---|---:|---:|---:|---:|---:|---:|
| ONNX re-run | 0.000046 | 7.3e-7 | — | 0 | 0 | 1.900 |
| PyTorch CPU | 0.003914 | 1.93e-5 | 0.003110 | 0 | 0 | 2.105 |
| Core ML CPU_ONLY | 0.004692 | 1.66e-5 | 0.003493 | 0 | 0 | 2.061 |
| Core ML CPU_AND_GPU | 0.000648 | 4.32e-6 | 0.000486 | 0 | 0 | 0.136 |
| Core ML ALL | 0.000648 | 4.32e-6 | 0.000486 | 0 | 0 | 0.136 |

ONNX re-run отличается от oracle на 4.6e-5 из-за потоковой недетерминированности CPU; это меньше 0.001 LSB.

### 5.2. Финальный композит через точный Python/Qt pipeline

| Движок | changed outside | changed alpha | max vs ONNX final | mean vs ONNX final | MAE vs clean (min/max) |
|---|---:|---:|---:|---:|---:|
| ONNX | 0 | 0 | 0 | 0 | 1.036 / 5.085 |
| PyTorch | 0 | 0 | 1 | 2.1e-6 | 1.035 / 5.085 |
| Core ML CPU_ONLY | 0 | 0 | 1 | 1.9e-6 | 1.036 / 5.085 |
| Core ML CPU_AND_GPU | 0 | 0 | 1 | 4e-7 | 1.036 / 5.085 |
| Core ML ALL | 0 | 0 | 1 | 4e-7 | 1.036 / 5.085 |

Per-case MAE vs clean (inside mask), ONNX/Core ML:

| Case | flat | gradient | texture | lines | edge | border | soft-logo | alpha |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ONNX | 1.362 | 1.049 | 4.579 | 2.655 | 1.813 | 5.085 | 1.049 | 1.036 |
| Core ML GPU | 1.362 | 1.049 | 4.579 | 2.655 | 1.813 | 5.085 | 1.049 | 1.036 |

Визуально (1:1 montage для `lines`, `texture`, `alpha`) отличий, кроме 1–2 пикселей на 1 LSB, не найдено. Артефакты самого reference сохраняются: сглаживание повторяемой фактуры и потолок на краю кадра; конвертация их не добавляет. Это не означает, что LaMa достаточно хороша для всех реальных логотипов.

### 5.3. Скорость и память

Свежий процесс на один движок; `phys_footprint` — `task_vm_info`, RSS — `psutil`; пик сэмплировался каждые 10 мс. `load, s` включает импорт библиотеки и загрузку модели; отдельно: загрузка уже скомпилированной модели ~0.03–0.21 s, `.mlpackage` с компиляцией ~4.1–4.9 s (не в таблице).

| Движок | load, s | warm, s | phys peak, MiB | RSS peak, MiB | ru_maxrss, MiB |
|---|---:|---:|---:|---:|---:|
| Core ML CPU_AND_GPU | 2.71 | 0.135 | 929 | 651 | 778 |
| Core ML ALL | 2.81 | 0.137 | 920 | 668 | 805 |
| Core ML CPU_ONLY | 2.46 | 2.127 | 287 | 797 | 797 |
| ONNX CPU | 2.04 | 1.918 | 717 | 958 | 958 |
| PyTorch CPU | 2.28 | 2.189 | 3 668 | 3 943 | 3 943 |

* Core ML GPU: первый warm-up ~0.43–0.45 s, затем 0.135–0.137 s.
* PyTorch peak 3.7 GiB приходится на загрузку checkpoint/state_dict; steady phys ~464 MiB, RSS ~741 MiB. Для приложения это довод в пользу Core ML worker и против загрузки PyTorch в UI-процессе.
* Core ML CPU_ONLY `phys_footprint` занижен относительно RSS (287 vs 797 MiB); для admission нельзя опираться только на phys. RSS — консервативная оценка.
* Все цифры — один Mac, одна модель, один кейс `texture`; не p95 по парку Mac и не гарантия для 8 GiB.

### 5.4. Compute units и Neural Engine

`MLComputePlan` для `.mlmodelc` при `CPU_AND_GPU` и `ALL`:

* 7 820 операций;
* 2 954 — preferred `MLGPUComputeDevice`;
* 4 866 — устройство не определено (в основном константы/служебные операции);
* **0 определённых операций с Neural Engine**; 4 866 операций без определённого устройства;
* estimated cost sum 1.0.

`ALL` и `CPU_AND_GPU` дают одинаковую скорость и одинаковый output. **Neural Engine не подтверждён**; заявлять ANE-ускорение нельзя.

## 6. Наблюдение о падении

При попытке загрузить в одном Python-процессе три Core ML варианта (`CPU_ONLY`, `CPU_AND_GPU`, `ALL`) вместе с PyTorch получен `Segmentation fault: 11` (exit 139). Воспроизведено в измерительном harness; backtrace нет. Каждый движок в отдельном процессе работает стабильно, все результаты выше получены так.

Это не атрибутируется модели: скорее взаимодействие нескольких Core ML runtime/моделей и PyTorch в одном процессе. Для Native это дополнительный аргумент за **один движок/одну модель на worker-процесс** и за изоляцию падений. В рамках E0 UI/worker не реализовывались.

## 7. Ограничения

* Только 8 синтетических 768×512 fixtures, по одной прямоугольной маске; нет реальных фотографий, кисти, разрозненных/крупных логотипов, multi-pass, 40 MP и Native alpha path.
* Только один Mac: Apple M3 Max, 36 GiB, macOS 27.2 arm64. Нет 8/16/24 GiB, Intel, macOS 14. Переносить цифры на них нельзя.
* Core ML запускался через Python `CompiledMLModel`/`MLModel`; приложение может иметь другой baseline памяти и другую загрузку.
* FP32 only; FP16/quantization/palettization/ANE не проверялись и не приняты.
* `MLComputePlan` — anticipated device usage, не фактический счётчик выполнения; ANE не обнаружен, но это не абсолютное доказательство.
* Нет полного 40 MP pipeline, нет decode/encode памяти, нет отмены/watchdog/worker.
* Package hash не byte-identical при повторной конвертации из-за metadata; `weight.bin` идентичен, outputs идентичны. Для manifest использовать semantic/weight hash и output parity, а не только hash каталога.
* Лицензия кода Apache-2.0; лицензия весов и право распространения 196 MiB пакета требуют отдельного подтверждения.

## 8. Воспроизведение

Полные команды — в [Tools/e0/README.md](Tools/e0/README.md). Кратко:

```bash
# отдельное окружение
python3.12 -m venv <e0-venv>
<e0-venv>/bin/python -m pip install -r apps/native/Tools/e0/requirements-e0.txt

# 1) веса vs ONNX
<e0-venv>/bin/python apps/native/Tools/e0/check_weights.py \
  --lama-src <e0-data>/src/lama --config <e0-data>/big-lama/config.yaml \
  --checkpoint <e0-data>/big-lama/models/best.ckpt \
  --onnx <models>/lama_fp32.onnx --out <e0-data>/work/e0/results/weights.json

# 2) конвертация
TORCH_HOME=<e0-data> PYTHONPATH=<e0-data>/src/lama \
<e0-venv>/bin/python apps/native/Tools/e0/convert_lama.py \
  --lama-src <e0-data>/src/lama --config <e0-data>/big-lama/config.yaml \
  --checkpoint <e0-data>/big-lama/models/best.ckpt \
  --onnx <models>/lama_fp32.onnx --source-zip <e0-data>/src/carve_lama.zip \
  --out-dir <e0-data>/work/e0/models

# 3) oracle — в существующем app-Python
QT_QPA_PLATFORM=offscreen PYTHONPATH=<repo>/apps/python \
<app-python> apps/native/Tools/e0/oracle.py --app-python <repo>/apps/python \
  --onnx <models>/lama_fp32.onnx --out <e0-data>/work/e0/fixtures

# 4) один движок на процесс; повторить для onnx/torch/coreml_*
<e0-venv>/bin/python apps/native/Tools/e0/run_engine.py \
  --fixtures <e0-data>/work/e0/fixtures --engine coreml_cpu_gpu \
  --model <e0-data>/work/e0/models/LaMa-fp32.mlmodelc --compiled \
  --out <e0-data>/work/e0/results

# 5) композит через Python/Qt
QT_QPA_PLATFORM=offscreen PYTHONPATH=<repo>/apps/python \
<app-python> apps/native/Tools/e0/composite.py \
  --fixtures <e0-data>/work/e0/fixtures --app-python <repo>/apps/python \
  --out <e0-data>/work/e0/results/composite.json

# 6) память/скорость, 7) compute plan, 8) summary
```

Ключевые артефакты в `work/e0/` (игнорируются Git): `.mlpackage`, `.mlmodelc`, fixtures, output PNG/NPY, JSON. Веса и модели не коммитились.

## 9. Рекомендуемый следующий шаг

1. **Зафиксировать FP32-модель как reference** для Native: manifest, SHA256, fixed 512, tensor I/O, CPU_AND_GPU. Не объявлять её универсально качественной.
2. **E1: изолированный worker** с одним compiled `.mlmodelc`, один проход, straight RGBA8, точный composite, отмена/watchdog, память по измеренному пику (~0.9–1.0 GiB для GPU/ALL на этом Mac). Не загружать PyTorch и несколько Core ML вариантов в UI-процесс.
3. **До UI-интеграции** прогнать реальные фото и 40 MP source: кирпич/ткань/волосы/листва, тонкие линии, край кадра, разрозненные маски, три прохода, alpha=0/1–254. Проверить полный Native pipeline, не только Python composite.
4. **FP16/ANE — только после** визуальной приёмки FP32. ANE не обнаружен; `ALL` не даёт выигрыша на этом Mac. FP16 может изменить FFT-фазы и тонкие линии; начинать с сравнения tensor parity и 100% crops.
5. **Лицензия/поставка:** 196 MiB package; решить bundle vs explicit download; подтвердить право распространения весов; добавить SHA256/каталог; не коммитить веса.
6. **Не использовать MI-GAN как default**: он остаётся optional/test double; его uint8/inverse-mask adapter нельзя смешивать с LaMa.

## 10. Подтверждено и гипотеза

**Подтверждено на этом Mac и этом наборе:**

* ONNX функционально соответствует checkpoint; 452 named initializers bit-exact, anonymous weights объясняются BN folding; output max 0.0275.
* FP32 Core ML LaMa конвертируется; fixed 512, tensor I/O, package 196 MiB.
* Tensor parity Core ML GPU/ALL vs ONNX max 0.000648; final composite outside/alpha exact, max 1 LSB.
* Core ML GPU ~0.136 s/prediction; ONNX CPU ~1.918 s; PyTorch CPU ~2.189 s на этом Mac.
* Core ML GPU phys peak ~929 MiB; PyTorch load peak ~3.7 GiB.
* `MLComputePlan` не показывает ANE; `ALL` ≈ `CPU_AND_GPU`.

**Гипотеза / не проверено:**

* Поведение на 8/16/24 GiB, Intel, macOS 14 и других GPU/ANE.
* Качество на реальных фотографиях, крупных/разрозненных логотипах, multi-pass и 40 MP.
* FP16/quantization/ANE без визуальной деградации.
* Полный Native worker/XPC, отмена, watchdog и жёсткий memory limit.
* Совместимость с Python-сессиями и экспортом (вне E0).
* Лицензионное право распространения 196 MiB модели.

**Итог:** E0 можно считать успешным как **parity-эксперимент**: FP32 Core ML LaMa воспроизводит Python/ONNX на проверенном наборе с запасом по порогам и даёт заметное ускорение на GPU. Это ещё не приёмка качества удаления логотипов и не разрешение на UI-интеграцию без реальных фото, 40 MP и worker-изоляции.
