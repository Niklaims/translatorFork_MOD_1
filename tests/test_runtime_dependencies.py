from pathlib import Path

import build_master


ROOT = Path(__file__).resolve().parents[1]


def test_python_and_numeric_dependency_contract_is_consistent():
    assert build_master.FORCED_VERSIONS["numpy"] == ">=2.0,<3"
    assert build_master.FORCED_VERSIONS["pandas"] == ">=3.0,<4"
    assert build_master.FORCED_VERSIONS["razdel"] == ">=0.5,<1"
    assert {"numpy", "pandas", "razdel"} <= set(build_master.ESSENTIAL_PACKAGES)

    for path in ("requirements.txt", "requirements-translator-only.txt"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "numpy>=2.0,<3" in text
        assert "pandas>=3.0,<4" in text
        assert "razdel>=0.5,<1" in text

    assert 'target-version = "py311"' in (ROOT / "pyproject.toml").read_text()
    assert 'python-version: "3.11"' in (ROOT / ".github/workflows/tests.yml").read_text()
    assert 'python-version: "3.11"' in (ROOT / ".github/workflows/release.yml").read_text()


def test_qa_prompt_resources_are_collected_by_both_builds():
    """A prompt file left out of the bundle fails every QA request closed."""
    prompts = ROOT / "gemini_translator/config/translation_qa_prompts.json"
    assert prompts.is_file()

    for spec_name in ("translatorFork_MOD.spec", "translatorFork-translator-only.spec"):
        spec = (ROOT / spec_name).read_text(encoding="utf-8")
        assert "gemini_translator/config/translation_qa_prompts.json" in spec


def test_every_shipped_prompt_declares_its_data_boundary():
    """A prompt without the untrusted-data markers would take book text as orders."""
    import json

    payload = json.loads(
        (ROOT / "gemini_translator/config/translation_qa_prompts.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload
    for name, template in payload.items():
        assert template.count("__QA_DATA_TAG__") == 2, name
        assert template.count("__QA_DATA_PAYLOAD__") == 1, name


def test_requirements_exclude_pyasn1_versions_with_known_advisories():
    """pyasn1 0.6.3 has three advisories fixed in 0.6.4 (PYSEC-2026-3455..3457).

    It arrives through google-auth, so nothing pins it unless the manifest does,
    and an existing virtualenv keeps the vulnerable version forever.
    """
    from packaging.requirements import Requirement

    lines = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    pinned = [Requirement(line) for line in lines if Requirement(line).name.lower() == "pyasn1"]
    generated = Requirement("pyasn1" + build_master.FORCED_VERSIONS.get("pyasn1", ""))

    assert len(pinned) == 1
    for requirement in (pinned[0], generated):
        assert not requirement.specifier.contains("0.6.3")
        assert requirement.specifier.contains("0.6.4")
