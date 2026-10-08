# core/hydraulics.py
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from core.models import Point, CrossSection, Subsection

# Limites (X gauche, X droite) de la zone dans laquelle on fait le calcul, ou None pour
# tout le profil. Chaque limite agit comme une paroi verticale fictive : l'eau ne s'étend
# pas au-delà, et la paroi ne compte pas dans le périmètre mouillé (interface d'eau, pas
# un frottement sur le terrain). Une limite peut être infinie (-inf / +inf) : le profil
# n'est alors borné de ce côté que par son extrémité naturelle (ex. "bras gauche seul" =
# (-inf, X de séparation des bras)).
Bounds = Optional[Tuple[float, float]]

# Écart de cote (m) en dessous duquel l'eau est considérée exactement au niveau d'un point
# (arrondis de calcul flottant), pour la fermeture des lits et la détection de débordement.
_Z_TOLERANCE = 1e-9

# Précision de la recherche de cote en mode "Imposer Q" (cf. find_water_level_for_discharge) :
# débit à 0.1 % du débit cible et cote à 1 mm près. Relative, la tolérance sur le débit vaut
# aussi bien pour un petit débit (0.03 m³/s) que pour une crue (plusieurs centaines de m³/s).
Q_RELATIVE_TOLERANCE = 1e-3
_SOLVER_Z_TOLERANCE = 1e-3


def target_discharge_reached(q: float, target_q: float) -> bool:
    """Le débit obtenu atteint-il le débit cible, à Q_RELATIVE_TOLERANCE près ? Règle unique,
    partagée par la recherche de cote et par l'affichage (débit "Saisi", avertissement
    "débit cible non atteint"), pour qu'ils ne se contredisent jamais."""
    return abs(q - target_q) <= Q_RELATIVE_TOLERANCE * abs(target_q)


def _empty_result(water_z: Optional[float], overflow_sides: Optional[List[str]] = None,
                  water_intervals: Optional[List[Tuple[float, float]]] = None) -> dict:
    return {"S": 0, "P": 0, "Rh": 0, "V": 0, "Q": 0, "water_z": water_z,
            "x_left": None, "x_right": None, "wet_intervals": [], "bed_discharges": [],
            "subsections": [], "overflow_sides": overflow_sides or [],
            "water_intervals": water_intervals or []}


def free_end_levels(section: CrossSection, bounds: Bounds = None) -> Dict[str, float]:
    """Cotes des extrémités "libres" du profil calculé, c'est-à-dire non fermées par une
    paroi de zone d'écoulement : {"left": z, "right": z} (un côté fermé par une paroi est
    absent). Au-dessus de l'une d'elles, l'eau déborderait hors du profil levé : ce
    débordement n'est pas modélisé, le lit qui touche cette extrémité est ignoré (cf.
    get_wet_beds)."""
    points, wall_left, wall_right = clip_to_bounds(section.points, bounds)
    if len(points) < 2:
        return {}
    ends = {}
    if not wall_left:
        ends["left"] = points[0].z
    if not wall_right:
        ends["right"] = points[-1].z
    return ends


def overflow_level(section: CrossSection, bounds: Bounds = None) -> Optional[float]:
    """Cote la plus haute atteignable sans débordement (la plus basse des extrémités
    libres), ou None si les deux côtés sont fermés par une paroi."""
    ends = free_end_levels(section, bounds)
    return min(ends.values()) if ends else None


def suggest_arm_split(points: List[Point]) -> Optional[Point]:
    """Point haut qui sépare le plus nettement deux bras (ex. la crête d'une île), ou None
    si le profil n'a qu'un seul creux. Pour chaque point intérieur, on mesure de combien il
    domine le fond du bras le MOINS profond de part et d'autre (min(crête - fond gauche,
    crête - fond droit)) : le meilleur séparateur est celui qui maximise cette hauteur. Un
    point de berge extérieure ne sépare rien (un seul côté a un fond plus bas)."""
    best, best_height = None, 0.0
    for k in range(1, len(points) - 1):
        left_bottom = min(p.z for p in points[:k])
        right_bottom = min(p.z for p in points[k + 1:])
        height = min(points[k].z - left_bottom, points[k].z - right_bottom)
        if height > best_height:
            best, best_height = points[k], height
    return best


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


