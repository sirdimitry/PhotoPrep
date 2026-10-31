# PhotoPrep Native — первая пригодная Native-версия

**Дата:** 31.10.2026  
**Ветка:** `v1/native-usable`  
**Коммит функций:** `38a80d5` (crop/logo/export); отчёт/STATUS — этот коммит.  
**Сборка:** `work/v1-build/Build/Products/Debug/PhotoPrep Native.app` (ad-hoc signed).  
Python, окружение, веса и пользовательские данные не менялись. Публичного релиза нет.

## Что уже работает

* LaMa FP32 в отдельном self-exec worker; Apple Silicon, локально, без сети.
* Straight RGBA8, outside-mask и alpha, EXIF orientation, hidden RGB.
* brush/eraser/undo stroke, один и несколько последовательных проходов, pass count, undo pass.
* Source identity + reads: изменение файла скрывает result и требует rebase/reset, recipes сохраняются.
* LRU-кэш 384 MiB, replay после вытеснения, dirty state и Save/Discard/Cancel для Open/New/Close/Cmd+Q.
* Сессии `.photoprep.json`: схемы 1–7 read; поддерживаемое пишется минимально (2/3/5/6), атомарно 0600; crop/logo поддерживаются; MI-GAN/SDXL read-only.
* **Кадрирование**: фиксированная рамка output aspect, перетаскивание/масштабирование изображения, точные выходные размеры, undo crop, состояние на фото.
* **Логотип**: локальный PNG с alpha, путь/размер/прозрачность/x/y/enabled/mode, применение к одному/всем фото; template trim alpha; render по геометрии Python.
* **Экспорт PNG/JPEG**: последовательная очередь, cancel, replay ретуши, crop, resize, logo, новые файлы без перезаписи/ symlink, белый фон для JPEG, без метаданных.

## Сборка и запуск

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  swift test --disable-sandbox --package-path apps/native \
  --scratch-path /tmp/v1-swift

DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  xcodebuild -project apps/native/PhotoPrepNative.xcodeproj -scheme PhotoPrepNative \
  -configuration Debug -destination 'platform=macOS,arch=arm64' \
  -derivedDataPath work/v1-build build CODE_SIGNING_ALLOWED=NO
```

Модель копируется build-phase в `Contents/Resources/Models/LaMa-fp32.mlmodelc`. Приложение запускается из `work/v1-build/...`; при первом Open/Save пользователь выбирает файлы/папки; sandbox read-write только для выбранного.

## Фактические проверки

* **35 Swift tests**: 13 session/output tests + 19 history/scale/decoder/cancellation + output editing.
* **V1 export self-test, 2 фото**: PNG 1136×710 для coffee/astronaut, logo overlay, crop, original SHA unchanged:

```json
{"exported":2,"expected":2,"error":"","originalsUnchanged":true,
 "dimensions":[{"width":1136,"height":710},{"width":1136,"height":710}]}
```

* Crop test: exact output size, alpha preserved.
* Logo test: PNG alpha overlay changes pixels, size preserved; template alpha trim implemented.
* Export test: PNG/JPEG encode, exclusive create, collision no overwrite, symlink-safe.
* Session state: output 999×777/view preserved; Python fixtures 1–7; v1/v2/v3 roundtrip Python; MI-GAN/SDXL read-only.
* Session files atomic mode 0600; failed save leaves old bytes.
* Source change: cache cleared, recipes kept (`recipesKept=true`).

## Реальный UI: что проверено

* file picker показывает конкретные `.photoprep.json`;
* два прохода и undo pass (E1.4);
* pass count/dirty controls;
* export UI добавлен, но полный ручной путь import→retouch→crop→logo→export **не пройден**;
* crop canvas/logo controls скомпилированы, но не подтверждены ручным сценарием;
* session open/save/reopen **не завершён**: системный memory pressure warning остановил загрузку, приложение штатно показало сообщение и не форсировало загрузку.

## Memory pressure

Наблюдалось системное предупреждение (интерфейс: «Загрузка остановлена: системе нужна память…»), после которого приложение приостановило preview/retouch. Это не OOM и не отключение защиты. Добавлена запись события/состояния (pressure-events.json) и восстановление preview после normal; фактический OS event в логе текущего прогона не зафиксирован, поэтому причина warning (внешняя нагрузка vs. app allocation) **не доказана**. Полный UI-прогон сессии при normal pressure остаётся нужным.

## Незакрытые пункты

* Полный ручной UI: import → retouch → crop → logo → export, несколько фото, PNG-alpha, JPEG, collisions.
* Session open → save as → close → reopen на подписанном sandbox-приложении; memory pressure и folder access.
* Dirty/Close/Cmd+Q Save/Discard/Cancel вручную.
* Rapid open A→B и switch during replay UI.
* Внешняя папка фото и отказ доступа.
* Interrupted save kill; multi-large-photo eviction.
* 5 mask-пикселей/sub-LSB RGB — зарегистрированное ограничение; визуальный паритет не заявлен.
* MI-GAN/SDXL/FP16/XPC/8–16 GiB/Intel/macOS14 не входят.

## Ограничения первой версии

LaMa only, Apple Silicon, local. MI-GAN/SDXL/FP16/XPC/crop/logo/export UI features included but session UI acceptance not complete. Model 196 MiB in bundle.
