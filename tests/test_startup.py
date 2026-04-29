"""Tests para app.startup.print_startup_banner."""

from pathlib import Path

from app.startup import print_startup_banner


def test_print_startup_banner_uses_assets_logo(tmp_path, monkeypatch):
    """
    Copia la estructura esperada: parent/parent/assets/geminis-labs-logo.txt
    respecto a app/startup.py.
    """
    root = tmp_path
    app_dir = root / "app"
    app_dir.mkdir()
    (app_dir / "startup.py").write_text("#", encoding="utf-8")

    assets = root / "assets"
    assets.mkdir()
    (assets / "geminis-labs-logo.txt").write_text("LOGO_LINE\n", encoding="utf-8")

    import app.startup as startup_mod

    monkeypatch.setattr(startup_mod, "__file__", str(app_dir / "startup.py"))

    print_startup_banner()


def test_print_startup_banner_missing_file_logs_without_crashing(
    monkeypatch, caplog
):
    import app.startup as startup_mod

    monkeypatch.setattr(startup_mod, "__file__", "/no/such/path/startup.py")

    with caplog.at_level("WARNING"):
        print_startup_banner()

    assert any("Logo file not found" in r.message for r in caplog.records)
