# core/hard_points.py
"""Règles des points durs d'un projet et de la pente hydraulique qui en découle.

Un point dur est un repère de terrain fixe (nom, PK, Z). Un projet en a une liste libre ;
seuls les points COMPLETS (PK et Z renseignés) entrent dans les calculs, triés par PK. Un
point incomplet (hérité d'une ancienne version, où les champs pouvaient rester vides) est
conservé et affiché, mais ignoré.

- Le premier point complet est la référence "distance 0" des profils : un profil à la
  distance d est au PK (PK du premier point + d).
- La zone couverte va du premier au dernier point complet ; il en faut au moins deux.
- La pente d'un tronçon entre deux points voisins vaut (Z amont - Z aval) / (PK aval - PK
  amont), en m/m ; elle doit être strictement positive (ni contre-pente, ni pente nulle).
- La pente calculée d'un profil est celle du tronçon qui l'encadre ; s'il est exactement
  sur un point dur, celle du tronçon aval (sur le dernier point : le dernier tronçon).

Fonctions pures, sans base de données ni interface : la base (DatabaseManager) et la
sidebar s'appuient dessus pour valider les saisies et recalculer les pentes."""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Mode de pente d'un profil (clé "slope_mode" de ses paramètres).
SLOPE_COMPUTED = "computed"
SLOPE_IMPOSED = "imposed"

# Tolérance sur les PK (m) : comparaisons de position aux arrondis de saisie près.
_PK_TOLERANCE = 1e-6


@dataclass
class HardPoint:
    name: Optional[str]
    pk: Optional[float]
    z: Optional[float]
    id: Optional[int] = None  # identifiant en base, None pour un point pas encore enregistré

    @property
    def is_complete(self) -> bool:
        return self.pk is not None and self.z is not None

    @property
    def label(self) -> str:
        return self.name or (f"PK {self.pk:g}" if self.pk is not None else "point sans nom")

    @classmethod
    def from_dict(cls, data: Dict) -> "HardPoint":
        return cls(name=data.get("name"), pk=data.get("pk"), z=data.get("z"), id=data.get("id"))

    def to_dict(self) -> Dict:
        return {"id": self.id, "name": self.name, "pk": self.pk, "z": self.z}


@dataclass
class Segment:
    """Tronçon entre deux points durs complets voisins."""
    upstream: HardPoint
    downstream: HardPoint

    @property
    def slope(self) -> float:
        return (self.upstream.z - self.downstream.z) / (self.downstream.pk - self.upstream.pk)

    @property
    def label(self) -> str:
        return f"« {self.upstream.label} » → « {self.downstream.label} »"


def format_slope(slope: float) -> str:
    """Pente affichée partout dans la même unité que le champ de l'onglet Hydraulique."""
    return f"{slope:.4f} m/m"


def complete_points(points: Iterable[HardPoint]) -> List[HardPoint]:
    """Points complets, triés par PK."""
    return sorted((p for p in points if p.is_complete), key=lambda p: p.pk)


def reference_pk(points: Iterable[HardPoint]) -> Optional[float]:
    """PK de la référence "distance 0" (premier point complet), ou None."""
    complete = complete_points(points)
    return complete[0].pk if complete else None


def distance_zone(points: Iterable[HardPoint]) -> Optional[Tuple[float, float]]:
    """Plage de distances (par rapport au premier point) couverte par les points durs, ou
    None s'il y a moins de deux points complets (pas de zone : distances libres)."""
    complete = complete_points(points)
    if len(complete) < 2:
        return None
    return 0.0, complete[-1].pk - complete[0].pk


def segments(points: Iterable[HardPoint]) -> List[Segment]:
    complete = complete_points(points)
    return [Segment(a, b) for a, b in zip(complete, complete[1:])]


def segment_for_distance(points: Iterable[HardPoint], distance: float) -> Optional[Segment]:
    """Tronçon qui encadre un profil à `distance`, ou None (moins de deux points complets,
    ou profil hors de la zone couverte)."""
    zone = distance_zone(points)
    if zone is None or not (zone[0] - _PK_TOLERANCE <= distance <= zone[1] + _PK_TOLERANCE):
        return None
    all_segments = segments(points)
    pk = all_segments[0].upstream.pk + distance
    for segment in all_segments:
        if pk < segment.downstream.pk - _PK_TOLERANCE:
            return segment
    return all_segments[-1]  # exactement sur le dernier point : dernier tronçon


def computed_slope(points: Iterable[HardPoint], distance: float) -> Tuple[Optional[float], Optional[Segment], str]:
    """(pente, tronçon, explication) pour un profil à `distance`. La pente est None quand
    aucun calcul n'est possible, l'explication dit alors pourquoi."""
    points = list(points)
    if distance_zone(points) is None:
        return None, None, "le projet n'a pas au moins deux points durs complets (PK et Z)"
    # Points durs hérités d'une ancienne version (jamais validés à la saisie) : une
    # contre-pente, une pente nulle ou deux PK égaux rendent le calcul impossible.
    for segment in segments(points):
        if segment.downstream.pk - segment.upstream.pk <= _PK_TOLERANCE or segment.slope <= 0:
            return None, None, (f"les points durs {segment.label} présentent une contre-pente, "
                                "une pente nulle ou un même PK")
    segment = segment_for_distance(points, distance)
    if segment is None:
        zone = distance_zone(points)
        return None, None, (f"la distance du profil ({distance:g} m) est hors de la zone couverte "
                            f"par les points durs ({zone[0]:g} à {zone[1]:g} m)")
    return segment.slope, segment, ""


