from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dual_release_script_packages_onedir_outputs():
    script = (PROJECT_ROOT / "build_release_dual.bat").read_text(encoding="utf-8")

    assert 'call :finish_build "dist\\translatorFork-translator"' in script
    assert 'call :finish_build "dist\\translatorFork-full"' in script
    assert 'call :finish_build "dist\\translatorFork-translator.exe"' not in script
    assert 'call :finish_build "dist\\translatorFork-full.exe"' not in script

    assert "translatorFork-translator-v%RELEASE_VERSION%-windows.zip" in script
    assert "translatorFork-full-v%RELEASE_VERSION%-windows.zip" in script
    assert "translatorFork_MOD-source-v%RELEASE_VERSION%.zip" in script
    assert "SHA256SUMS.txt" in script
    assert "git archive --format=zip" in script
