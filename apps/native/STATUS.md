# PhotoPrep Native — текущий статус

31.10.2026, branch `e1.5/session-integrity`, base E1.4 `cfaa6ce` (E0 `101f6bf`).
Исторические отчёты не переписаны: [E0-LAMA-COREML.md](E0-LAMA-COREML.md),
[E1-LAMA-WORKER.md](E1-LAMA-WORKER.md), [E1.1-QUALITY-STABILITY.md](E1.1-QUALITY-STABILITY.md),
[E1.2-ACCEPTANCE.md](E1.2-ACCEPTANCE.md),
[E1.3-QUALITY-HISTORY.md](E1.3-QUALITY-HISTORY.md),
[E1.4-HISTORY-SESSIONS.md](E1.4-HISTORY-SESSIONS.md),
[E1.5-SESSION-INTEGRITY.md](E1.5-SESSION-INTEGRITY.md), [REFERENCE-RESULTS.md](REFERENCE-RESULTS.md).

## Реально работает

* **E0 принят и ужесточён.** `Tools/e0/verify_e0.py` проверяет ожидаемые SHA256
  ONNX/checkpoint/config/source/model до загрузки, затем shape, float32,
  NaN/Infinity, tensor-пороги, outside-mask и alpha. Повторный прогон сохранённой
  Core ML модели: 8/8 cases, worst tensor max 0.000664, outside/alpha zero.
* **Нативная сборка и identity.** Xcode-проект, `PhotoPrep Native.app`,
  `com.sirdimitry.PhotoPrep.Native`, RU/EN, темы, App Sandbox read-only,
  без сети. Модель LaMa FP32 лежит в `Contents/Resources/Models`, не в Git.
* **Один проход LaMa в отдельном native worker.** Приложение запускает свой же
  подписанный бинарник с `--photoprep-worker`; worker загружает одну
  `.mlmodelc`, валидирует вход/выход, пишет response. Python не требуется.
* **Минимальный canvas.** Brush/eraser, normalized mask, live overlay,
  undo last stroke, clear, размер кисти.
* **Один проход и сравнение.** Process → progress → result → before/after;
  cancel, timeout (120 s), понятные ошибки; поздний/устаревший результат не
  применяется (jobID, source identity, mask/edit revision).
* **Straight RGBA8.** Hidden RGB/alpha сохраняются; premultiplied alpha с
  alpha<255 отклоняется, а не портится; outside-mask копируется побайтово;
  alpha не меняется; EXIF 1–8 применяется.
* **Исправления каркаса.** Импорт и preview разведены: выбор фото больше не
  отменяет импорт. Memory pressure `source.data` захватывается синхронно.
  Source identity (size/mtime/SHA256) проверяется до применения результата.
* **Ресурсы.** Job-каталог удаляется на всех путях; закрытие окна/terminate
  убивает worker; после cancel/timeout/crash процессов не остаётся.
* **E1.1 качество.** Clamp ограничен context rect; float→uint8 до resize;
  Qt-совместимый mask upscale. Astronaut-ghost устранён: final max 13/mean 0.083
  против Python (было 34/0.105); coffee max 13/mean 0.056; grass max 16/mean 0.118.
  Остались 5 mask-пикселей и различия hair edge/травы.
* **E1.1 отмена/ошибки.** Отмена привязана к job; новый запуск не сбрасывает
  старую отмену; busy не снимается до подтверждённого выхода. Отдельно
  проверены ordinary error (model_load_failed), SIGKILL crash (status 9),
  hang timeout, cancel-before-start и restart после cancel.
* **E1.1 decoder.** Только RGB; CMYK/alphaOnly/float/non-default byte order
  отклоняются; noneSkipFirst/Last явно RGBX/XRGB; проверяются bytesPerRow и
  длина; ICC сохраняется и прикладывается без конверсии.
* **E1.1 UI.** Реально пройдены debug-import, brush, eraser, undo, process,
  before/after, cancel; закрытие окна во время 40 Мп обработки не оставило
  процессов/job-файлов. NSOpenPanel, photo switch и 20 UI-проходов — нет.

* **E1.2 завершение worker.** SIGTERM → 0.5 s → SIGKILL → waitUntilExit; job
  cleanup/next job только после подтверждённого выхода. Hard-kill self-test:
  0.83 s, pid_alive=false; cancel→restart: старый PID мёртв, новый отличается,
  процессов нет.
* **E1.2 отмена в фазах.** context scan, upscale/downscale, prepare, dilation,
  composite проверяют флаг. Latency 6000×4000: context 36 µs, scale 3.6 ms,
  dilate 0.28 ms, composite 104 ms.
* **E1.2 большой контекст.** Qt-совместимый area downscale 1353→512:
  image/mask max 0, model max 0.00206, final max 1 (0 >1 LSB) на 2 Мп.
* **E1.2 20 полных app-проходов.** 20/20 ok, 64.02 s, app phys peak 18.29 MB,
  residual 17.52 MB, без процессов/Jobs.
* **E1.2 UI.** Реальный NSOpenPanel (debug start dir), 40 Мп pass 16.56 s
  (decode 4.90, prepare 7.31, worker 2.19, composite 2.15), photo switch,
  source-change error, cancel/close clean.
* **E1.2 pressure.** warning/critical во время preparing и processing: noResult,
  idle, worker/Jobs cleanup; model-level injection.

* **E1.3 RGB rounding.** Python/8-bit transition измерен: round-to-nearest
  (ties-even) вместо fractional float. Native RGB + Python mask: astronaut
  max 9.53→2.90, coffee 13.18→1.98, brick 8.75→1.15; native final mean
  astronaut 0.028, coffee 0.011, brick 0.022.
