# E1 — один нативный проход LaMa: worker, маска, canvas, память и отмена

**Дата:** 31.10.2026  
**Ветка:** `e1/lama-native-worker`, создана от E0-коммита `101f6bf`.  
**Статус:** E0 дополнительно ужесточён и повторно проверен; E1 реализован как ограниченный вертикальный срез. Модель, worker, straight-RGBA pipeline, brush/eraser, undo, один проход, before/after, progress/cancel/timeout и self-exec worker работают. Полная приёмка на реальных фотографиях и интерактивный UI-прогон остаются ограничением.

## 1. Коммиты

| Коммит | Содержание |
|---|---|
| `101f6bf` | база: принятый E0 |
| `99f71f7` | E0 fail-closed verification |
| `9d3f669` | E1 core: straight RGBA, mask, context, composite, tests |
| `9b9fb9c` | E1 worker + self-test + минимальный canvas/UI |
| этот отчёт | STATUS/README/E1 report |

Ветка локальная, не публиковалась; точные хеши — в `git log`.

## 2. E0 укрепление

Добавлен `Tools/e0/verify_e0.py`. Он **падает до загрузки модели/сессии**, если не совпал ожидаемый SHA256:

* ONNX `1faef530…`;
* checkpoint `fccb7adf…`;
* config `4fdeed49…`;
* source zip `87ae3462…`;
* `.mlmodelc` `5df23cc8…` или `.mlpackage` `eaaaa45f…`.

После загрузки проверяются:

* shape `image [1,3,512,512]`, `mask [1,1,512,512]`, `output [1,3,512,512]`;
* dtype float32 и отсутствие NaN/Infinity;
* tensor parity: max ≤ 1 LSB, mean ≤ 0.1, p99 ≤ 1, ноль `>2 LSB`;
* `changed_outside == 0`, `changed_alpha == 0` на финальном композите;
* final max vs ONNX ≤ 1 LSB.

**Фактический повторный результат (31.10.2026):** 8/8 cases passed; worst tensor max `0.000664`; outside/alpha zero; final max 1 LSB. Полный JSON — `work/e0/results/verify_e0.json` (вне репозитория). Это повторное измерение сохранённой Core ML-модели, а не только прежний отчёт.

## 3. Что реализовано в E1

### 3.1. Отдельный native worker

* Приложение запускает **свой же подписанный бинарник** с `--photoprep-worker <job-dir>`; это отдельный процесс, без Python, SwiftUI и AppKit.
* Worker загружает одну `LaMa-fp32.mlmodelc` (`computeUnits = .cpuAndGPU`), читает два float32-файла `[1,3,512,512]` и `[1,1,512,512]`, проверяет выходную форму/ finite, пишет `output.f32` и `response.json`.
* Parent (`InferenceWorkerClient`) создаёт job-каталог в Application Support контейнера, запускает процесс, ждёт с таймаутом 120 с, проверяет `jobID`, убивает процесс при cancel/timeout (`SIGTERM`, затем `SIGKILL`), удаляет job-каталог.
* Подпись и App Sandbox не обходятся: дочерний процесс наследует sandbox родителя; модель читается из `Contents/Resources/Models`, job-файлы — из контейнера приложения. Проверено на подписанном ad-hoc app.

### 3.2. Straight RGBA8 и качество

* `StraightImage` — RGBA8 straight alpha, top-left origin.
* `StraightImageDecoder`: проверка header/размеров/памяти; ImageIO full decode с `shouldCacheImmediately`; чтение raw `CGImage` только для 8-bit RGB/RGBA; **premultiplied alpha с alpha<255 отклоняется**, а не портится молча; hidden RGB при alpha=0 и 1–254 сохраняется; EXIF 1–8 применяется к буферу.
* `MaskRenderer`: grayscale8, top-left, round caps/joins, antialiasing, erase, single point.
* `RetouchPreprocessor`: Python-совместимый `context_rect` (ties-to-even), crop/resize 512, mask threshold + 5×5 dilation, composite по исходному coverage/255; alpha не меняется; вне маски копируются исходные байты.
* `RetouchPreprocessor.composite` проверяет форму/finite и сохраняет outside/alpha; ошибки — явные.

