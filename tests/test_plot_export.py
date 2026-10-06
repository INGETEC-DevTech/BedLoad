"""Export PNG du graphique : écriture du fichier à partir de l'image produite par Plotly, et
nom de fichier proposé selon ce qui est affiché. La production de l'image elle-même (dans la
page web) ne peut pas tourner ici : le moteur web ne démarre pas sans affichage."""
import base64

import pytest

from ui.views.plot_view import save_png_data_url

# Plus petit PNG valide (1 x 1 pixel transparent).
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def test_png_data_url_is_written_as_a_png_file(tmp_path):
    path = tmp_path / "graphique.png"

    save_png_data_url(path, "data:image/png;base64," + base64.b64encode(TINY_PNG).decode())

    assert path.read_bytes() == TINY_PNG


def test_anything_else_than_a_png_is_refused(tmp_path):
    path = tmp_path / "graphique.png"

    with pytest.raises(ValueError):
        save_png_data_url(path, "data:image/svg+xml;base64,PHN2Zz4=")
    assert not path.exists()
