import math

import pytest

from core.hydraulics import (
    compute_hydraulic_params,
    find_water_level_for_discharge,
    get_water_intersections,
    resolve_hydraulic_result,
)
from core.models import CrossSection, Point
from core.geometry import build_project_cross_section
from core.models import ProjectParameters


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
    la fonction s'arrête silencieusement à la cote la plus haute du profil (z=2) sans avertir l'appelant.
    Le débit à cette cote doit rester celui, non nul, du plein bord (cf. fix de l'intervalle fermé
    dans get_water_intersections : ce n'est plus 0 par simple effet de bord de comparaison stricte)."""
    res = find_water_level_for_discharge(trapezoidal_section, target_q=1e9, slope=0.001, ks=30.0)

    z_max = max(p.z for p in trapezoidal_section.points)
    assert res["water_z"] == pytest.approx(z_max)
    assert res["Q"] < 1e9
    assert res["Q"] > 0


def test_get_water_intersections_exact_top_of_profile_is_valid():
    """Cf. audit : quand le niveau d'eau testé est exactement égal au point le plus haut du
    profil, la comparaison stricte ("<" au lieu de "<=") faisait perdre l'intersection côté
    du sommet atteint, et le débit retombait à 0 alors qu'un débit de plein bord est
    calculable à ce niveau."""
    section = CrossSection(
        name="test",
        points=[Point(x=0, z=2), Point(x=1, z=0), Point(x=4, z=0), Point(x=5, z=2)],
    )

    x_left, x_right = get_water_intersections(section, water_z=2.0)

    assert x_left == pytest.approx(0.0)
    assert x_right == pytest.approx(5.0)


def test_compute_hydraulic_params_at_exact_top_returns_nonzero_discharge(trapezoidal_section):
    z_max = max(p.z for p in trapezoidal_section.points)

    res = compute_hydraulic_params(trapezoidal_section, water_z=z_max, slope=0.001, ks=30.0)

    assert res["S"] == pytest.approx(8.0)  # trapèze : (largeur fond 3 + largeur miroir 5) / 2 * hauteur 2
    assert res["Q"] > 0


def test_get_water_intersections_handles_horizontal_shelf_at_water_level():
    """Un profil avec un palier horizontal exactement à la cote d'eau testée (plusieurs
    sommets à la même altitude, de part et d'autre d'un creux) ne doit ni planter (division
    par zéro sur le segment horizontal) ni élargir la largeur mouillée au-delà des bords
    réels du creux."""
    section = CrossSection(
        name="test",
        points=[
            Point(x=0, z=2),
            Point(x=1, z=1),
            Point(x=2, z=1),  # palier horizontal à z=1
            Point(x=3, z=0),
            Point(x=4, z=1),  # symétrique côté droit
            Point(x=5, z=2),
        ],
    )

    x_left, x_right = get_water_intersections(section, water_z=1.0)

    # Sans dédoublonnage, le palier horizontal (deux extrémités à z=1) et les sommets
    # partagés avec les segments voisins produiraient plus de deux abscisses candidates ;
    # seules les deux extrêmes doivent ressortir.
    assert x_left == pytest.approx(1.0)
    assert x_right == pytest.approx(4.0)


class TestResolveHydraulicResult:
    """resolve_hydraulic_result est le point d'entrée unique utilisé par
    core.controller.ProfileController pour l'onglet Hydraulique. Ces tests vérifient qu'il
    n'a AUCUN état interne : le résultat ne dépend que des arguments reçus à CET appel, donc
    changer de mode, de profil ou de valeur imposée ne peut jamais laisser filtrer le
    résultat d'un appel précédent (cf. bug rapporté : tirant d'eau/vitesse périmés affichés
    en mode "Imposer Q")."""

    @staticmethod
    def _reproduction_section():
        """Géométrie du cas de reproduction rapporté : bed_width=0.80, bed_depth=0.38,
        bed_side_slope=1.60, berges 2.20/1.30, largeurs 2.40/1.50."""
        params = ProjectParameters(
            bed_width=0.80, bed_depth=0.38, bed_side_slope=1.60,
            berm_width_left=0.0, berm_width_right=0.0,
            berm_slope_left=0.0, berm_slope_right=0.0,
            bank_slope_left=2.20, bank_width_left=2.40,
            bank_slope_right=1.30, bank_width_right=1.50,
            anchor_x=6.49, anchor_z=81.97,
        )
        return build_project_cross_section(params), params.anchor_z

    def test_reported_reproduction_case_gives_correct_depth_not_stale_h_eau(self):
        """Cas de reproduction exact du rapport de bug : cible Q=8.00 m³/s doit donner un
        tirant d'eau proche de 0.93 m — jamais 0.54 m (l'ancien h_eau d'un précédent passage
        en mode "Imposer H")."""
        section, anchor_z = self._reproduction_section()

        res = resolve_hydraulic_result(
            section, calc_mode='H_FROM_Q',
            q_target=8.00, h_eau=0.54,  # h_eau volontairement laissé à une valeur périmée
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )

        h = res["water_z"] - anchor_z
        assert h == pytest.approx(0.93, abs=0.02)
        assert h != pytest.approx(0.54, abs=0.05)
        assert res["V"] == pytest.approx(3.71, abs=0.05)
        assert res["S"] == pytest.approx(2.15, abs=0.05)
        assert res["Q"] == pytest.approx(8.00, abs=0.01)

    def test_switching_calc_mode_recomputes_from_scratch(self):
        """Basculer de "Imposer H" à "Imposer Q" (même section) doit changer le résultat en
        conséquence, pas répéter l'ancien tirant d'eau saisi."""
        section, anchor_z = self._reproduction_section()

        res_impose_h = resolve_hydraulic_result(
            section, calc_mode='Q_FROM_H',
            q_target=999.0, h_eau=0.54,  # q_target ignoré dans ce mode : ne doit rien changer
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )
        res_impose_q = resolve_hydraulic_result(
            section, calc_mode='H_FROM_Q',
            q_target=8.00, h_eau=0.54,
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )

        assert res_impose_h["water_z"] - anchor_z == pytest.approx(0.54)
        assert res_impose_q["water_z"] - anchor_z == pytest.approx(0.93, abs=0.02)
        assert res_impose_h["water_z"] != res_impose_q["water_z"]

    def test_changing_q_target_alone_recomputes_result(self):
        """Changer uniquement le débit cible (sans changer de mode ni de profil) doit
        redéclencher un vrai recalcul du tirant d'eau — pas de valeur figée."""
        section, anchor_z = self._reproduction_section()

        res_q8 = resolve_hydraulic_result(
            section, calc_mode='H_FROM_Q', q_target=8.00, h_eau=0.0,
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )
        res_q12 = resolve_hydraulic_result(
            section, calc_mode='H_FROM_Q', q_target=12.00, h_eau=0.0,
            z_ref=anchor_z, slope=0.058, ks=25.0,
        )

        assert res_q8["water_z"] != res_q12["water_z"]
        assert res_q12["water_z"] > res_q8["water_z"]  # plus de débit -> tirant d'eau plus grand
        assert res_q8["Q"] == pytest.approx(8.00, abs=0.01)
        assert res_q12["Q"] == pytest.approx(12.00, abs=0.01)

    def test_changing_profile_geometry_recomputes_result(self):
        """Changer de profil (section différente), en restant dans le même mode et avec le
        même débit cible, doit donner un tirant d'eau propre à la NOUVELLE géométrie."""
        section_a, anchor_z_a = self._reproduction_section()
        params_b = ProjectParameters(
            bed_width=2.40, bed_depth=1.00, bed_side_slope=2.00,
            anchor_x=3.78, anchor_z=47.40,
        )
        section_b = build_project_cross_section(params_b)

        res_a = resolve_hydraulic_result(
            section_a, calc_mode='H_FROM_Q', q_target=8.00, h_eau=0.0,
            z_ref=anchor_z_a, slope=0.058, ks=25.0,
        )
        res_b = resolve_hydraulic_result(
            section_b, calc_mode='H_FROM_Q', q_target=8.00, h_eau=0.0,
            z_ref=params_b.anchor_z, slope=0.058, ks=25.0,
        )

        assert (res_a["water_z"] - anchor_z_a) != pytest.approx(res_b["water_z"] - params_b.anchor_z)
