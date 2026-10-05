import math

import pytest

from core.hydraulics import (
    clip_to_bounds,
    compute_hydraulic_params,
    find_water_level_for_discharge,
    get_wet_beds,
    resolve_hydraulic_result,
)


def get_water_intersections(section, water_z, bounds=None):
    """Bornes extrêmes (x gauche, x droite) de la zone mouillée, ou (None, None)."""
    beds = get_wet_beds(section, water_z, bounds)
    if not beds:
        return None, None
    return beds[0][0].x, beds[-1][-1].x
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
        "water_z": 1.0, "x_left": None, "x_right": None, "wet_intervals": [],
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
    réels du creux. Le palier lui-même (profondeur nulle) n'est pas mouillé : le lit
    commence à x=2, là où le terrain passe sous l'eau."""
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

    assert x_left == pytest.approx(2.0)
    assert x_right == pytest.approx(4.0)


# --- Plusieurs lits dans le même profil ---

@pytest.fixture
def two_beds_section() -> CrossSection:
    """Deux lits trapézoïdaux identiques séparés par un merlon : lit A de x=0 à x=5, merlon
    culminant à z=3 en x=6, lit B de x=7 à x=12. Les berges extérieures montent à z=2."""
    return CrossSection(
        name="test",
        points=[
            Point(x=0, z=2), Point(x=1, z=0), Point(x=4, z=0), Point(x=5, z=2),
            Point(x=6, z=3),
            Point(x=7, z=2), Point(x=8, z=0), Point(x=11, z=0), Point(x=12, z=2),
        ],
    )


def test_water_line_stops_at_the_emerging_bank_and_restarts_in_the_second_bed(two_beds_section):
    res = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0)

    assert res["wet_intervals"] == [pytest.approx((0.5, 4.5)), pytest.approx((7.5, 11.5))]
    assert (res["x_left"], res["x_right"]) == pytest.approx((0.5, 11.5))


def test_two_identical_beds_carry_twice_the_flow_of_one(two_beds_section, trapezoidal_section):
    """Le merlon émergé n'entre ni dans la surface ni dans le périmètre : chaque lit garde
    son propre rayon hydraulique, donc deux lits identiques = exactement deux fois un lit."""
    one = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)
    two = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0)

    assert two["S"] == pytest.approx(2 * one["S"])
    assert two["P"] == pytest.approx(2 * one["P"])
    assert two["Q"] == pytest.approx(2 * one["Q"])
    assert two["V"] == pytest.approx(one["V"])


def test_bounds_restrict_the_calculation_to_one_bed(two_beds_section, trapezoidal_section):
    one = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)

    res = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0, bounds=(6.0, 20.0))

    assert res["wet_intervals"] == [pytest.approx((7.5, 11.5))]
    assert res["Q"] == pytest.approx(one["Q"])


def test_bound_inside_the_water_acts_as_a_wall_not_counted_in_perimeter(trapezoidal_section):
    """Limite droite au milieu du fond (x=2.5) : l'eau s'arrête sur la paroi fictive. La
    surface est la moitié gauche du trapèze, le périmètre ne compte que le terrain mouillé."""
    res = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0, bounds=(-10.0, 2.5))

    assert res["wet_intervals"] == [pytest.approx((0.5, 2.5))]
    assert res["S"] == pytest.approx(3.5 / 2)
    assert res["P"] == pytest.approx(math.sqrt(0.5**2 + 1.0**2) + 1.5)


def test_bounds_outside_the_profile_change_nothing(two_beds_section):
    free = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0)
    wide = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0, bounds=(-100.0, 100.0))

    assert wide == free


def test_bounds_not_overlapping_the_profile_give_no_water(two_beds_section):
    res = compute_hydraulic_params(two_beds_section, water_z=1.0, slope=0.001, ks=30.0, bounds=(50.0, 60.0))

    assert res["Q"] == 0 and res["wet_intervals"] == []
    assert find_water_level_for_discharge(two_beds_section, 5.0, 0.001, 30.0, bounds=(50.0, 60.0))["Q"] == 0


