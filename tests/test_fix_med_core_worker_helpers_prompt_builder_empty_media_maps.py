"""
Регресс на core-b/bugs/5-replace-media-placeholders-emp:
_replace_media_with_placeholders(html_content='', return_maps=True) должен
возвращать (dict, dict), как и в непустой ветке, а не вложенный кортеж
(({}, {}), ""). Иначе единственный вызывающий код,
ResponseParser._restore_media_from_placeholders, падает с AttributeError
при попытке распаковки для пустой (или whitespace-only) главы.
"""

from gemini_translator.core.worker_helpers.prompt_builder import PromptBuilder
from gemini_translator.core.worker_helpers.response_parser import ResponseParser


def _parser(logs=None):
    return ResponseParser(
        worker=None,
        log_callback=(logs or []).append,
        prompt_builder=PromptBuilder(
            custom_prompt="",
            context_manager=None,
            use_system_instruction=False,
        ),
    )


def test_replace_media_with_placeholders_empty_content_return_maps_shape():
    builder = PromptBuilder(
        custom_prompt="",
        context_manager=None,
        use_system_instruction=False,
    )

    media_map, link_map = builder._replace_media_with_placeholders("", return_maps=True)

    assert media_map == {}
    assert link_map == {}


def test_restore_media_from_placeholders_with_empty_original_content_is_noop():
    translated = "<body><p>Переведённый текст.</p></body>"

    # Пустая original_content_for_map_building (например, глава из EPUB
    # оказалась пустой строкой) не должна ронять восстановление медиа —
    # оно должно вернуть переведённый текст без изменений.
    restored = _parser()._restore_media_from_placeholders(
        translated_content=translated,
        original_content_for_map_building="",
    )

    assert restored == translated
