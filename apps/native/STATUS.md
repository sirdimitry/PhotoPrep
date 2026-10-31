# PhotoPrep Native — текущий статус

31.10.2026, branch `e1.1/quality-stability`, base E1 `765e57a` (E0 `101f6bf`).
Исторические отчёты не переписаны: [E0-LAMA-COREML.md](E0-LAMA-COREML.md),
[E1-LAMA-WORKER.md](E1-LAMA-WORKER.md), [E1.1-QUALITY-STABILITY.md](E1.1-QUALITY-STABILITY.md),
[REFERENCE-RESULTS.md](REFERENCE-RESULTS.md).

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

## Проверено

* 16 Swift tests: preview, policy, CMYK reject, hidden RGB/alpha, mask
  top-left/eraser, context rect, outside/alpha composite, cancellation,
  EXIF 6 full decode, source identity.
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

## Ограничения

* Реальные разрешённые sample (NASA astronaut public domain, coffee CC0) с
  синтетическим знаком прогнаны; outside/alpha точны. На astronaut Native
  оставил заметный hallucinated-патч в области логотипа (Native vs Python max
  35, mean 0.086), поэтому качество real-photo ещё не принято. Нет реальных
  12/40 MP фото и набора кирпич/ткань/волосы/листва.
* UI: debug-import/brush/eraser/undo/process/before-after/cancel проверены;
  NSOpenPanel, смена фото, source substitution и 20 UI-проходов не проверены.
* 12/40 Мп synthetic + 40 Мп real-based file; 40 Мп UI display/close проверены,
  полный 40 Мп UI-проход до результата — нет.
  Реальные sample были 512×512/600×400.
* 20 worker restarts в одном процессе есть; 20–50 UI-обработок в одном app —
  нет. Memory pressure injection только model-level, не реальный OS event.
  Нет 8/16 GiB, Intel, macOS 14; только Apple M3 Max 36 GiB, macOS 27.2.
* Нет Native vs Python blind-сравнения на одинаковых реальных масках; E0
  проверяет модель, но Native resize/composite отличается от Qt.
* Нет crop/logo/export/session/MI-GAN/SDXL/FP16/quantization.
* Worker — self-exec Process, не XPC service; sandbox наследуется, crash-домен
  отдельный, но launchd/XPC lifecycle не реализован.
* Модель 196 MiB в app bundle; лицензия/распространение требуют подтверждения.

## Следующий шаг

Реальные фото и ручной UI-сценарий → полный 40 MP файл → 20–50 проходов и
memory pressure injection → Native/Python blind-сравнение → оптимизация
40 MP composite → затем crop/logo/export/sessions по ROADMAP.