### 3.3. UI

* `BrushCanvas` (NSViewRepresentable): fit-изображение, brush/eraser, normalized points, live mask overlay, undo last stroke, clear.
* `RetouchPanel`: brush/eraser, size, undo, clear, «Удалить логотип», progress, cancel, before/after, error codes.
* `WorkspaceModel`: один retouch job; `jobID`, source identity, mask revision, edit revision; поздний/устаревший результат не применяется; cancel/timeout/падение worker не меняет выбранное фото.
* Ошибки: empty mask, source changed, model missing, unsupported alpha, memory, timeout, worker crash, invalid output.

### 3.4. Исправления каркаса

* Импорт и preview больше не делят один `Task`/`busy`: выбор фото больше не отменяет импорт.
* Memory pressure event читает `source.data` **синхронно в handler**, а не позже в Task.
* Перед применением результата повторно считается `SourceIdentity` (size/mtime/SHA256); изменение файла → `source_changed`, результат не применяется.
* Job-каталог удаляется через `defer` на всех путях, включая поздний/устаревший результат.
* При закрытии окна/terminate вызывается `cancel()`: worker убивается, job-каталог убирается.

## 4. Проверки и фактические результаты

### 4.1. Тесты

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  swift test --disable-sandbox --package-path apps/native \
  --scratch-path /tmp/e1-swift-tests
```

**14 Swift tests passed:** 3 preview, 5 policy, 6 retouch (hidden RGB/alpha, mask top-left/eraser, context rect, outside/alpha composite, EXIF 6 full decode, source identity).

### 4.2. Сборка

```bash
xcodebuild -project apps/native/PhotoPrepNative.xcodeproj -scheme PhotoPrepNative \
  -configuration Debug -destination 'platform=macOS,arch=arm64' \
  -derivedDataPath /tmp/e1-build build CODE_SIGNING_ALLOWED=NO
