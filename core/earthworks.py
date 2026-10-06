# core/earthworks.py
"""Surfaces de terrassement en coupe entre le profil existant et le profil projet.

- Déblai (à enlever) : le terrain existant est AU-DESSUS du profil projet.
- Remblai (à ajouter) : le profil projet est AU-DESSUS du terrain existant.

Le calcul porte sur l'emprise commune aux deux profils (de la plus grande des deux abscisses
de départ à la plus petite des deux abscisses de fin) : au-delà, l'un des deux profils n'est
pas défini. Il est découpé en zones, chacune délimitée par deux points où les profils se
croisent (ou par un bord de l'emprise). Les surfaces sont en m² (surface en coupe ; un
volume s'obtient en la multipliant par une longueur d'application)."""
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from core.models import CrossSection, Point

CUT = "cut"    # déblai
FILL = "fill"  # remblai

# Zones plus petites que ce seuil (m²) ignorées : simples arrondis là où les deux profils
# se confondent (ex. un point du projet posé exactement sur le terrain).
MIN_ZONE_AREA = 1e-4
# Écart vertical (m) en dessous duquel les deux profils sont considérés confondus.
_Z_TOLERANCE = 1e-9


@dataclass
class EarthworkZone:
    kind: str                 # CUT ou FILL
    name: str                 # "D1", "D2"... (déblais) ou "R1"... (remblais), de gauche à droite
    x_start: float
    x_end: float
    area: float               # m², toujours positive
    # Contour de la zone (pour la tracer) : le long du terrain existant de gauche à
    # droite, puis le long du profil projet de droite à gauche.
    outline_x: List[float] = field(default_factory=list)
    outline_z: List[float] = field(default_factory=list)


@dataclass
class EarthworksResult:
    zones: List[EarthworkZone]
    extent: Optional[Tuple[float, float]]   # emprise commune, None si les profils ne se recouvrent pas

    @property
    def cut_total(self) -> float:
        return sum(z.area for z in self.zones if z.kind == CUT)

    @property
    def fill_total(self) -> float:
        return sum(z.area for z in self.zones if z.kind == FILL)

    @property
    def balance(self) -> float:
        """Déblai - remblai : positif = excédent de matériaux, négatif = apport nécessaire."""
        return self.cut_total - self.fill_total


def _segment_line(points: List[Point], a: float, b: float) -> Callable[[float], float]:
    """Équation du segment du profil qui couvre [a, b] (a < b, sans point intermédiaire).
    Évaluer la droite du segment, plutôt que le profil en un point, lève l'ambiguïté des
    sauts verticaux (deux points de même X) : chaque côté du saut prend sa propre valeur."""
    for p1, p2 in zip(points, points[1:]):
        if p1.x <= a and b <= p2.x and p2.x > p1.x:
            slope = (p2.z - p1.z) / (p2.x - p1.x)
            return lambda x, p1=p1, slope=slope: p1.z + (x - p1.x) * slope
    raise ValueError(f"Aucun segment ne couvre [{a}, {b}]")


def compute_earthworks(existing: CrossSection, project: CrossSection) -> EarthworksResult:
    ex, pj = existing.points, project.points
    if len(ex) < 2 or len(pj) < 2:
        return EarthworksResult(zones=[], extent=None)

    lo = max(ex[0].x, pj[0].x)
    hi = min(ex[-1].x, pj[-1].x)
    if lo >= hi:
        return EarthworksResult(zones=[], extent=None)

    grid = sorted({p.x for p in ex + pj if lo <= p.x <= hi} | {lo, hi})

    # Morceaux élémentaires (a, b, z_existant(a), z_existant(b), z_projet(a), z_projet(b)),
    # coupés là où les deux profils se croisent : l'écart y garde un signe constant.
    pieces = []
    for a, b in zip(grid, grid[1:]):
        line_e, line_p = _segment_line(ex, a, b), _segment_line(pj, a, b)
        da, db = line_e(a) - line_p(a), line_e(b) - line_p(b)
        cuts = [a, b]
        if da * db < 0:
            cuts.insert(1, a + da * (b - a) / (da - db))
        for x0, x1 in zip(cuts, cuts[1:]):
            pieces.append((x0, x1, line_e(x0), line_e(x1), line_p(x0), line_p(x1)))

    # Regroupe les morceaux consécutifs de même signe en zones. Un morceau où les profils
    # sont confondus, ou un changement de signe (croisement, ou saut vertical d'un profil),
    # ferme la zone en cours.
    groups = []  # (kind, [morceaux])
    for piece in pieces:
        x0, x1, ze0, ze1, zp0, zp1 = piece
        diff = ((ze0 - zp0) + (ze1 - zp1)) / 2
        kind = CUT if diff > _Z_TOLERANCE else FILL if diff < -_Z_TOLERANCE else None
        if kind is None:
            groups.append((None, []))
        elif groups and groups[-1][0] == kind:
            groups[-1][1].append(piece)
        else:
            groups.append((kind, [piece]))

    zones: List[EarthworkZone] = []
    counters = {CUT: 0, FILL: 0}
    for kind, group in groups:
        if kind is None:
            continue
        area = sum(abs((x1 - x0) * ((ze0 - zp0) + (ze1 - zp1)) / 2)
                   for x0, x1, ze0, ze1, zp0, zp1 in group)
        if area < MIN_ZONE_AREA:
            continue
        along_existing = [pt for x0, x1, ze0, ze1, _, _ in group for pt in ((x0, ze0), (x1, ze1))]
        along_project = [pt for x0, x1, _, _, zp0, zp1 in group for pt in ((x0, zp0), (x1, zp1))]
        outline = along_existing + list(reversed(along_project)) + along_existing[:1]
        counters[kind] += 1
        zones.append(EarthworkZone(
            kind=kind, name=f"{'D' if kind == CUT else 'R'}{counters[kind]}",
            x_start=group[0][0], x_end=group[-1][1], area=area,
            outline_x=[x for x, _ in outline], outline_z=[z for _, z in outline],
        ))

    return EarthworksResult(zones=zones, extent=(lo, hi))
