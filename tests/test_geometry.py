import pytest

from core.geometry import build_project_cross_section
from core.models import ProjectParameters


def test_build_project_cross_section_default_params():
    """Vérifie chaque point contre un calcul à la main (valeurs par défaut de ProjectParameters)."""
    params = ProjectParameters()
    section = build_project_cross_section(params)

    assert [p.x for p in section.points] == pytest.approx(
        [0.239, 3.239, 3.24, 3.78, 5.78, 6.32, 7.12, 10.12]
    )
    assert [p.z for p in section.points] == pytest.approx(
        [49.336666667, 47.67, 47.67, 47.40, 47.40, 47.67, 47.67, 48.87]
    )


def test_build_project_cross_section_point_order_and_count():
    """L'ordre documenté (hdbg, pdbg, banq1, fdlg, fdld, banq2, pdbd, hdbd) doit être respecté,
    et les X doivent être strictement croissants de gauche à droite pour une géométrie valide."""
    params = ProjectParameters()
    section = build_project_cross_section(params)

    assert len(section.points) == 8
    xs = [p.x for p in section.points]
    assert xs == sorted(xs)
    assert len(set(xs)) == len(xs)


def test_anchor_point_is_bed_left_corner():
    """Le point d'ancrage (anchor_x, anchor_z) doit correspondre exactement au bord gauche du fond du lit (fdlg)."""
    params = ProjectParameters(anchor_x=10.0, anchor_z=100.0)
    section = build_project_cross_section(params)

    fdlg = section.points[3]
    assert fdlg.x == pytest.approx(10.0)
    assert fdlg.z == pytest.approx(100.0)


def test_bed_width_sets_bed_corners_distance():
    """La largeur du fond de lit doit séparer fdlg et fdld exactement de bed_width."""
    params = ProjectParameters(bed_width=5.0)
    section = build_project_cross_section(params)

    fdlg, fdld = section.points[3], section.points[4]
    assert fdld.x - fdlg.x == pytest.approx(5.0)
    assert fdld.z == pytest.approx(fdlg.z)


def test_zero_bank_slope_raises_zero_division_error():
    """Documente un bug connu (cf. audit) : une pente de berge nulle provoque une division par zéro
    au niveau du modèle, sans validation ni message d'erreur explicite. Ce test doit être mis à jour
    (ex: pytest.raises(ValueError)) le jour où une validation est ajoutée à ProjectParameters."""
    params = ProjectParameters(bank_slope_left=0.0)

    with pytest.raises(ZeroDivisionError):
        build_project_cross_section(params)
