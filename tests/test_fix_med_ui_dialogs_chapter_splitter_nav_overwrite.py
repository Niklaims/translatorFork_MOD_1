# -*- coding: utf-8 -*-
"""
Регрессионный тест для находки ui-dialogs-other/bugs/4-epub-split-nav-overwrite.

split_epub_file (chapter_splitter.py) разбивает главы книги по циклу spine
(строки ~460-508), а затем отдельным циклом по манифесту (~532-607)
обновляет ссылки в документе навигации (nav.xhtml) и в NCX, безусловно
перечитывая их исходное содержимое из архива (zin.read(internal_path)).

Если nav.xhtml сам присутствует в spine и достаточно велик, чтобы попасть
под split_threshold, первый цикл трактует его как обычную главу и кладёт в
updated_files только часть 1 — а второй цикл затем перезаписывает эту же
запись ПОЛНЫМ исходным содержимым nav (без учёта, что документ уже был
разбит). Если у nav-документа к тому же стоит properties="nav", это
свойство наследуют и сгенерированные part-файлы (nav_part2.xhtml и т.д.);
они тоже подпадают под условие второго цикла и падают с KeyError, потому
что такого файла в исходном архиве нет.

Документ навигации — это оглавление книги, а не глава для перевода/сплита,
поэтому корневое исправление — исключить его из первого (spine) цикла
разбиения: он не является "главой" и должен обновляться только вторым,
специализированным циклом.
"""
import zipfile

CONTAINER_XML = (
    '<?xml version="1.0"?>'
    '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="{path}" '
    'media-type="application/oebps-package+xml"/></rootfiles>'
    "</container>"
)


def _make_epub(tmp_path, name, entries):
    epub_path = tmp_path / name
    with zipfile.ZipFile(epub_path, "w") as zf:
        for arcname, content in entries.items():
            zf.writestr(arcname, content)
    return epub_path


def _nav_body(link_count):
    items = "".join(
        f'<li><a href="chapter1.xhtml">Глава про {index}</a></li>'
        for index in range(link_count)
    )
    return f'<nav epub:type="toc"><ol>{items}</ol></nav>'


def _build_book(tmp_path, nav_properties):
    """Собирает EPUB, где nav.xhtml включён в spine и достаточно велик,
    чтобы сам подвергнуться разбиению, и содержит ссылку на chapter1.xhtml,
    которая тоже будет разбита на части."""
    long_body = "<p>" + ("слово " * 400) + "</p>"
    nav_attr = f' properties="{nav_properties}"' if nav_properties else ""
    opf = (
        '<package xmlns="http://www.idpf.org/2007/opf">'
        "<manifest>"
        f'<item id="navitem" href="nav.xhtml" media-type="application/xhtml+xml"{nav_attr}/>'
        '<item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>'
        "</manifest>"
        '<spine><itemref idref="navitem"/><itemref idref="c1"/></spine>'
        "</package>"
    )
    return _make_epub(
        tmp_path,
        "book.epub",
        {
            "META-INF/container.xml": CONTAINER_XML.format(path="OEBPS/content.opf"),
            "OEBPS/content.opf": opf,
            "OEBPS/nav.xhtml": f"<html><body>{_nav_body(30)}</body></html>",
            "OEBPS/chapter1.xhtml": f"<html><body><h1>Глава</h1>{long_body}</body></html>",
        },
    )


def test_nav_with_nav_property_is_not_split_and_does_not_crash(tmp_path):
    """properties="nav" на самом nav.xhtml — самый тяжёлый вариант дефекта:
    сгенерированные part-файлы nav унаследовали бы то же properties="nav" и
    упали бы с KeyError во втором цикле (он читает их из ОРИГИНАЛЬНОГО zin,
    где таких файлов нет)."""
    from gemini_translator.ui.dialogs import chapter_splitter

    epub_path = _build_book(tmp_path, nav_properties="nav")
    output_path = tmp_path / "out.epub"
    settings = chapter_splitter.SplitSettings(split_threshold=50, target_size=100, min_part_size=20)

    stats = chapter_splitter.split_epub_file(str(epub_path), str(output_path), settings)

    # Разбита должна быть только настоящая глава (chapter1), а не nav.
    assert stats.split_chapters == 1

    with zipfile.ZipFile(output_path) as zout:
        names = set(zout.namelist())
        # Никаких "осиротевших" частей навигации быть не должно.
        assert not any("nav_part" in name for name in names)
        assert "OEBPS/nav.xhtml" in names

        opf_text = zout.read("OEBPS/content.opf").decode("utf-8")
        # В манифесте не должно появиться part-элементов для nav.
        assert "navitem_part" not in opf_text

        nav_text = zout.read("OEBPS/nav.xhtml").decode("utf-8")
        # Ссылка на разбитую главу должна вести на настоящую часть 1.
        assert "chapter1.xhtml" in nav_text


def test_nav_named_by_basename_is_not_split_into_orphaned_parts(tmp_path):
    """Даже без properties="nav" (документ распознан только по имени файла
    nav.xhtml) первый (spine) цикл не должен разбивать его как обычную
    главу — иначе часть 1, записанная туда, будет затем перезаписана
    полным исходным содержимым вторым циклом, а сгенерированные
    nav_part2.xhtml/nav_part3.xhtml останутся в архиве как дубликаты,
    не обновлённые ссылками на реальные части других глав."""
    from gemini_translator.ui.dialogs import chapter_splitter

    epub_path = _build_book(tmp_path, nav_properties=None)
    output_path = tmp_path / "out.epub"
    settings = chapter_splitter.SplitSettings(split_threshold=50, target_size=100, min_part_size=20)

    stats = chapter_splitter.split_epub_file(str(epub_path), str(output_path), settings)

    assert stats.split_chapters == 1

    with zipfile.ZipFile(output_path) as zout:
        names = set(zout.namelist())
        assert not any("nav_part" in name for name in names)

        nav_text = zout.read("OEBPS/nav.xhtml").decode("utf-8")
        # Ссылка на разбитую главу должна быть дополнена частью 2.
        assert "chapter1_part2.xhtml" in nav_text
