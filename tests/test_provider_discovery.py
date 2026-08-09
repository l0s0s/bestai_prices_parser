import pytest

from app.services.provider_discovery import crawl_enabled_sources


def test_crawl_enabled_sources_raises_when_config_missing(monkeypatch, tmp_path):
    """Reproduces a real gap against TZ §5.8, which names "не удалось
    прочитать config" as one of exactly four conditions that must terminate
    the run with an error, not degrade silently. The old behavior (log +
    return []) let update-all report "Pipeline completed successfully" with
    zero providers processed whenever SOURCES_FILE was missing."""
    from app.settings import settings

    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(settings, "sources_file", str(missing_path))

    with pytest.raises(FileNotFoundError):
        crawl_enabled_sources()
