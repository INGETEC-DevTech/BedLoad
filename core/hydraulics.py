# core/hydraulics.py
import math
from typing import List, Optional, Tuple
from core.models import Point, CrossSection

# Limites (X gauche, X droite) du lit dans lequel on fait le calcul, ou None pour tout le
# profil. Chaque limite agit comme une paroi verticale fictive : l'eau ne s'étend pas
# au-delà, et la paroi ne compte pas dans le périmètre mouillé (interface d'eau, pas un
# frottement sur le terrain).
Bounds = Optional[Tuple[float, float]]


def _empty_result(water_z: Optional[float]) -> dict:
    return {"S": 0, "P": 0, "Rh": 0, "V": 0, "Q": 0, "water_z": water_z,
            "x_left": None, "x_right": None, "wet_intervals": []}


def _interpolate_z(points: List[Point], x: float) -> float:
    for p1, p2 in zip(points, points[1:]):
        if p1.x <= x <= p2.x:
            if p2.x == p1.x:
                return p1.z
            return p1.z + (x - p1.x) * (p2.z - p1.z) / (p2.x - p1.x)
    raise ValueError(f"x={x} hors du profil")


def clip_to_bounds(points: List[Point], bounds: Bounds) -> Tuple[List[Point], bool, bool]:
    """Restreint le profil aux limites du lit de calcul, en interpolant le terrain sur
    chaque limite. Retourne (points, paroi_gauche, paroi_droite) : une limite ne fait paroi
    que si elle tombe à l'intérieur du profil (au-delà de ses extrémités, elle ne coupe
    rien et l'extrémité naturelle du profil reste la borne). Liste vide si les limites ne
    recouvrent pas le profil."""
    if bounds is None or not points:
        return list(points), False, False
    x_min, x_max = bounds
    if x_min >= points[-1].x or x_max <= points[0].x:
        return [], False, False

    wall_left = x_min > points[0].x
    wall_right = x_max < points[-1].x
    clipped = [p for p in points
               if (not wall_left or p.x > x_min) and (not wall_right or p.x < x_max)]
    if wall_left:
        clipped.insert(0, Point(x=x_min, z=_interpolate_z(points, x_min)))
    if wall_right:
        clipped.append(Point(x=x_max, z=_interpolate_z(points, x_max)))
    return clipped, wall_left, wall_right


def get_wet_beds(section: CrossSection, water_z: float, bounds: Bounds = None) -> List[List[Point]]:
    """Découpe la section mouillée en lits séparés : chaque lit est la portion de terrain
    (polyligne) située sous la cote d'eau entre deux points où le terrain la coupe. Un
    terrain qui émerge entre deux creux (ex. un merlon entre deux lits) sépare donc deux
    lits distincts, au lieu d'être compté comme mouillé (ancienne approche : tout ce qui
    se trouvait entre la première et la dernière intersection).

    - Un palier horizontal exactement à la cote d'eau a une profondeur nulle : il n'est pas
      mouillé et ne prolonge pas le lit.
    - Un lit qui touche une extrémité naturelle du profil sans que le terrain ne remonte
      jusqu'à la cote d'eau déborde hors du profil levé : il est ignoré, comme avant
      (le débordement n'est pas modélisé).
    - Un lit qui s'arrête sur une limite du lit de calcul (`bounds`) est fermé par la
      paroi fictive de cette limite."""
    points, wall_left, wall_right = clip_to_bounds(section.points, bounds)
    if len(points) < 2:
        return []

    # Insère les points où le terrain coupe la cote d'eau.
    refined = [points[0]]
    for p1, p2 in zip(points, points[1:]):
        if (p1.z - water_z) * (p2.z - water_z) < 0:
            x = p1.x + (water_z - p1.z) * (p2.x - p1.x) / (p2.z - p1.z)
            refined.append(Point(x=x, z=water_z))
        refined.append(p2)

    beds, current = [], []
    for p1, p2 in zip(refined, refined[1:]):
        is_wet = (p1.z <= water_z and p2.z <= water_z
                  and not (p1.z == water_z and p2.z == water_z))
        if is_wet:
            if not current:
                current = [p1]
            current.append(p2)
        elif current:
            beds.append(current)
            current = []
    if current:
        beds.append(current)

    # Un lit dont une extrémité est sous l'eau commence/finit forcément au bord du profil
    # (sinon un point de coupure aurait été inséré) : fermé par une paroi, ou débordant.
    return [
        bed for bed in beds
        if (bed[0].z == water_z or wall_left) and (bed[-1].z == water_z or wall_right)
    ]


