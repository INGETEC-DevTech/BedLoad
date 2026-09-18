# core/hydraulics.py
import math
from typing import Tuple, Optional
from core.models import Point, CrossSection

def get_water_intersections(section: CrossSection, water_z: float) -> Tuple[Optional[float], Optional[float]]:
    """Trouve automatiquement les abscisses (X) d'intersection entre la ligne d'eau et le terrain."""
    pts = section.points
    intersections = []
    
    for i in range(len(pts) - 1):
        p1, p2 = pts[i], pts[i+1]
        # Vérifie si le segment traverse la ligne d'eau
        if min(p1.z, p2.z) <= water_z < max(p1.z, p2.z):
            # Interpolation linéaire pour trouver le X exact
            x_int = p1.x + (water_z - p1.z) * (p2.x - p1.x) / (p2.z - p1.z)
            intersections.append(x_int)
            
    if len(intersections) >= 2:
        return min(intersections), max(intersections)
    return None, None

def compute_hydraulic_params(section: CrossSection, water_z: float, slope: float, ks: float) -> dict:
    """Calcule S (Surface), P (Périmètre), Rh, Vitesse et Débit pour une cote d'eau donnée."""
    if slope <= 0 or ks <= 0:
        return {"S": 0, "P": 0, "Rh": 0, "V": 0, "Q": 0, "water_z": water_z, "x_left": None, "x_right": None}
        
    x_left, x_right = get_water_intersections(section, water_z)
    if x_left is None or x_right is None:
         return {"S": 0, "P": 0, "Rh": 0, "V": 0, "Q": 0, "water_z": water_z, "x_left": None, "x_right": None}
         
    # Construction du polygone immergé
    w_points = [Point(x=x_left, z=water_z)]
    for p in section.points:
        if x_left < p.x < x_right:
            w_points.append(Point(x=p.x, z=min(p.z, water_z)))
    w_points.append(Point(x=x_right, z=water_z))
    
    s = 0.0
    p = 0.0
    
    # Intégration par la méthode des trapèzes
    for i in range(len(w_points) - 1):
        p1, p2 = w_points[i], w_points[i+1]
        h1 = water_z - p1.z
        h2 = water_z - p2.z
        s += (p2.x - p1.x) * (h1 + h2) / 2.0
        p += math.sqrt((p2.x - p1.x)**2 + (p2.z - p1.z)**2)
        
    if p == 0:
        return {"S": 0, "P": 0, "Rh": 0, "V": 0, "Q": 0, "water_z": water_z, "x_left": None, "x_right": None}
        
    rh = s / p
    v = ks * math.pow(rh, 2/3) * math.sqrt(slope)
    q = v * s
    
    return {"S": s, "P": p, "Rh": rh, "V": v, "Q": q, "water_z": water_z, "x_left": x_left, "x_right": x_right}

def find_water_level_for_discharge(section: CrossSection, target_q: float, slope: float, ks: float) -> dict:
    """Trouve la cote d'eau correspondant au débit cible (par dichotomie)."""
    z_min = min(p.z for p in section.points)
    z_max = max(p.z for p in section.points)
    
    low, high = z_min, z_max
    
    for _ in range(100):  # 100 itérations suffisent pour une précision millimétrique
        mid = (low + high) / 2.0
        res = compute_hydraulic_params(section, mid, slope, ks)
        
        if abs(res["Q"] - target_q) < 0.01:
            return res
        elif res["Q"] < target_q:
            low = mid
        else:
            high = mid
            
    # Si la crue est immense, elle s'arrête au sommet des berges géométriques
    return compute_hydraulic_params(section, high, slope, ks)