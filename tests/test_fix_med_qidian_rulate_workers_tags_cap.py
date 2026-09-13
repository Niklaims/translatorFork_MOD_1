# -*- coding: utf-8 -*-
"""Регресс на находку qidian-tools/bugs/3-normalize-list-caps-tags-at-ei.

`_normalize_list` безусловно резала результат до 8 элементов. Для жанров
это безвредно (используется только `[:7]`), но для тегов Rulate — реальный
дефект: `build_catalog_prompt` просит модель вернуть до 15 тегов, а
`RulateFillWorker._fill_description` перебирает `prepared.tags[:15]`, но
получить больше 8 тегов не может, потому что список уже обрезан на этапе
`normalize_rulate_tags` -> `_normalize_list`.
"""

from qidian_rulate import workers


def test_normalize_rulate_tags_keeps_up_to_15_valid_tags(monkeypatch):
    allowed = [f"тег{i}" for i in range(1, 16)]  # 15 валидных тегов Rulate
    monkeypatch.setattr(workers, "load_rulate_tags", lambda: allowed)

    # Модель добросовестно вернула все 15 валидных тегов по смыслу описания.
    result = workers.normalize_rulate_tags(", ".join(allowed))

    assert result == allowed, (
        "normalize_rulate_tags не должен молча обрезать валидные теги модели "
        "до 8 — промпт и заполнение формы Rulate рассчитаны на до 15 тегов"
    )


def test_normalize_list_still_caps_genres_at_default_limit():
    # Жанры (`_normalize_list` без явного limit) по-прежнему ограничены
    # прежним значением по умолчанию — поведение для жанров не меняется.
    allowed = [f"жанр{i}" for i in range(1, 11)]
    result = workers._normalize_list(", ".join(allowed), allowed=allowed, fallback=[])
    assert len(result) == 8
