"""
Construction géométrique du profil projet ("lit emboîté").

Reproduit fidèlement la mécanique du bloc "Dimensionnement lit emboîté" de la
feuille CT de l'Excel hydrotopo (cellules D3:D12 -> table de points AC5:AD16).

Ce n'est PAS un calcul hydraulique : c'est de la géométrie pure (on place des
points les uns par rapport aux autres à partir de largeurs et de pentes).
C'est la version simplifiée : contrairement à l'Excel, le raccord automatique
entre le haut de berge et le terrain existant (recherche d'intersection avec
une pente de stabilité) n'est pas implémenté ici. L'utilisateur positionne le
profil projet à la main via le point d'ancrage (anchor_x, anchor_z).

Les formules ci-dessous ont été validées contre les valeurs réelles de la
feuille CT1 du classeur hydrotopo_v_1_5_1.xlsx (voir tests/test_geometry.py).
"""

from core.models import CrossSection, Point, ProjectParameters


def build_project_cross_section(params: ProjectParameters, name: str = "Profil projet") -> CrossSection:
    """
    Construit le profil projet de gauche à droite, à partir du bord gauche du
    fond du lit (point d'ancrage).

    Ordre des points générés (8 points, de gauche à droite) :
        haut de berge gauche (hdbg)
        pied de berge gauche (pdbg)
        banquette gauche (banq1)
        bord gauche du fond du lit (fdlg)   <- point d'ancrage
        bord droit du fond du lit (fdld)
        banquette droite (banq2)
        pied de berge droit (pdbd)
        haut de berge droit (hdbd)
    """
    p = params

    # Fond du lit (plat, largeur = bed_width), calé sur le point d'ancrage.
    fdlg = Point(x=p.anchor_x, z=p.anchor_z)
    fdld = Point(x=fdlg.x + p.bed_width, z=fdlg.z)

    # Sommet des talus du lit d'étiage (on remonte de bed_depth, avec une
    # pente bed_side_slope de chaque côté).
    banq1 = Point(x=fdlg.x - p.bed_side_slope * p.bed_depth, z=fdlg.z + p.bed_depth)
    banq2 = Point(x=fdld.x + p.bed_side_slope * p.bed_depth, z=fdld.z + p.bed_depth)

    # Banquettes (largeur horizontale, altitude constante).
    pdbg = Point(x=banq1.x - p.berm_width_left, z=banq1.z)
    pdbd = Point(x=banq2.x + p.berm_width_right, z=banq2.z)

    # Berges (largeur horizontale bank_width, pente bank_slope -> montée
    # verticale = bank_width / bank_slope).
    hdbg = Point(x=pdbg.x - p.bank_width_left, z=pdbg.z + p.bank_width_left / p.bank_slope_left)
    hdbd = Point(x=pdbd.x + p.bank_width_right, z=pdbd.z + p.bank_width_right / p.bank_slope_right)

    points = [hdbg, pdbg, banq1, fdlg, fdld, banq2, pdbd, hdbd]
    return CrossSection(name=name, points=points)
