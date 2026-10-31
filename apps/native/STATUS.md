# PhotoPrep Native — текущий статус

31.10.2026, integration branch `e1/lama-native-worker`, base E0 `101f6bf`.
Исторические отчёты не переписаны: [E0-LAMA-COREML.md](E0-LAMA-COREML.md),
[E1-LAMA-WORKER.md](E1-LAMA-WORKER.md), [REFERENCE-RESULTS.md](REFERENCE-RESULTS.md).

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

## Проверено

* 14 Swift tests: preview, policy, hidden RGB/alpha, mask top-left/eraser,
  context rect, outside/alpha composite, EXIF 6 full decode, source identity.
* Debug app build; ad-hoc signature; model copy; запуск UI.
* E1 self-test 1/12/40 MP на синтетике: outside=0, alpha=0; app phys after
  20.6 / 121.5 / 373.7 MiB; worker max RSS ~689 MiB; full wall 3.35 / 12.49 /
  37.56 s (включая генерацию тестового буфера).
* Timeout, crash (missing model), cancel self-tests прошли; после 20
  последовательных запусков app phys стабилен, worker-процессов нет.
* E0 strict re-verification: 8/8, worst tensor max 0.000664, final max 1 LSB.

## Ограничения

* **Нет реальных разрешённых фотографий**: приёмка на реальной фактуре/линиях/
  логотипе у края не закрыта. Пользовательские фото не использовались.
* **Интерактивный UI-прогон не автоматизирован**: приложение запускается,
  панель отображается; NSOpenPanel/кисть/process через UI вручную ещё проверить.
* 12/40 MP проверены на синтетическом буфере, не на реальном 40 MP файле;
  37.56 s включает генерацию тестового буфера и не является оценкой UI-отклика.
* Нет 20–50 проходов в одном процессе, memory pressure injection, 8/16 GiB,
  Intel, macOS 14; только Apple M3 Max 36 GiB, macOS 27.2.
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
