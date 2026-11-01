# PhotoPrep Native — текущий статус

**01.11.2026, ветка `v1/layout-interaction`.** **Статус: кандидат для личной проверки.** Native v1, LaMa FP32, Apple Silicon, только локальная обработка; полный UI-маршрут ещё не подтверждён. Сборка: `work/PhotoPrep-Native-v1-candidate.app`. Публичного релиза нет. Python-приложение, окружение, веса и пользовательские данные не менялись.

## Сейчас работает

* Импорт JPEG/PNG/TIFF/BMP/WebP, EXIF orientation, straight RGBA8; оригиналы не перезаписываются.
* LaMa FP32 в отдельном self-exec worker; brush/eraser/undo, один и несколько проходов, before/after, cancel/timeout.
* Последовательные проходы, per-photo masks/recipes, undo pass, replay после вытеснения LRU (384 MiB), source identity.
* Dirty state и Save/Discard/Cancel для Open/New/Close/Cmd+Q.
* Сессии `.photoprep.json`: схемы 1–7 read, поддержанные 2/3/5/6 атомарно 0600; crop/logo/lama; MI-GAN/SDXL read-only.
* Кадрирование: fixed output frame, pan/zoom, exact output size, undo crop, per-photo state.
* Логотип: локальный PNG alpha, размер/прозрачность/позиция, один/все фото, logo/template.
* Экспорт PNG/JPEG: sequential replay → crop → resize → logo → новый файл; cancel, no-overwrite/symlink-safe, JPEG white flatten, без metadata.

## Проверки

36 Swift tests; app state 999×777/view; Python fixtures 1–7; 2-photo v1 export 1136×710, originals SHA unchanged; crop/logo/export unit tests; source change recipes kept; read-only save no overwrite.

## Ограничения

* Полный ручной UI import → retouch → crop → logo → export и session open/save/reopen **не закрыты**: системный memory pressure warning остановил UI-прогон; crop/logo controls не проверены вручную.
* Dirty/Close/Cmd+Q и rapid open/switch не проверены вручную.
* Внешняя папка фото/отказ доступа, interrupted save, multi-large-photo eviction не закрыты.
* 5 mask-пикселей/sub-LSB RGB — зарегистрированное ограничение, паритет не заявлен.
* Нет MI-GAN/SDXL/FP16/XPC, 8–16 GiB/Intel/macOS14.

## Отчёты

* [V1-USABLE.md](V1-USABLE.md) — текущая сборка/маршрут/ограничения.
* [E1.6-SESSION-UI.md](E1.6-SESSION-UI.md)
* [E1.5-SESSION-INTEGRITY.md](E1.5-SESSION-INTEGRITY.md)
* [E1.4-HISTORY-SESSIONS.md](E1.4-HISTORY-SESSIONS.md)
* [E1.3-QUALITY-HISTORY.md](E1.3-QUALITY-HISTORY.md)
* [E1.2-ACCEPTANCE.md](E1.2-ACCEPTANCE.md)
* [E1.1-QUALITY-STABILITY.md](E1.1-QUALITY-STABILITY.md)
* [E1-LAMA-WORKER.md](E1-LAMA-WORKER.md), [E0-LAMA-COREML.md](E0-LAMA-COREML.md), [REFERENCE-RESULTS.md](REFERENCE-RESULTS.md)