def get_wet_beds(section: CrossSection, water_z: float, bounds: Bounds = None,
                 keep_overflowing: bool = False) -> List[List[Point]]:
    """Découpe la section mouillée en lits séparés : chaque lit est la portion de terrain
    (polyligne) située sous la cote d'eau entre deux points où le terrain la coupe. Un
    terrain qui émerge entre deux creux (ex. un merlon entre deux lits) sépare donc deux
    lits distincts, au lieu d'être compté comme mouillé (ancienne approche : tout ce qui
    se trouvait entre la première et la dernière intersection).

    - Un palier horizontal exactement à la cote d'eau a une profondeur nulle : il n'est pas
      mouillé et ne prolonge pas le lit.
    - Un lit qui touche une extrémité naturelle du profil sans que le terrain ne remonte
      jusqu'à la cote d'eau déborde hors du profil levé : il est ignoré, comme avant
      (le débordement n'est pas modélisé), sauf avec `keep_overflowing` (affichage de la
      ligne d'eau, qui s'étend alors jusqu'à l'extrémité du profil).
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
    # Une extrémité à la cote d'eau, aux arrondis près (ex. 99.4 + 3.4 = 102.80000000000001),
    # ferme le lit : sinon une eau "exactement à ras" serait comptée comme débordante.
    if keep_overflowing:
        return beds
    return [
        bed for bed in beds
        if (bed[0].z >= water_z - _Z_TOLERANCE or wall_left)
        and (bed[-1].z >= water_z - _Z_TOLERANCE or wall_right)
    ]


@dataclass
class _WetPart:
    """Portion mouillée d'un lit, comprise dans une seule partie de la section (subsection
    None : section non découpée, le lit entier). C'est l'entrée de la méthode de calcul du
    débit (cf. _divided_channel_discharges)."""
    subsection: Optional[Subsection]
    bed_index: int
    area: float
    perimeter: float
    ks: float


def _split_bed(bed: List[Point], subsections: List[Subsection]) -> List[Tuple[Optional[Subsection], List[Point]]]:
    """Découpe un lit mouillé par les verticales qui séparent les parties de la section :
    une portion de terrain par partie traversée, le terrain étant interpolé sur chaque
    verticale. Sans découpage, le lit reste d'un seul bloc."""
    if not subsections:
        return [(None, bed)]
    pieces = []
    for subsection in subsections:
        piece, _, _ = clip_to_bounds(bed, (subsection.x_min, subsection.x_max))
        if len(piece) >= 2:
            pieces.append((subsection, piece))
    return pieces


def _wet_area_and_perimeter(points: List[Point], water_z: float) -> Tuple[float, float]:
    """Surface sous la cote d'eau (méthode des trapèzes) et longueur de terrain mouillé. Les
    verticales qui bornent la portion (découpage, limites de zone) ne sont pas du terrain :
    elles ne comptent pas dans le périmètre."""
    area = perimeter = 0.0
    for p1, p2 in zip(points, points[1:]):
        area += (p2.x - p1.x) * ((water_z - p1.z) + (water_z - p2.z)) / 2.0
        perimeter += math.hypot(p2.x - p1.x, p2.z - p1.z)
    return area, perimeter


def _divided_channel_discharges(parts: List[_WetPart], slope: float) -> List[float]:
    """Méthode des lits séparés : chaque partie est un canal de Manning-Strickler
    indépendant (sa surface, son périmètre, son Ks), le débit total est la somme. La méthode
    de Debord, qui tient compte des échanges entre lit mineur et lit majeur, s'ajoutera à
    côté avec la même entrée (toutes les parties à la fois)."""
    return [part.ks * part.area * math.pow(part.area / part.perimeter, 2 / 3) * math.sqrt(slope)
            for part in parts]


