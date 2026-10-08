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
feuille CT1 du classeur hydrotopo_v_1_5_1.xlsx.
"""

import math

from core.models import CrossSection, Point, ProjectParameters, Subsection


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

    Un lit majeur optionnel peut s'ajouter de chaque côté, juste après la berge
    (donc avant hdbg / après hdbd) : bout du lit majeur gauche (lmg) et bout du
    lit majeur droit (lmd). Il n'apparaît que si sa largeur (floodplain_width_*)
    est strictement positive ; à 0 (valeur par défaut), le comportement est
    inchangé.
    """
    p = params

    # Fond du lit (plat, largeur = bed_width), calé sur le point d'ancrage.
    fdlg = Point(x=p.anchor_x, z=p.anchor_z)
    fdld = Point(x=fdlg.x + p.bed_width, z=fdlg.z)

    # Sommet des talus du lit d'étiage (on remonte de bed_depth, avec une
    # pente bed_side_slope de chaque côté).
    banq1 = Point(x=fdlg.x - p.bed_side_slope * p.bed_depth, z=fdlg.z + p.bed_depth)
    banq2 = Point(x=fdld.x + p.bed_side_slope * p.bed_depth, z=fdld.z + p.bed_depth)

    # Banquettes (largeur horizontale, pente berm_slope montante vers l'extérieur ;
    # 0 = plat, comportement historique).
    pdbg = Point(x=banq1.x - p.berm_width_left, z=banq1.z + p.berm_width_left * p.berm_slope_left)
    pdbd = Point(x=banq2.x + p.berm_width_right, z=banq2.z + p.berm_width_right * p.berm_slope_right)

    # Berges (largeur horizontale bank_width, pente bank_slope -> montée
    # verticale = bank_width / bank_slope).
    hdbg = Point(x=pdbg.x - p.bank_width_left, z=pdbg.z + p.bank_width_left / p.bank_slope_left)
    hdbd = Point(x=pdbd.x + p.bank_width_right, z=pdbd.z + p.bank_width_right / p.bank_slope_right)

    # Lit majeur optionnel (largeur horizontale, pente floodplain_slope montante vers
    # l'extérieur ; 0 = plat, comportement historique). N'est ajouté que si sa largeur
    # est strictement positive, sinon le point serait un doublon exact de hdbg/hdbd.
    lmg = None
    if p.floodplain_width_left > 0:
        lmg = Point(x=hdbg.x - p.floodplain_width_left, z=hdbg.z + p.floodplain_width_left * p.floodplain_slope_left)

    lmd = None
    if p.floodplain_width_right > 0:
        lmd = Point(x=hdbd.x + p.floodplain_width_right, z=hdbd.z + p.floodplain_width_right * p.floodplain_slope_right)

    # Bout de la géométrie côté gauche/droit avant un éventuel raccord : le lit majeur
    # quand il est activé, sinon le haut de berge (comportement historique).
    end_left = lmg if lmg is not None else hdbg
    end_right = lmd if lmd is not None else hdbd

    # Raccord optionnel vers un point du profil existant, choisi manuellement (valeur
    # figée à la sélection) : prolonge la géométrie au-delà du bout du lit majeur (ou,
    # à défaut, du haut de berge).
    raccord_g = None
    if p.connect_x_left is not None:
        if not (p.connect_x_left < end_left.x):
            raise ValueError(
                "Le point de raccord gauche est plus proche de l'axe du lit que le "
                "bout du lit majeur (ou le haut de berge) actuel — géométrie invalide."
            )
        raccord_g = Point(x=p.connect_x_left, z=p.connect_z_left)

    raccord_d = None
    if p.connect_x_right is not None:
        if not (p.connect_x_right > end_right.x):
            raise ValueError(
                "Le point de raccord droit est plus proche de l'axe du lit que le "
                "bout du lit majeur (ou le haut de berge) actuel — géométrie invalide."
            )
        raccord_d = Point(x=p.connect_x_right, z=p.connect_z_right)

    # Noms des points, repris tels quels dans l'export Excel du profil projet.
    for point, label in (
        (raccord_g, "Raccord terrain G"), (lmg, "Bout lit majeur G"),
        (hdbg, "Haut de berge G"), (pdbg, "Pied de berge G"), (banq1, "Banquette G"),
        (fdlg, "Fond du lit G (ancrage)"), (fdld, "Fond du lit D"),
        (banq2, "Banquette D"), (pdbd, "Pied de berge D"), (hdbd, "Haut de berge D"),
        (lmd, "Bout lit majeur D"), (raccord_d, "Raccord terrain D"),
    ):
        if point is not None:
            point.label = label

    points = [hdbg, pdbg, banq1, fdlg, fdld, banq2, pdbd, hdbd]
    if lmg is not None:
        points.insert(0, lmg)
    if lmd is not None:
        points.append(lmd)
    if raccord_g is not None:
        points.insert(0, raccord_g)
    if raccord_d is not None:
        points.append(raccord_d)

    # Découpage hydraulique par 4 verticales, aux hauts du lit d'étiage (banquettes) et aux
    # hauts de berge : chaque partie est calculée comme un lit à part. Une partie sans
    # terrain (pas de lit majeur ni de raccord) ou hors d'eau est ignorée par le calcul.
    subsections = [
        Subsection("Lit majeur G", -math.inf, hdbg.x, floodplain=True),
        Subsection("Banquette + berge G", hdbg.x, banq1.x),
        Subsection("Lit d'étiage", banq1.x, banq2.x),
        Subsection("Banquette + berge D", banq2.x, hdbd.x),
        Subsection("Lit majeur D", hdbd.x, math.inf, floodplain=True),
    ]
    return CrossSection(name=name, points=points, subsections=subsections)