def test_clip_to_bounds_interpolates_the_terrain_on_each_bound(trapezoidal_section):
    points, wall_left, wall_right = clip_to_bounds(trapezoidal_section.points, (0.5, 4.0))

    assert (wall_left, wall_right) == (True, True)
    assert [(p.x, p.z) for p in points] == [(0.5, 1.0), (1, 0), (4, 0)]


def test_find_water_level_with_bounds_solves_in_the_chosen_bed_only(two_beds_section, trapezoidal_section):
    target = compute_hydraulic_params(trapezoidal_section, water_z=1.0, slope=0.001, ks=30.0)["Q"]

    res = find_water_level_for_discharge(two_beds_section, target, 0.001, 30.0, bounds=(6.0, 20.0))

    # La dichotomie s'arrête à 0.01 m³/s près sur le débit, pas sur la cote.
    assert res["water_z"] == pytest.approx(1.0, abs=5e-3)
    assert res["Q"] == pytest.approx(target, abs=0.01)
    assert res["wet_intervals"] == [pytest.approx((7.5, 11.5), abs=1e-2)]


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


# --- Onglet Hydraulique (contrôleur + graphique) ---

TWO_BEDS_POINTS = [
    {"X (m)": x, "Z (m NGF)": z}
    for x, z in [(0, 2), (1, 0), (4, 0), (5, 2), (6, 3), (7, 2), (8, 0), (11, 0), (12, 2)]
]


def _hydraulics_figure(**hydro):
    from core.controller import ProfileController, ViewMode
    data = {"hydro_source": "existing", "calc_mode": "Q_FROM_H", "h_eau": 1.0,
            "slope": 0.001, "ks_pro": 30.0, **hydro}
    return ProfileController().build_figure(TWO_BEDS_POINTS, data, ViewMode.HYDRAULICS)


def _water_trace(fig):
    return next(t for t in fig.data if t.name == "Ligne d'eau")


def test_hydraulics_figure_draws_one_water_segment_per_bed():
    trace = _water_trace(_hydraulics_figure())

    # Le None coupe le trait au-dessus du merlon émergé, entre les deux lits.
    assert list(trace.x[:2]) == pytest.approx([0.5, 4.5])
    assert trace.x[2] is None
    assert list(trace.x[3:]) == pytest.approx([7.5, 11.5])


def test_hydraulics_figure_with_bounds_draws_only_the_chosen_bed_and_the_bounds():
    fig = _hydraulics_figure(hydro_bounds_enabled=True, hydro_x_left=6.0, hydro_x_right=13.0)

    assert list(_water_trace(fig).x) == pytest.approx([7.5, 11.5])
    assert sorted(shape.x0 for shape in fig.layout.shapes) == [6.0, 13.0]
    assert "Lit de calcul" in fig.layout.annotations[0].text


def test_hydraulics_bounds_disabled_are_ignored_even_if_inconsistent():
    fig = _hydraulics_figure(hydro_bounds_enabled=False, hydro_x_left=5.0, hydro_x_right=1.0)

    assert len(_water_trace(fig).x) == 5
    assert not fig.layout.shapes


def test_hydraulics_inconsistent_bounds_raise_a_readable_error():
    with pytest.raises(ValueError, match="X gauche"):
        _hydraulics_figure(hydro_bounds_enabled=True, hydro_x_left=5.0, hydro_x_right=5.0)


def test_existing_source_depth_is_measured_from_the_bottom_of_the_chosen_bed():
    """Lit de droite relevé de 0.5 m : avec les limites sur ce lit, "h = 1 m" doit donner une
    cote d'eau à 1.5 (fond du lit choisi + 1), pas 1.0 (fond de l'autre lit + 1)."""
    from core.controller import ProfileController, ViewMode
    points = [{"X (m)": p["X (m)"], "Z (m NGF)": p["Z (m NGF)"] + (0.5 if p["X (m)"] >= 7 else 0)}
              for p in TWO_BEDS_POINTS]
    data = {"hydro_source": "existing", "calc_mode": "Q_FROM_H", "h_eau": 1.0, "slope": 0.001,
            "ks_pro": 30.0, "hydro_bounds_enabled": True, "hydro_x_left": 6.0, "hydro_x_right": 13.0}

    fig = ProfileController().build_figure(points, data, ViewMode.HYDRAULICS)

    assert list(_water_trace(fig).y) == pytest.approx([1.5, 1.5])