def validate_hard_points(points: Sequence[HardPoint], reference_id: Optional[int] = None,
                         profile_pks: Optional[Dict[str, float]] = None,
                         original_incomplete: Optional[Dict[int, Tuple]] = None) -> List[str]:
    """Erreurs (messages pour l'utilisateur) d'une liste de points durs saisie, ou [] :
    - PK et Z obligatoires, sauf pour un point incomplet hérité laissé tel quel
      (`original_incomplete` : id -> (nom, pk, z) d'origine des points incomplets en base) ;
    - pas de point en amont du premier point dur actuel (`reference_id`), qui reste la
      référence "distance 0" ;
    - deux points voisins : PK différents, et pente strictement positive (le Z doit baisser
      vers l'aval : ni contre-pente, ni pente nulle) ;
    - les profils existants (`profile_pks` : libellé -> PK absolu) doivent rester dans la
      zone couverte par les points durs."""
    errors = []
    original_incomplete = original_incomplete or {}

    for point in points:
        if point.is_complete:
            continue
        untouched = (point.id in original_incomplete
                     and original_incomplete[point.id] == (point.name, point.pk, point.z))
        if not untouched:
            errors.append(f"Point dur « {point.label} » : le PK et le Z sont obligatoires.")

    complete = complete_points(points)
    if reference_id is not None:
        reference = next((p for p in complete if p.id == reference_id), None)
        if reference is not None:
            upstream = [p for p in complete if p is not reference and p.pk < reference.pk + _PK_TOLERANCE]
            for point in upstream:
                errors.append(
                    f"Point dur « {point.label} » (PK {point.pk:g}) : il ne peut pas être en amont "
                    f"du premier point dur « {reference.label} » (PK {reference.pk:g}), qui sert de "
                    "référence pour la distance des profils."
                )

    for a, b in zip(complete, complete[1:]):
        if abs(b.pk - a.pk) <= _PK_TOLERANCE:
            errors.append(f"Points durs « {a.label} » et « {b.label} » : même PK ({a.pk:g}).")
        elif b.z > a.z:
            errors.append(
                f"Contre-pente entre « {a.label} » (Z {a.z:g}) et « {b.label} » (Z {b.z:g}) : "
                "le Z doit baisser vers l'aval."
            )
        elif b.z == a.z:
            errors.append(f"Pente nulle entre « {a.label} » et « {b.label} » (même Z : {a.z:g}).")

    if profile_pks and len(complete) >= 2:
        first, last = complete[0].pk, complete[-1].pk
        outside = [f"« {name} » (PK {pk:g})" for name, pk in profile_pks.items()
                   if not (first - _PK_TOLERANCE <= pk <= last + _PK_TOLERANCE)]
        if outside:
            errors.append(
                f"Ces profils sortiraient de la zone couverte par les points durs (PK {first:g} à "
                f"{last:g}) : {', '.join(outside)}."
            )
    return errors


@dataclass
class SlopeReport:
    """Bilan d'un recalcul des pentes hydrauliques d'un ou plusieurs profils (libellés
    "Scénario › Profil"), pour le message récapitulatif affiché à l'utilisateur."""
    updated: List[str] = field(default_factory=list)                 # pente calculée modifiée
    imposed_kept: List[str] = field(default_factory=list)            # pente imposée, laissée telle quelle
    switched_to_imposed: List[Tuple[str, str]] = field(default_factory=list)  # (profil, raison)

    def merge(self, other: "SlopeReport") -> "SlopeReport":
        self.updated += other.updated
        self.imposed_kept += other.imposed_kept
        self.switched_to_imposed += other.switched_to_imposed
        return self

    @property
    def has_changes(self) -> bool:
        return bool(self.updated or self.switched_to_imposed)

    def message(self) -> str:
        """Texte du message récapitulatif, ou "" s'il n'y a rien à signaler (aucune pente
        modifiée ni basculée en pente imposée)."""
        if not self.has_changes:
            return ""

        def names(labels, limit=8):
            shown = ", ".join(labels[:limit])
            return shown + (f" et {len(labels) - limit} autre(s)" if len(labels) > limit else "")

        lines = ["Pentes hydrauliques recalculées à partir des points durs :"]
        if self.updated:
            lines.append(f"• {len(self.updated)} profil(s) mis à jour : {names(self.updated)}")
        if self.imposed_kept:
            lines.append(f"• {len(self.imposed_kept)} profil(s) en pente imposée, non modifié(s) : "
                         f"{names(self.imposed_kept)}")
        if self.switched_to_imposed:
            lines.append(f"• {len(self.switched_to_imposed)} profil(s) passé(s) en pente imposée, "
                         "faute de calcul possible :")
            for label, reason in self.switched_to_imposed[:8]:
                lines.append(f"    – {label} : {reason}")
            if len(self.switched_to_imposed) > 8:
                lines.append(f"    – et {len(self.switched_to_imposed) - 8} autre(s)")
        return "\n".join(lines)
