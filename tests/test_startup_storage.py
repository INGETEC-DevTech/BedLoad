"""Démarrage : la base et le journal sont écrits à côté de l'exe (appli portable). Si ce
dossier n'est pas modifiable, un message clair est affiché et l'appli se ferme proprement."""
import os
import stat
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
# QtWebEngine (importé par app.py via la fenêtre principale) doit précéder la QApplication.
from PyQt6 import QtWebEngineWidgets  # noqa: F401
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.utils import find_storage_problem


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def read_only(request):
    """Rend des fichiers lecture seule, et les rétablit en fin de test (nettoyage de tmp_path)."""
    paths = []

    def make(path):
        os.chmod(path, stat.S_IREAD)
        paths.append(path)
    yield make
    for path in paths:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_writable_folder_has_no_problem(tmp_path):
    assert find_storage_problem(tmp_path) is None


def test_folder_that_cannot_be_created_is_reported(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("un fichier, pas un dossier")
    base_dir = blocker / "HydroTopo"

    message = find_storage_problem(base_dir)

    assert message is not None
    assert str(base_dir) in message and "Déplacez HydroTopo" in message


def test_access_denied_on_write_is_reported(tmp_path, monkeypatch):
    """Cas Program Files / partage en lecture seule : l'écriture d'un fichier est refusée."""
    def denied(*args, **kwargs):
        raise PermissionError(13, "Accès refusé")
    monkeypatch.setattr(tempfile, "TemporaryFile", denied)

    message = find_storage_problem(tmp_path)

    assert message is not None and "Accès refusé" in message
    assert "Program Files" in message


@pytest.mark.parametrize("relative", [("data", "hydrotopo.db"), ("hydrotopo.log",)])
def test_existing_read_only_database_or_log_is_reported(tmp_path, read_only, relative):
    path = tmp_path.joinpath(*relative)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"")
    read_only(path)

    message = find_storage_problem(tmp_path)

    assert message is not None and str(path) in message


def test_startup_shows_the_message_and_asks_to_close(qapp, tmp_path, monkeypatch):
    import app
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a)))
    blocker = tmp_path / "blocker"
    blocker.write_text("")

    assert app.check_storage_or_warn(blocker / "HydroTopo") is False
    assert len(shown) == 1 and shown[0][1] == "HydroTopo ne peut pas démarrer"
    assert "Déplacez HydroTopo" in shown[0][2]

    shown.clear()
    assert app.check_storage_or_warn(tmp_path) is True
    assert shown == []
