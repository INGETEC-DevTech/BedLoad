"""
Test de non-régression : vérifie que build_project_cross_section() reproduit
EXACTEMENT les points calculés par la feuille CT1 du classeur Excel
hydrotopo_v_1_5_1.xlsx (paramètres D3:D12, résultats table AC5:AD16).

Exécution : python -m pytest tests/ -v
(ou simplement : python tests/test_geometry.py)
"""

from core.geometry import build_project_cross_section
from core.models import ProjectParameters

# Paramètres exacts de la coupe CT1 de l'Excel de référence.
_CT1_PARAMS = ProjectParameters(
    bed_width=2.0,           # D3
    bed_depth=0.27,          # D4
    bed_side_slope=2.0,      # D5
    berm_width_left=0.001,   # D6
    berm_width_right=0.8,    # D7
    bank_slope_left=1.8,     # D8
    bank_width_left=3.0,     # D9
    bank_slope_right=2.5,    # D11
    bank_width_right=3.0,    # D12
    anchor_x=3.78,           # Xfond_pro (fdlg dans l'Excel)
    anchor_z=47.4,           # Zfond_pro
)

# Points de référence lus directement dans l'Excel (plage AC5:AD16 de CT1).
_EXPECTED_POINTS = [
    (0.239, 49.336666666666666),   # haut de berge gauche (hdbg)
    (3.239, 47.67),                # pied de berge gauche (pdbg)
    (3.24, 47.67),                 # banquette gauche (banq1)
    (3.78, 47.4),                  # bord gauche du fond du lit (fdlg)
    (5.78, 47.4),                  # bord droit du fond du lit (fdld)
    (6.32, 47.67),                 # banquette droite (banq2)
    (7.12, 47.67),                 # pied de berge droit (pdbd)
    (10.12, 48.87),                # haut de berge droit (hdbd)
]


def test_matches_excel_ct1_reference():
    section = build_project_cross_section(_CT1_PARAMS)
    assert len(section.points) == len(_EXPECTED_POINTS)
    for point, (expected_x, expected_z) in zip(section.points, _EXPECTED_POINTS):
        assert abs(point.x - expected_x) < 1e-6, f"X attendu {expected_x}, obtenu {point.x}"
        assert abs(point.z - expected_z) < 1e-6, f"Z attendu {expected_z}, obtenu {point.z}"


if __name__ == "__main__":
    test_matches_excel_ct1_reference()
    print("OK : la géométrie générée correspond exactement à la référence Excel CT1.")
