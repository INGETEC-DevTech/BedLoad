"""core/ ne fait que du calcul : il ne doit dépendre d'aucune couche d'affichage (graphiques,
interface). La présentation vit dans viz/ et ui/."""
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DISPLAY_PACKAGES = {"plotly", "PyQt6", "viz", "ui"}


def test_core_modules_import_no_display_package():
    """Dans un processus neuf (celui des tests a déjà chargé Qt et Plotly) : importer tout
    core/ ne doit charger aucun paquet d'affichage, même indirectement."""
    modules = sorted(f"core.{path.stem}" for path in (APP_DIR / "core").glob("*.py") if path.stem != "__init__")
    code = "import sys\n" + "".join(f"import {module}\n" for module in modules) + (
        f"print(sorted({{name.split('.')[0] for name in sys.modules}} & {DISPLAY_PACKAGES!r}))"
    )

    result = subprocess.run([sys.executable, "-c", code], cwd=APP_DIR, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "core.controller" in modules
    assert result.stdout.strip() == "[]"
