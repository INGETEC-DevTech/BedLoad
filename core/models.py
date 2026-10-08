from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import pandas as pd

@dataclass
class Point:
    """Un point topographique (X = distance cumulée, Z = altitude). `label` nomme le point
    quand il a un rôle géométrique (ex. "Haut de berge G" sur le profil projet) ; il
    n'entre pas dans la comparaison de deux points."""
    x: float
    z: float
    label: str = field(default="", compare=False)

@dataclass
class Subsection:
    """Partie de la section comprise entre deux verticales de découpage (X de x_min à x_max,
    infinis aux deux bouts), calculée comme un lit à part (cf. core.hydraulics). `floodplain`
    distingue le lit majeur du lit mineur : c'est sur lui que s'appuieront un Ks propre au
    lit majeur et la méthode de Debord."""
    name: str
    x_min: float
    x_max: float
    floodplain: bool = False

@dataclass
class CrossSection:
    """Un profil en travers : un nom + une liste de points ordonnés par X. `subsections`
    découpe la section pour le calcul hydraulique (profil projet : lit d'étiage, banquettes
    et berges, lits majeurs) ; vide, chaque lit mouillé est calculé d'un seul bloc."""
    name: str
    points: List[Point] = field(default_factory=list)
    subsections: List[Subsection] = field(default_factory=list)

    def to_arrays(self) -> Tuple[List[float], List[float]]:
        """Retourne (liste des X, liste des Z), pratique pour tracer un graphique."""
        xs = [p.x for p in self.points]
        zs = [p.z for p in self.points]
        return xs, zs

@dataclass
class ProjectParameters:
    """Paramètres du profil projet, alignés sur la feuille CT de l'Excel."""
    # --- Lit trapézoïdal ---
    bed_width: float = 2.0
    bed_depth: float = 0.27
    bed_side_slope: float = 2.0

    # --- Banquettes ---
    berm_width_left: float = 0.001
    berm_width_right: float = 0.8
    berm_slope_left: float = 0.0
    berm_slope_right: float = 0.0

    # --- Berges ---
    bank_slope_left: float = 1.8
    bank_width_left: float = 3.0

    bank_slope_right: float = 2.5
    bank_width_right: float = 3.0

    # --- Lit majeur (segment optionnel après la berge ; largeur = 0 -> désactivé,
    # comportement inchangé) ---
    floodplain_width_left: float = 0.0
    floodplain_width_right: float = 0.0
    floodplain_slope_left: float = 0.0
    floodplain_slope_right: float = 0.0

    # --- Ancrage sur le terrain ---
    anchor_x: float = 3.78
    anchor_z: float = 47.40

    # --- Géométrie (Nouveau) ---
    slope: float = 0.005
    # Pente calculée à partir des points durs du projet ("computed"), ou saisie à la main
    # ("imposed") : cf. core.hard_points.
    slope_mode: str = "computed"
    
    # --- Hydraulique ---
    calc_mode: str = "Q_FROM_H"  # "Q_FROM_H" (Calculer Débit) ou "H_FROM_Q" (Calculer Hauteur)
    h_eau: float = 0.42
    q_target: float = 15.0
    ks_pro: float = 25.0
    # Rugosité (Strickler) du lit majeur : stockée pour un usage futur, pas encore
    # utilisée dans le calcul hydraulique (un seul paramètre pour les deux rives).
    floodplain_ks: float = 25.0
    # Zone d'écoulement du calcul hydraulique (cf. core.controller.flow_zone_bounds) :
    # - "all"       : tout le profil, l'eau remplit tous les bras qu'atteint la cote d'eau ;
    # - "left_arm"  : bras gauche seul (à gauche de hydro_arm_split_x) ;
    # - "right_arm" : bras droit seul (à droite de hydro_arm_split_x) ;
    # - "custom"    : terrain compris entre hydro_x_left et hydro_x_right.
    hydro_zone: str = "all"
    hydro_arm_split_x: float = 0.0
    hydro_x_left: float = 0.0
    hydro_x_right: float = 0.0

    # --- Raccords latéraux optionnels vers le profil existant ---
    # Choisis manuellement (valeur figée à la sélection) : prolongent la géométrie
    # au-delà du bout du lit majeur (ou, à défaut, du haut de berge). None de chaque côté
    # = comportement inchangé.
    connect_x_left: Optional[float] = None
    connect_z_left: Optional[float] = None
    connect_x_right: Optional[float] = None
    connect_z_right: Optional[float] = None


def _entered_right_to_left(xs: pd.Series) -> bool:
    """Le profil a-t-il été saisi de droite à gauche, c'est-à-dire avec des X globalement
    décroissants : plus de pas descendants que montants d'une ligne à la suivante ? Compter
    les pas, plutôt que comparer le premier et le dernier X, ne se laisse pas tromper par un
    point de plateau gauche ajouté en fin de tableau."""
    steps = pd.to_numeric(xs, errors="coerce").diff().dropna()
    return (steps < 0).sum() > (steps > 0).sum()


def dataframe_to_points(df: pd.DataFrame) -> List[Point]:
    """Convertit un tableau (2 colonnes : X, Z) en liste de Point, triés par X. À X égal
    (berge verticale), l'ordre de saisie est conservé, dans le sens du levé : un profil
    saisi de droite à gauche est d'abord retourné (cf. _entered_right_to_left)."""
    if df is None or df.empty:
        return []
    clean = df.dropna(how="any")
    if clean.empty:
        return []

    x_col, z_col = clean.columns[0], clean.columns[1]
    if _entered_right_to_left(clean[x_col]):
        clean = clean.iloc[::-1]
    # Tri stable : le tri par défaut (quicksort) peut inverser deux points de même X, et
    # donc retourner une berge verticale.
    clean = clean.sort_values(by=x_col, kind="stable")
    points: List[Point] = []
    
    for _, row in clean.iterrows():
        try:
            points.append(Point(x=float(row[x_col]), z=float(row[z_col])))
        except (TypeError, ValueError):
            continue
    return points

def points_to_dataframe(points: List[Point], x_label: str = "X (m)", z_label: str = "Z (m NGF)") -> pd.DataFrame:
    """Fonction inverse de dataframe_to_points, utile pour l'affichage en table."""
    return pd.DataFrame({x_label: [p.x for p in points], z_label: [p.z for p in points]})