# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class QidianBookMetadata:
    source_url: str = ""
    title_original: str = ""
    author_name: str = ""
    description: str = ""
    cover_url: str = ""
    cover_image_data: bytes = b""


@dataclass(slots=True)
class PreparedRulateMetadata:
    english_title: str = ""
    translated_title: str = ""
    translated_description: str = ""
    translator_team_mode: str = ""
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    cover_prompt: str = ""


@dataclass(slots=True)
class RulateBookDraft:
    qidian: QidianBookMetadata
    prepared: PreparedRulateMetadata
