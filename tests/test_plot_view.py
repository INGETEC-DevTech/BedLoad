"""Étendue des données d'une figure : elle décide si le zoom mémorisé du profil en long
(en cadrage automatique) vaut encore. La mémoire elle-même vit dans la page web, qui ne
peut pas tourner ici (le moteur web ne démarre pas sans affichage)."""
import plotly.graph_objects as go

from core.longitudinal import build_longitudinal_profile
from viz.plots import plot_longitudinal_profile
from ui.views.plot_view import data_extent

HARD_POINTS = [{"name": "A", "pk": 0.0, "z": 50.0}, {"name": "B", "pk": 300.0, "z": 47.0}]


def test_extent_covers_every_trace_including_hard_points():
    fig = plot_longitudinal_profile(build_longitudinal_profile([(100.0, 48.0, 47.5)], HARD_POINTS))

    assert data_extent(fig) == [[0.0, 300.0], [47.0, 50.0]]


def test_extent_ignores_missing_values_and_is_none_without_points():
    fig = go.Figure([go.Scatter(x=[1.0, None, 3.0], y=[5.0, 6.0, None])])
    assert data_extent(fig) == [[1.0, 1.0], [5.0, 5.0]]

    assert data_extent(go.Figure()) is None


def test_longitudinal_profile_is_orthonormal_only_on_request():
    profile = build_longitudinal_profile([(100.0, 48.0, 47.5)], HARD_POINTS)

    free = plot_longitudinal_profile(profile)
    orthonormal = plot_longitudinal_profile(profile, orthonormal=True)

    assert free.layout.yaxis.scaleanchor is None
    assert (orthonormal.layout.yaxis.scaleanchor, orthonormal.layout.yaxis.scaleratio) == ("x", 1)


def test_extent_is_unchanged_when_an_inner_point_moves():
    """Modifier un profil sans changer l'étendue garde le zoom ; l'élargir le réinitialise."""
    rows = [(100.0, 48.0, 47.5), (200.0, 47.8, 47.2)]
    before = data_extent(plot_longitudinal_profile(build_longitudinal_profile(rows, HARD_POINTS)))

    rows[0] = (100.0, 48.5, 47.5)
    assert data_extent(plot_longitudinal_profile(build_longitudinal_profile(rows, HARD_POINTS))) == before

    rows[0] = (100.0, 52.0, 47.5)
    assert data_extent(plot_longitudinal_profile(build_longitudinal_profile(rows, HARD_POINTS))) != before
