# PhotoPrep Native — текущий статус

29.10.2026, development branch `native/swiftui-foundation`, base main `8f7c597`.

## Реально работает

* Проведён аудит Python-контрактов, включая маску, проходы, историю, схемы 1–7,
  crop/logo/export и безопасную запись: [BEHAVIOR.md](BEHAVIOR.md).
* Воспроизводимый developer benchmark на 8 синтетических сценах, реальные локальные
  Python LaMa/MI-GAN, по два прохода; оригиналы, alpha и внешние пиксели сохранены.
  На линиях/фактуре текущий MI-GAN хуже LaMa: [REFERENCE-RESULTS.md](REFERENCE-RESULTS.md).
* Настоящий Xcode-проект: окно, меню Open/New, отдельное имя/ID, RU/EN, две темы.
* Импорт отдельных однокадровых JPEG/PNG/TIFF/BMP/WebP, дедупликация, выбор фото,
  ImageIO preview ≤2048 px с EXIF orientation. Файлы читаются, а не переписываются.
* Одна очередь decode, отмена с отбрасыванием позднего результата, cap 40 MP,
  проверка размеров/переполнения, проверка общего resident+estimated allocation
  относительно app budget и системного резерва. Unknown memory → отказ.
* События memory pressure очищают preview и отменяют задачу. Закрытие окна
  освобождает preview; следующая загрузка требует нормального memory pressure.
* Sandbox: user-selected files read-only, без сетевого доступа. Отдельные defaults.
  Тяжёлые модели в приложение не включены и не загружаются.

## Проверено

* Xcode 27.1 (27A9275), Swift 6.4, macOS 27.2 arm64; deployment target 14.0.
  Запуск на самой macOS 14 и Intel пока не проверен.
* 8 Swift tests: allocation denial/overflow/pressure, EXIF rotation, bounded
  preview, source bytes unchanged, low-memory denial before decode, corrupt/network input.
* 58 Python tests passed: inference, retouch_passes, editing, sessions, exporting.
  Python-код не менялся; существующая среда использовалась только для запуска.
* Debug app собрана, ad-hoc signature/entitlements проверены. Реальный запуск,
  импорт синтетического фото, RU/EN и обе темы проверены через UI.
* Первый запуск выявил force unwrap недоступного UserDefaults suite; исправлено
  на стандартные defaults отдельного Native bundle, запуск повторно проверен.
* Команды воспроизведения: [README](README.md), [BEHAVIOR](BEHAVIOR.md),
  [reference report](REFERENCE-RESULTS.md). Native CI добавлен; удалённый запуск
  CI не подтверждён (ветка пока локальная).

## Ограничения и следующий этап

Это каркас B и начало C, не готовый редактор. Нет Core ML-моделей/worker,
кисти/маски, zoom/pan, ретуши, crop/logo/export, сессий или истории. Совместимость
1–7 описана, но Native reader/writer ещё не реализованы. Полный этап A по
межъязыковым fixtures будет дополнен вместе с reader/writer; Python tests не
подменяют Native round-trip. Нет обещания сохранения ещё не реализованных наборов.

Многостраничные/анимированные файлы сейчас отвергаются; папки/drag-and-drop и
миниатюры коллекции ещё не реализованы. WebP зависит от ImageIO установленной ОС.
Memory admission — оценка, не жёсткая квота; decoder пока в UI-процессе,
в отдельном actor. Проверка длительных серий, malicious-file fuzzing и изоляция
worker обязательны до подключения AI. Тесты policy не доказывают отсутствие OOM
на всех Mac; memory pressure проверена через policy tests, не стрессом реальной ОС.
GPU/physical-footprint/watchdog и crash recovery worker пока не реализованы.

Далее C/D: устойчивое состояние коллекции и история, точные координаты холста,
маска/ластик и совместимые сессии. Затем E: конвертация LaMa с manifest,
изолированный нативный worker и сравнение с reference на тех же входах. До
измерений FP16/Neural Engine/автоускорение не включаются. Восстановление скрытого
содержимого оценивается визуально; точное восстановление утраченного фона не обещается.

Нативного релиза, DMG, PR или публикации не создавалось. Установленный Python,
оригинальные веса, логотипы, настройки и исторические релизы не заменялись.