```

Сборка успешна. Модель копируется build-phase в `Contents/Resources/Models/LaMa-fp32.mlmodelc`; app ~198 MiB. Для сборки вне текущего checkout задайте `PHOTOPREP_LAMA_MODEL`. Ad-hoc подпись и запуск проверены; Python не требуется.

### 4.3. End-to-end self-test (реальный worker + preprocess + composite)

```bash
"PhotoPrep Native.app/Contents/MacOS/PhotoPrep Native" --photoprep-e1-selftest
PHOTOPREP_E1_WIDTH=4000 PHOTOPREP_E1_HEIGHT=3000 ... --photoprep-e1-selftest
PHOTOPREP_E1_WIDTH=8000 PHOTOPREP_E1_HEIGHT=5000 ... --photoprep-e1-selftest
```

Синтетические источники с градиентом, линиями и alpha; маска из трёх штрихов; полный путь parent → worker → composite:

| Источник | outside changed | alpha changed | rect | app phys after | полный wall time |
|---|---:|---:|---|---:|---:|
| 1024×768 (~0.8 MP) | 0 | 0 | 822×768 | 20.6 MiB | 3.35 s |
| 4000×3000 (12 MP) | 0 | 0 | 3210×3000 | 121.5 MiB | 12.49 s |
| 8000×5000 (40 MP) | 0 | 0 | 6150×5000 | 373.7 MiB | 37.56 s |

Worker отдельно: load ~1.15 s (first) / 0.07–0.08 s (compiled cache, subsequent runs), predict ~0.40 s; max RSS ~689 MiB на 512-тензорах. 40 MP app + worker ≈ 1.06 GiB (phys app + worker RSS; не единый измеренный footprint).

`Task.detached` выносит mask render/preprocess/composite за MainActor, поэтому UI не должен блокироваться на 40 MP; это проверено кодом, но не отдельным UI-тестом.

### 4.4. Отмена, таймаут, падение

```bash
... --photoprep-e1-timeout-selftest
... --photoprep-e1-crash-selftest
... --photoprep-e1-cancel-selftest
```

Все три прошли:

* timeout — worker остановлен;
* crash (missing model) — приложение пережило `processExited(1)`;
* cancel — `cancelled`, процесс не остался.

После 20 последовательных self-test запусков (1024×768) app phys после каждого `20 627 936 B` (стабильно), late/leftover процессов нет. Это 20 **свежих** app+worker процессов, не один долгоживущий процесс; in-process 50-pass серия ещё не выполнена.

## 5. Ограничения приёмки

* **Реальные фотографии не использованы**: в репозитории нет разрешённых реальных фото с логотипами; пользовательские/сторонние изображения не брались. Поэтому пункт «реальные фото со сложной фактурой, линиями и логотипом у края» **не закрыт**. Нужны разрешённые фото от владельца.
* **Интерактивный UI-прогон не подтверждён автоматизированно**: приложение собирается, подписывается, запускается, панель/controls отображаются; автоматизация NSOpenPanel/кисти не доведена. Canvas/brush/eraser/undo проверены кодом и core-тестами, но не полным UI-сценарием.
* **12/40 MP** проверены на синтетическом буфере, а не на реальном 40 MP файле с decode; полный wall time включает генерацию тестового буфера и mask, поэтому 37.56 s — верхняя/нерепрезентативная оценка. Полный файл 40 MP и UI-отклик ещё измерить.
* **Серия 20–50 проходов в одном процессе** не выполнена; 20 свежих процессов стабильны.
* **Memory pressure injection** не выполнен; обработчик исправлен, но безопасная инъекция warning/critical ещё нужна.
* Нет 8/16 GiB, Intel, macOS 14; только Apple M3 Max 36 GiB, macOS 27.2.
* Нет визуального сравнения Native vs Python на одинаковых реальных масках; E0 parity модели есть, но Native resize/composite отличается от Qt и требует blind-сравнения.
* Нет crop/logo/export/session/MI-GAN/SDXL/FP16/quantization — по условию E1.
* Worker — self-exec Process, не XPC service; sandbox наследуется, crash-домен отдельный, но lifecycle/launchd-политики XPC нет.
* Модель 196 MiB лежит в app bundle; лицензия/распространение всё ещё требуют подтверждения.

## 6. Следующий шаг

1. Получить разрешённые реальные фото (кирпич/ткань/волосы/листва, логотип у края, тонкие линии) и прогнать полный UI-сценарий: open → brush/eraser → undo → process → before/after → cancel.
2. Повторить 40 MP на реальном файле; измерить decode + UI responsiveness; оптимизировать 40 MP mask/composite (vImage/Accelerate или ROI), не ухудшая outside/alpha.
3. Провести 20–50 проходов в одном процессе worker/app; memory pressure injection; закрытие окна во время prediction; forced worker kill; 8/16 GiB.
4. Сравнить Native composite с Python на одинаковых масках (blind 100/200%); проверить hidden RGB/alpha на реальных PNG.
5. После этого — XPC/helper hardening, затем crop/logo/export/sessions по ROADMAP.

## 7. Итог

E1 даёт работающий ограниченный vertical slice: одно нативное приложение без Python, отдельный Core ML worker, straight-RGBA маска/композит, brush/eraser/undo, один проход, before/after, прогресс, отмена, timeout, crash-survival, source identity и фиксы импорта/memory pressure. На синтетике 1/12/40 MP outside и alpha точны; worker и app не оставляют процессов после cancel/timeout. Полная приёмка E1 на реальных фотографиях и интерактивном UI пока не закрыта — это следующий ограниченный шаг, а не повод объявлять готовность.