def compute_hydraulic_params(section: CrossSection, water_z: float, slope: float, ks: float,
                             bounds: Bounds = None) -> dict:
    """Calcule S (surface), P (périmètre mouillé), Rh, vitesse et débit pour une cote d'eau
    donnée, sur tous les lits mouillés (cf. get_wet_beds) entre les limites `bounds`.

    Avec plusieurs lits séparés, le débit est la somme des débits de Manning-Strickler de
    chaque lit (somme des débitances), chacun avec son propre rayon hydraulique : un seul
    Rh global sous-estimerait le lit principal en le moyennant avec un petit lit voisin.
    V est la vitesse moyenne Q / S, Rh le rapport global S / P (pour information).
    `wet_intervals` liste les (x_gauche, x_droite) de chaque lit, pour l'affichage ; x_left
    et x_right en sont les bornes extrêmes."""
    if slope <= 0 or ks <= 0:
        return _empty_result(water_z)

    beds = get_wet_beds(section, water_z, bounds)

    s_total, p_total, q_total = 0.0, 0.0, 0.0
    for bed in beds:
        s = p = 0.0
        # Intégration par la méthode des trapèzes
        for p1, p2 in zip(bed, bed[1:]):
            s += (p2.x - p1.x) * ((water_z - p1.z) + (water_z - p2.z)) / 2.0
            p += math.hypot(p2.x - p1.x, p2.z - p1.z)
        if s > 0 and p > 0:
            q_total += ks * s * math.pow(s / p, 2 / 3) * math.sqrt(slope)
        s_total += s
        p_total += p

    if s_total <= 0 or p_total <= 0:
        return _empty_result(water_z)

    return {
        "S": s_total, "P": p_total, "Rh": s_total / p_total, "V": q_total / s_total, "Q": q_total,
        "water_z": water_z, "x_left": beds[0][0].x, "x_right": beds[-1][-1].x,
        "wet_intervals": [(bed[0].x, bed[-1].x) for bed in beds],
    }


def find_water_level_for_discharge(section: CrossSection, target_q: float, slope: float, ks: float,
                                   bounds: Bounds = None) -> dict:
    """Trouve la cote d'eau correspondant au débit cible (par dichotomie), entre le point
    le plus bas et le point le plus haut du terrain compris dans les limites `bounds`."""
    points, _, _ = clip_to_bounds(section.points, bounds)
    if not points:
        return _empty_result(None)
    z_min = min(p.z for p in points)
    z_max = max(p.z for p in points)

    low, high = z_min, z_max

    for _ in range(100):  # 100 itérations suffisent pour une précision millimétrique
        mid = (low + high) / 2.0
        res = compute_hydraulic_params(section, mid, slope, ks, bounds)

        if abs(res["Q"] - target_q) < 0.01:
            return res
        elif res["Q"] < target_q:
            low = mid
        else:
            high = mid

    # Si la crue est immense, elle s'arrête au sommet des berges géométriques
    return compute_hydraulic_params(section, high, slope, ks, bounds)


def resolve_hydraulic_result(
    section: CrossSection, calc_mode: str,
    q_target: float, h_eau: float, z_ref: float, slope: float, ks: float,
    bounds: Bounds = None,
) -> dict:
    """Point d'entrée unique pour obtenir le résultat hydraulique à afficher, quel que soit
    le mode de dimensionnement :
    - calc_mode == 'H_FROM_Q' ("Imposer Q") : résout le tirant d'eau pour le débit cible.
    - sinon ('Q_FROM_H', "Imposer H") : calcule directement pour le tirant d'eau saisi.
    `bounds` restreint le calcul au lit compris entre deux X (cf. Bounds).

    Fonction pure et sans état : chaque appel recalcule entièrement à partir des arguments
    reçus (section, mode et grandeur imposée). Rien n'est mémorisé d'un appel à l'autre, donc
    changer de mode, de profil (section différente) ou de valeur imposée ne peut jamais faire
    réapparaître un résultat d'un appel précédent — le seul moyen d'obtenir un résultat
    obsolète serait d'appeler cette fonction avec des arguments eux-mêmes obsolètes."""
    if calc_mode == 'H_FROM_Q':
        return find_water_level_for_discharge(section, q_target, slope, ks, bounds)
    return compute_hydraulic_params(section, z_ref + h_eau, slope, ks, bounds)
