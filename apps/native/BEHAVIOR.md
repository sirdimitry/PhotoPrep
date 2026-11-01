# Native: проверенные контракты

Аудит 29.10.2026, Python v0.2.0, база `8f7c597`. Native пока не выполняет ретушь.
Приоритет пользователя: удаление логотипов и восстановление фона, устойчивость,
контролируемая память и скорость. Компиляция не является приёмкой качества AI.

## Что переносим

| Область | Источник в apps/python/photoprep | Проверенное поведение / риск |
|---|---|---|
| Импорт | models.py, ui/canvas.py | JPG/JPEG/PNG/WebP/TIFF/BMP; папка без рекурсии, casefold-порядок; абсолютные разрешённые пути, удаление дублей. EXIF 5–8 меняют местами размеры. Python иногда декодирует неизвестный размер целиком; Native не должен делать это до проверки бюджета. |
| Коллекция | workspace.py | Добавление/удаление, правки, общий логотип и размеры создают checkpoint. 100 undo-снимков, новая правка очищает redo. История содержит планы, не пиксели. Dirty сравнивает также выделение и view с сохранённым снимком. |
| Маска | editing.py, ui/editor.py | Координаты от левого верхнего угла ориентированного фото, x вправо/y вниз; ширина = диаметр / min(W,H). Круглые caps/joins, одиночная точка; порядок штрихов важен. Grayscale8, antialiasing; ластик рисует чёрным SourceOver. Overlay ≤1536 по большей стороне не является inference-маской. |
| Геометрия | editing.py, ui/editor.py | fit_crop вписывает отношение сторон, существующий кадр сохраняет центр и площадь до ограничения границами. Рамка неподвижна, изображение двигается под ней. Zoom — физические экранные пиксели / пиксель источника; координаты сессии не зависят от Retina. |
| Ретушь | inference.py | Контекст охватывает все ненулевые пиксели маски: span=max(dx+1,dy+1), side=max(256,span+max(64,span//2)), центр bounding box; ограничение границами. Python round — ties-to-even. Контекст растягивается в квадрат 512 (SDXL 1024), без letterbox. |
| Вход модели | inference.py | RGB NCHW float32 [0,1], mask N1HW float32 0/1; после SmoothTransformation ненулевое покрытие становится 1, затем дилатация квадратом 5×5, только для inference. MI-GAN получает uint8 RGB [0,255] и обратную mask (1-mask)*255. |
| Выход модели | inference.py | Только (1,3,R,R), все значения finite. Clip [0,255], truncation до uint8, растяжение обратно; затем RGB blend исходным покрытием /255, ties-to-even rounding. Alpha исходника остаётся побитово неизменной. Вне маски RGBA идентичны исходному каноническому RGBA8888. |
| Проходы | ui/main_window.py, inference.py | Новый проход использует предыдущий результат; при вытеснении кэша replay исходника по порядку. На проход сохраняется модель. Clear mask не удаляет проходы; «До/После» не меняет рецепт. Отмена удаления возвращает последнюю маску перед текущими штрихами, сохраняет crop/logo. |
| Задачи | ui/ai_controller.py | Один дочерний процесс; cancel убивает его. Commit только при совпадении source signature + recipe + pending mask + model с текущим состоянием. При ошибке маска не потребляется. Native сохраняет принцип изоляции тяжёлой обработки. |
| Кэши | ui/canvas.py, ui/main_window.py | Python: decode cache 128 MiB, retouch cache 192 MiB, до 2 decoder threads. Это не общий лимит памяти: активные изображения/NumPy/модель/драйверы находятся вне этих кэшей. |
| Логотип | branding.py | PNG до 32 MiB/32 MP; sRGB, отдельные logo/template. Template обрезает прозрачные поля. Поля 3% у logo, без полей у template; width относительно выходной рамки, x/y относительно свободного места, opacity. Личные PNG не входят в приложение. |
| Экспорт | exporting.py | Replay → floating crop → точный размер → logo → новый буфер без EXIF/GPS/XMP/комментариев/ICC. Перед композицией tagged source переводится в sRGB; JPEG на белом фоне, quality 1–100. Это отдельный контракт от точности пикселей ретуши. |
| Запись | exporting.py | Последовательные файлы, временный файл в выходном каталоге, fsync и renamex_np(RENAME_EXCL). Не заменяет существующие файлы и symlinks. Сигнатура source/logo проверяется перед и после обработки. Частичная ошибка сохраняет готовые файлы. |
| Настройки/логи | settings.py, diagnostics.py | Отдельная Native identity; нет автопереноса настроек. Локальные приватные логи с ограничением; нет фото, токенов и путей в опубликованных артефактах. |

## Сессии 1–7: уточнения перед Codable

Источник — `session.py`; тесты `test_sessions`, `test_editing`, `test_retouch_passes`,
`test_catalog`, `test_branding_templates`, `test_sdxl`. Чтение ≤5 MiB (limit+1),
≤10 000 фото, ≤200 000 точек на документ, ≤100 проходов на фото. Формат PhotoPrep,
целочисленная версия 1–7 (bool недопустим). Version 1 игнорирует edits/output_size.
Missing/null edits → пустой рецепт; view с неверными числами → default, zoom .05–16,
center 0–1; fit false только при JSON false. Output 128–16000 по каждой оси;
40 MP проверяются экспортом, а не loader.

Stroke: непустой points list, каждая точка длины 2, finite и abs≤1e6 (выход за
0–1 допустим); finite width (0,512], erase именно bool. Crop nullable, finite,
x/y≥0, w/h>0, правый/нижний край≤1.000001. Loader повторно fit_crop под output.
Pass: непустая группа штрихов. Отсутствующий/пустой pass_models → LaMa на каждый
проход, иначе длины совпадают. Logo nullable; path непустой, без NUL, ≤4096;
width .01–.94, opacity/x/y 0–1, enabled bool, mode logo/template.

Python допускает некоторые числовые строки/bool через float(), но строго
проверяет тип output_size/version. Совместимость нужно проверять fixtures, а не
заявлять по похожести Swift-структур. Missing photo пропускается (его edits Python
не валидирует), дубли пропускаются, selection fallback — первое доступное фото.
**Неизвестную модель Python отвергает**: это отличие от желаемого Native сохранения
неподдерживаемого рецепта. Native может читать известный SDXL без выполнения;
для действительно неизвестного ID нужен явный режим без перезаписи, пока нет
решения о совместимости. Нельзя утверждать, что Python прочитает такой ID.

Writer: относительные пути, атомарная запись 0600; минимальная схема начинается
с 2, 3 — passes, 4 — non-LaMa, 5 — logo, 6 — template, 7 — SDXL.
История UI/закладки/кэши не добавляются в переносимый JSON. Формат 8 не вводится.

## Решения и открытые ограничения

* macOS 14.0, отдельное приложение `PhotoPrep Native.app`, bundle ID
  `com.sirdimitry.PhotoPrep.Native`. SwiftUI для окна/меню; AppKit допустим для холста.
* MainActor — только UI. Тяжёлые задачи последовательно, отдельный нативный worker
  до интеграции Core ML. Один actor сам по себе не защищает UI-процесс от crash/OOM.
* Канонический inference-буфер — ориентированные straight RGBA8; не round-trip через
  premultiplied CGContext. Проверка скрытого RGB при alpha 0 и alpha 1–254 обязательна.
* Не улучшать качество молча иной маской или контекстом. Сначала Python-compatible
  reference preset, затем сравниваемые варианты контекста/дилатации с явным manifest.
* LaMa → MI-GAN → SDXL. ONNX не считается Core ML-моделью. Нужны проверенный источник
  PyTorch, лицензия, graph review, manifest конвертации и реальные измерения.
* Исходный фон под непрозрачным логотипом утрачен: восстановление — оценка модели;
  нельзя обещать точную реконструкцию скрытого лица, текста или мелких деталей.

## Проверка этапа A

29.10.2026: 58 Python checks passed (inference, passes, editing, sessions, exporting),
Python 3.12.4 / PySide6 6.12.0 / NumPy 2.5.4 / ONNX Runtime 1.31.1 / Pillow 13.0.0.
Команда из apps/python: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PWD" <existing-python> -m pytest -q -p no:cacheprovider
tests/test_inference.py tests/test_retouch_passes.py tests/test_editing.py
tests/test_sessions.py tests/test_exporting.py`.
Это проверки действующего Python-контракта; не оценка качества Native.

Среда: arm64, macOS 27.2, Xcode 27.1 (27A9275), Swift 6.4. Xcode выбран для команд
через DEVELOPER_DIR, глобальный xcode-select не менялся. Свободно около 18 GiB;
новые веса не скачивались, существующая Python-среда не менялась.

Первичные источники для следующего этапа (проверены 29.10.2026):
[Core ML conversion](https://github.com/apple/coremltools/blob/main/docs-guides/source/load-and-convert-model.md),
[input/output dtype](https://apple.github.io/coremltools/docs-guides/source/model-input-and-output-types.html),
[MLModelConfiguration](https://developer.apple.com/documentation/coreml/mlmodelconfiguration).
Shape, dtype, precision, compute units задавать явно; ускорение не предполагать.
