from dataclasses import dataclass, field
from typing import List, Tuple
import pandas as pd

@dataclass
class Point:
    """Un point topographique (X = distance cumulée, Z = altitude)."""
    x: float
    z: float

@dataclass
class CrossSection:
    """Un profil en travers : un nom + une liste de points ordonnés par X."""
    name: str
    points: List[Point] = field(default_factory=list)

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

    # --- Berges ---
    bank_slope_left: float = 1.8
    bank_width_left: float = 3.0
    delete_point_left_bank: bool = False

    bank_slope_right: float = 2.5
    bank_width_right: float = 3.0
    delete_point_right_bank: bool = False

    # --- Lit majeur ---
    floodplain_slope_left: float = 10000.0
    floodplain_smooth_left: bool = False
    floodplain_slope_right: float = 10000.0
    floodplain_smooth_right: bool = False
    x_end_profile_left: float = 0.1
    x_end_profile_right: float = 11.0

    # --- Interruption du calcul de terrassements ---
    x_end_equals_profile_width: bool = False
    x_end_rd: float = 11.0

    # --- Granulométrie ---
    d50: float = 0.004

    # --- Ancrage sur le terrain ---
    anchor_x: float = 3.78
    anchor_z: float = 47.40

    # --- Position du lit ---
    keep_existing_slope: bool = False

    # --- Hydraulique ---
    calc_mode: str = "Existant"
    h_eau: float = 0.4225
    ks_pro: float = 25.0
    x_eau_gauche: float = 3.78
    x_eau_droite: float = 5.78


def dataframe_to_points(df: pd.DataFrame) -> List[Point]:
    """Convertit un tableau (2 colonnes : X, Z) en liste de Point."""
    if df is None or df.empty:
        return []
    clean = df.dropna(how="any")
    if clean.empty:
        return []
    
    x_col, z_col = clean.columns[0], clean.columns[1]
    clean = clean.sort_values(by=x_col)
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