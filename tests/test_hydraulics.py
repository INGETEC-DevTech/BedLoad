import math

import pytest

from core.hydraulics import (
    compute_hydraulic_params,
    find_water_level_for_discharge,
    get_water_intersections,
)
from core.models import CrossSection, Point


@pytest.fixture
def trapezoidal_section() -> CrossSection:
    """Canal trapézoïdal symétrique : fond plat de x=1 à x=4 (z=0), berges de pente 1:2
    (1 m horizontal pour 2 m vertical) remontant jusqu'à z=2 en x=0 et x=5."""
    return CrossSection(
        name="test",
        points=[
            Point(x=0, z=2),
            Point(x=1, z=0),
            Point(x=4, z=0),
            Point(x=5, z=2),
        ],
    )


def test_get_water_intersections_mid_bank(trapezoidal_section):
    """Pour une cote d'eau de 1 m, l'eau doit couper chaque berge à mi-hauteur (x=0.5 et x=4.5)."""
    x_left, x_right = get_water_intersections(trapezoidal_section, water_z=1.0)
    assert x_left == pytest.approx(0.5)
    assert x_right == pytest.approx(4.5)


def test_get_water_intersections_below_bed_returns_none(trapezoidal_section):
    """Une cote d'eau sous le fond du lit ne doit trouver aucune intersection."""
    x_left, x_right = get_water_intersections(trapezoidal_section, water_z=-1.0)
    assert x_left is None
    assert x_right is None


def test_get_water_intersections_above_banks_returns_none(trapezoidal_section):
    """Une cote d'eau au-dessus du sommet des berges ne doit trouver aucune intersection
    (la fonction ne gère pas le débordement, cf. audit)."""
    x_left, x_right = get_water_intersections(trapezoidal_section, water_z=3.0)
    assert x_left is None
    assert x_right is None


def test_compute_hydraulic_params_matches_hand_calculation(trapezoidal_section):
    """Vérifie S, P, Rh contre un calcul géométrique manuel pour une cote d'eau de 1 m :
    S = aire du trapèze (largeur fond 3 m, largeur miroir 4 m, hauteur 1 m) = 3.5 m².
    P = 2 * sqrt(0.5^2 + 1^2) + 3 = somme des longueurs mouillées des 2 berges + du fond.
    """
    res = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)

    expected_s = 3.5
    expected_p = 2 * math.sqrt(0.5**2 + 1.0**2) + 3.0
    expected_rh = expected_s / expected_p
    expected_v = 30.0 * expected_rh ** (2 / 3) * math.sqrt(0.001)
    expected_q = expected_v * expected_s

    assert res["S"] == pytest.approx(expected_s)
    assert res["P"] == pytest.approx(expected_p)
    assert res["Rh"] == pytest.approx(expected_rh)
    assert res["V"] == pytest.approx(expected_v)
    assert res["Q"] == pytest.approx(expected_q)
    assert res["x_left"] == pytest.approx(0.5)
    assert res["x_right"] == pytest.approx(4.5)


@pytest.mark.parametrize("slope,ks", [(0.0, 30.0), (-0.001, 30.0), (0.001, 0.0), (0.001, -5.0)])
def test_compute_hydraulic_params_invalid_slope_or_ks_returns_zeros(trapezoidal_section, slope, ks):
    """Une pente ou un coefficient de Strickler nul ou négatif doit renvoyer un résultat neutre,
    et ne jamais lever d'exception (division par zéro potentielle sinon)."""
    res = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=slope, ks=ks)

    assert res == {
        "S": 0, "P": 0, "Rh": 0, "V": 0, "Q": 0,
        "water_z": 1.0, "x_left": None, "x_right": None,
    }


def test_compute_hydraulic_params_no_intersection_returns_zeros(trapezoidal_section):
    """Si la cote d'eau ne coupe pas le profil (ex: sous le fond du lit), le résultat doit rester neutre."""
    res = compute_hydraulic_params(trapezoidal_section, water_z=-1.0, slope=0.001, ks=30.0)
    assert res["S"] == 0
    assert res["Q"] == 0


def test_find_water_level_for_discharge_converges_to_known_level(trapezoidal_section):
    """En injectant le débit calculé pour z=1 m, la dichotomie doit retrouver une cote d'eau proche de 1 m."""
    target = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)["Q"]

    res = find_water_level_for_discharge(trapezoidal_section, target_q=target, slope=0.001, ks=30.0)

    assert res["water_z"] == pytest.approx(1.0, abs=1e-3)
    assert res["Q"] == pytest.approx(target, abs=0.01)


def test_find_water_level_for_discharge_unreachable_target_stops_at_bank_top(trapezoidal_section):
    """Documente le comportement actuel (cf. audit) : si le débit cible dépasse la capacité du profil,
    la fonction s'arrête silencieusement à la cote la plus haute du profil (z=2) sans avertir l'appelant."""
    res = find_water_level_for_discharge(trapezoidal_section, target_q=1e9, slope=0.001, ks=30.0)

    z_max = max(p.z for p in trapezoidal_section.points)
    assert res["water_z"] == pytest.approx(z_max)
    assert res["Q"] < 1e9