def compute_hydraulic_params(section: CrossSection, water_z: float, slope: float, ks: float,
                             bounds: Bounds = None) -> dict:
    """Calcule S (surface), P (périmètre mouillé), Rh, vitesse et débit pour une cote d'eau
    donnée, sur tous les lits mouillés (cf. get_wet_beds) entre les limites `bounds`.

    Avec plusieurs lits séparés, le débit est la somme des débits de Manning-Strickler de
    chaque lit (somme des débitances), chacun avec son propre rayon hydraulique : un seul
    Rh global sous-estimerait le lit principal en le moyennant avec un petit lit voisin.
    Une section découpée (section.subsections, profil projet) est calculée de même partie
    par partie : sans cela, l'eau qui s'étale sur une banquette ou un lit majeur allonge
    brutalement le périmètre et le débit chute alors que l'eau monte.
    V est la vitesse moyenne Q / S, Rh le rapport global S / P (pour information).
    `wet_intervals` liste les (x_gauche, x_droite) de chaque lit, pour l'affichage, et
    `bed_discharges` le débit de chacun (même ordre) ; x_left et x_right en sont les bornes
    extrêmes. `subsections` détaille chaque partie mouillée de la section découpée (nom,
    S, P, Q, V), de gauche à droite. `overflow_sides` liste les extrémités libres ("left",
    "right") que la cote d'eau dépasse : l'eau y déborderait hors du profil, le lit concerné
    est ignoré (pas de modélisation du débordement) et l'appelant doit le signaler.
    `water_intervals` liste, pour l'affichage de la ligne d'eau, tous les lits en eau, y
    compris ceux qui débordent (étendus jusqu'à l'extrémité du profil) : la ligne reste
    visible en cas de débordement."""
    overflow_sides = [side for side, z in free_end_levels(section, bounds).items()
                      if water_z > z + _Z_TOLERANCE]
    water_intervals = [(bed[0].x, bed[-1].x)
                       for bed in get_wet_beds(section, water_z, bounds, keep_overflowing=True)]
    if slope <= 0 or ks <= 0:
        return _empty_result(water_z, overflow_sides, water_intervals)

    beds = get_wet_beds(section, water_z, bounds)

    # Un seul Ks pour toutes les parties pour l'instant : c'est ici que le lit majeur
    # (Subsection.floodplain) recevra son propre Ks.
    parts = []
    for index, bed in enumerate(beds):
        for subsection, piece in _split_bed(bed, section.subsections):
            area, perimeter = _wet_area_and_perimeter(piece, water_z)
            if area > 0 and perimeter > 0:
                parts.append(_WetPart(subsection, index, area, perimeter, ks))
    discharges = _divided_channel_discharges(parts, slope)

    s_total = sum(part.area for part in parts)
    p_total = sum(part.perimeter for part in parts)
    q_total = sum(discharges)
    if s_total <= 0 or p_total <= 0:
        return _empty_result(water_z, overflow_sides, water_intervals)

    subsection_results = []
    for subsection in section.subsections:
        wet = [(part, q) for part, q in zip(parts, discharges) if part.subsection is subsection]
        if wet:
            area = sum(part.area for part, _ in wet)
            q = sum(q for _, q in wet)
            subsection_results.append({"name": subsection.name, "S": area,
                                       "P": sum(part.perimeter for part, _ in wet),
                                       "Q": q, "V": q / area})

    return {
        "S": s_total, "P": p_total, "Rh": s_total / p_total, "V": q_total / s_total, "Q": q_total,
        "water_z": water_z, "x_left": beds[0][0].x, "x_right": beds[-1][-1].x,
        "wet_intervals": [(bed[0].x, bed[-1].x) for bed in beds],
        "bed_discharges": [sum(q for part, q in zip(parts, discharges) if part.bed_index == index)
                           for index in range(len(beds))],
        "subsections": subsection_results,
        "overflow_sides": overflow_sides,
        "water_intervals": water_intervals,
    }


def subsection_dividers(section: CrossSection, bounds: Bounds = None) -> List[Tuple[float, float]]:
    """Verticales de découpage de la section à tracer, (X, cote du terrain sur la
    verticale) : celles qui tombent à l'intérieur du profil et de la zone d'écoulement (une
    verticale au bout du profil, ex. au haut de berge sans lit majeur, ne sépare rien)."""
    points, _, _ = clip_to_bounds(section.points, bounds)
    if len(points) < 2:
        return []
    cuts = {sub.x_max for sub in section.subsections} | {sub.x_min for sub in section.subsections}
    return [(x, _interpolate_z(points, x)) for x in sorted(cuts) if points[0].x < x < points[-1].x]


def find_water_level_for_discharge(section: CrossSection, target_q: float, slope: float, ks: float,
                                   bounds: Bounds = None) -> dict:
    """Trouve la cote d'eau correspondant au débit cible (par dichotomie), entre le point
    le plus bas du terrain compris dans les limites `bounds` et la cote la plus haute
    atteignable sans débordement (cf. overflow_level ; le point le plus haut si les deux
    côtés sont fermés par une paroi). Au-delà, le lit qui déborde serait ignoré et le débit
    retomberait : un débit cible trop fort laisse donc l'eau à ce niveau maximal, avec la
    capacité correspondante (débit cible non atteint, signalé par l'appelant).

    La dichotomie continue jusqu'à ce que le débit soit atteint (cf. target_discharge_reached)
    ET que la cote soit encadrée à 1 mm près : à petit débit, 1 mm de cote change beaucoup
    le débit ; à grand débit, 0.1 % du débit peut représenter plus d'1 mm de cote."""
    points, _, _ = clip_to_bounds(section.points, bounds)
    if not points:
        return _empty_result(None)
    z_min = min(p.z for p in points)
    if target_q <= 0:  # débit nul : pas d'eau (une tolérance relative à 0 serait inatteignable)
        return compute_hydraulic_params(section, z_min, slope, ks, bounds)
    z_max = max(p.z for p in points)
    level = overflow_level(section, bounds)
    if level is not None:
        z_max = min(z_max, level)

    low, high = z_min, z_max

    for _ in range(100):  # bien au-delà de la précision des flottants
        mid = (low + high) / 2.0
        res = compute_hydraulic_params(section, mid, slope, ks, bounds)

        if res["Q"] < target_q:
            low = mid
        else:
            high = mid
        # mid est une borne de l'intervalle [low, high] qui encadre la cote cherchée.
        if high - low <= _SOLVER_Z_TOLERANCE and target_discharge_reached(res["Q"], target_q):
            return res

    # Si la crue est immense, elle s'arrête au niveau maximal sans débordement
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
