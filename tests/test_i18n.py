from photoprep.i18n import STRINGS, tr


def test_language_key_coverage():
    assert set(STRINGS["en"]) == set(STRINGS["ru"])


def test_language_switch_and_fallback():
    assert tr("ru", "open_photos") == "Открыть фото"
    assert tr("en", "open_photos") == "Open photos"
    assert tr("xx", "open_photos") == "Open photos"


def test_dynamic_labels():
    assert tr("ru", "status_loaded", count=3) == "Загружено фотографий: 3"
