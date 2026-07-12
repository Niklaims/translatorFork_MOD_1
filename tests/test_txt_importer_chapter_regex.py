from gemini_translator.utils.txt_importer import (
    BASIC_CJK_CHAPTER_REGEX,
    TxtChapterAnalyzer,
)


def test_basic_cjk_regex_matches_markdown_and_plain_chapter_titles():
    text = "\n".join(
        [
            "# 第1章 这就是美利坚，这就是纽约",
            "第一段正文",
            "第181章 移动手术室",
            "第一百八十一次手术开始了",
        ]
    )

    boundaries = TxtChapterAnalyzer(text).scan_chapter_boundaries(
        custom_regex=BASIC_CJK_CHAPTER_REGEX
    )

    assert [item["title"] for item in boundaries] == [
        "# 第1章 这就是美利坚，这就是纽约",
        "第181章 移动手术室",
    ]


def test_auto_analysis_offers_one_regex_for_mixed_cjk_headings():
    text = "\n".join(
        [
            "# 第1章 一",
            "正文内容 " * 100,
            "第2章 二",
            "正文内容 " * 100,
            "#第三章 三",
            "正文内容 " * 100,
        ]
    )

    results = TxtChapterAnalyzer(text).analyze_potential_markers()
    patterns = [marker[1] for marker, _count in results]

    assert BASIC_CJK_CHAPTER_REGEX in patterns