* **E1.3 mask contribution.** Остаточный max astronaut/brick — 5 mask-пикселей
  round-cap; coffee — 1. Большой контекст 1353→512: RGB/mask max 0, final max 1
  (0 >1 LSB). 19 Swift tests, включая up/down/mixed scale.
* **E1.3 edit state/history.** Per-photo mask + pass recipes; cumulative source;
  clear mask не удаляет ретушь; undo pass возвращает маску; switch сохраняет
  состояние; LRU cache 384 MiB, replay после eviction; history UI pass count.
  Self-test: outside/clear/toggle/replay/switch/undo/cancel-mask = yes.

* **E1.4 cache identity.** Cache key = SourceIdentity + pass UUIDs + modelID +
  mask fingerprint. Source change clears result/recipes; no stale display.
* **E1.4 modelID/lifecycle.** RetouchPass.modelID; replay uses pass model, not
  current. cancelAndWait on switch/close; restore clears activeID/busy/task on
  stale paths; commit checks jobID/source/recipe/cancel; replay obeys budget;
  resultImage released when LRU evicts current key.
* **E1.4 undo order.** Undo pass returns removed mask + current refinement, in
  that order; clear mask keeps retouch; history self-test all yes.
* **E1.4 sessions.** Schemas 1–7 read; supported saved as schema 2/3 atomically
  mode 0600; crop/logo/unsupported models read-only, no overwrite; Python→Native
  →Python fixtures pass; reopen replay pixelsEqual=true. 24 Swift tests.

* **E1.5 session integrity.** output_size/view/masks/passes/modelID сохраняются
  через app state; crop/logo/MI-GAN/SDXL хранятся как read-only и не пишутся;
  source change сохраняет рецепты; strict Python validation; async cancel;
  session generation; read-write entitlement + folder scope; close guard.
* **E1.5 tests.** 29 Swift tests; app session-state 999×777/view yes; Python
  fixtures 1–7; reopen replay pixelsEqual. Real session UI open/save/reopen
  заблокирован memory pressure warning и не принят.

## Проверено

* 16 Swift tests: preview, policy, CMYK reject, hidden RGB/alpha, mask
  top-left/eraser, context rect/dilation cancellation, outside/alpha composite,
  cancellation, EXIF 6 full decode, source identity.
* Debug app build; ad-hoc signature; model copy; запуск UI.
* E1.1 self-test 1/12/40 MP: outside=0, alpha=0; app phys after
  20.5 / 121.4 / 373.6 MiB; 40 Мп real-based PNG 8000×5000 — 38.50 s,
  phys 373.0 MiB, max RSS 690.5 MiB. 20 worker restarts в одном процессе:
  phys стабилен 2.55–2.64 MiB, 13.19 s, процессов не осталось.
* E1.1 real photos: coffee/astronaut/grass (NASA public domain / CC0), outside и
  alpha 0; astronaut ghost gone; grass texture blurred (same in Python).
* Timeout, crash (missing model), cancel self-tests прошли; после 20
  последовательных запусков app phys стабилен, worker-процессов нет.
* E0 strict re-verification: 8/8, worst tensor max 0.000664, final max 1 LSB.

## Ограничения E1.1/E1.2

* Реальные sample coffee/astronaut/grass/brick (NASA public domain / CC0)
  прогнаны с одинаковыми масками; outside/alpha точны. Остались 5 mask-пикселей
  round-cap, sub-LSB RGB и размытие grass; blind 100/200% приёмка не заявлена.
* UI: NSOpenPanel (debug start dir), photo switch, source-change, 40 Мп pass,
  cancel/close проверены; обычная ручная навигация панели и 20 ручных
  UI-проходов не проверены. 20 полных проходов — программные.
* 12/40 Мп synthetic + 40 Мп real-based file; полный 40 Мп UI-проход до
  результата выполнен (16.56 s), 40 Мп файл — upscaled real coffee, не native
  detail. Реальные sample — 512×512/600×400.
* 20 полных программных app-проходов есть; 20–50 ручных мышиных UI-проходов
  нет. Memory pressure injection только model-level, не реальный OS event.
  Нет 8/16 GiB, Intel, macOS 14; только Apple M3 Max 36 GiB, macOS 27.2.
* Native vs Python на одинаковых масках выполнен для coffee/astronaut/grass/
  brick и 2 Мп big-context; blind 100/200% независимая оценка не выполнена.
* Нет crop/logo/export/session/MI-GAN/SDXL/FP16/quantization.
* Sessions save UI не пройден вручную; core/CLI/Python fixtures проверены.
  Реальный UI open/save/reopen сессии остановлен memory pressure; нужен чистый
  normal-pressure прогон. Interrupted save проверен как no-overwrite, не kill.
* Replay+switch/cancel одновременно и несколько больших фото с eviction не
  прогнаны полностью; cache 384 MiB, 40 Мп результат 160 MB.
* Worker — self-exec Process, не XPC service; sandbox наследуется, crash-домен
  отдельный, но launchd/XPC lifecycle не реализован.
* Модель 196 MiB в app bundle; лицензия/распространение требуют подтверждения.

## Следующий шаг

Реальные фото и ручной UI-сценарий → полный 40 MP файл → 20–50 проходов и
memory pressure injection → Native/Python blind-сравнение → оптимизация
40 MP composite → затем crop/logo/export/sessions по ROADMAP.
