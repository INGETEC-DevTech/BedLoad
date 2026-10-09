"""Script de la page du graphique (cf. ui.views.plot_view._build_page_html), exécuté hors
du moteur web, qui ne démarre pas pendant les tests : avec JScript (cscript, livré avec
Windows), sur un faux DOM et un faux Plotly (tests/js/page_stubs.js), pour les scénarios
de tests/js/page_scenarios.js (étirement des axes du profil en long, case « Échelle
orthonormée »). JScript ne connaît que l'ES3 : le script de la page doit rester écrit
comme aujourd'hui (var, function), sans let, const ni fonctions fléchées.

Ce test vérifie la logique du script, pas la réaction de Plotly lui-même."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ui.views.plot_view import _build_page_html

JS_DIR = Path(__file__).resolve().parent / "js"


def _page_script() -> str:
    return re.findall(r"<script>(.*?)</script>", _build_page_html("plotly.js"), re.S)[-1]


@pytest.mark.skipif(shutil.which("cscript") is None, reason="JScript (cscript) indisponible")
def test_page_script_passes_its_mouse_scenarios(tmp_path):
    source = "".join([
        (JS_DIR / "page_stubs.js").read_text(encoding="utf-8"),
        _page_script(),
        (JS_DIR / "page_scenarios.js").read_text(encoding="utf-8"),
    ])
    harness = tmp_path / "harness.js"
    harness.write_text(source, encoding="utf-16")  # lu tel quel par JScript, accents compris

    result = subprocess.run(["cscript", "//nologo", "//E:jscript", str(harness)],
                            capture_output=True, timeout=60)

    output = (result.stdout + result.stderr).decode("cp850", "replace").strip()
    assert result.returncode == 0, output
    assert "0 echec(s)" in output, output
