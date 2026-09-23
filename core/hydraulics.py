# core/hydraulics.py
import math
from typing import Tuple, Optional
from core.models import Point, CrossSection

def get_water_intersections(section: CrossSection, water_z: float) -> Tuple[Optional[float], Optional[float]]:
    """Trouve automatiquement les abscisses (X) d'intersection entre la ligne d'eau et le terrain.

    L'intervalle testé par segment est fermé des deux côtés ([min, max], et non [min, max[)
    pour que le cas où le niveau d'eau touche exactement le point le plus haut du profil
    (typiquement en fin de dichotomie, cf. find_water_level_for_discharge, quand le débit
    cible dépasse la capacité du profil) compte bien comme une intersection, au lieu d'un
    débit nul. Les intersections trouvées sont dédupliquées par abscisse : sans ça, un
    niveau d'eau touchant exactement un sommet intérieur partagé par deux segments (ex :
    le haut d'une banquette) compterait deux fois le même point."""
    pts = section.points
    intersections = []

    for i in range(len(pts) - 1):
        p1, p2 = pts[i], pts[i + 1]
        if min(p1.z, p2.z) <= water_z <= max(p1.z, p2.z):
            if p1.z == p2.z:
                # Segment horizontal exactement à la cote d'eau : les deux extrémités sont
                # valides (et l'interpolation ci-dessous diviserait par zéro).
                intersections.append(p1.x)
                intersections.append(p2.x)
            else:
                x_int = p1.x + (water_z - p1.z) * (p2.x - p1.x) / (p2.z - p1.z)
                intersections.append(x_int)

    unique_x = sorted(set(round(x, 9) for x in intersections))
    if len(unique_x) >= 2:
        return unique_x[0], unique_x[-1]
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


def resolve_hydraulic_result(
    section: CrossSection, calc_mode: str,
    q_target: float, h_eau: float, z_ref: float, slope: float, ks: float,
) -> dict:
    """Point d'entrée unique pour obtenir le résultat hydraulique à afficher, quel que soit
    le mode de dimensionnement :
    - calc_mode == 'H_FROM_Q' ("Imposer Q") : résout le tirant d'eau pour le débit cible.
    - sinon ('Q_FROM_H', "Imposer H") : calcule directement pour le tirant d'eau saisi.

    Fonction pure et sans état : chaque appel recalcule entièrement à partir des arguments
    reçus (section, mode et grandeur imposée). Rien n'est mémorisé d'un appel à l'autre, donc
    changer de mode, de profil (section différente) ou de valeur imposée ne peut jamais faire
    réapparaître un résultat d'un appel précédent — le seul moyen d'obtenir un résultat
    obsolète serait d'appeler cette fonction avec des arguments eux-mêmes obsolètes."""
    if calc_mode == 'H_FROM_Q':
        return find_water_level_for_discharge(section, q_target, slope, ks)
    return compute_hydraulic_params(section, z_ref + h_eau, slope, ks)