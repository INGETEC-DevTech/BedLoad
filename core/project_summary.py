# core/project_summary.py
"""Récapitulatif d'un projet : une ligne de chiffres clés par scénario (avancement de la
saisie, terrassements, contrôle hydraulique), pour les comparer d'un coup d'œil.

Les chiffres sont recalculés à partir des profils enregistrés, avec exactement les mêmes
fonctions que les onglets du profil (cf. ProfileController.scenario_summary) : le
récapitulatif ne peut pas diverger de ce qu'affiche chaque profil."""
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from core.hard_points import HardPoint
from core.longitudinal import SegmentMarker, StationEarthworks


@dataclass
class ScenarioSummary:
    scenario_id: int
    name: str
    n_profiles: int = 0
    # Profils dont le terrain existant (au moins 2 points) ET le profil projet (cote
    # d'ancrage) sont renseignés.
    n_complete: int = 0
    # Distances du premier et du dernier profil, ou None sans profil.
    distance_range: Optional[Tuple[float, float]] = None
    # Déblai / remblai : sommes des surfaces en coupe (m²) des profils calculés, comme la
    # légende du profil en long, et volumes (m³) par la méthode des moyennes des aires.
    n_earthworks: int = 0
    cut_area: float = 0.0
    fill_area: float = 0.0
    cut_volume: Optional[float] = None
    fill_volume: Optional[float] = None
    # Contrôle hydraulique : profils dont le réglage enregistré fait déborder l'eau hors du
    # profil (avertissement de l'onglet Hydraulique), parmi ceux qui ont un réglage.
    n_hydraulics: int = 0
    overflow_names: List[str] = field(default_factory=list)

    @property
    def area_balance(self) -> float:
        return self.cut_area - self.fill_area

    @property
    def volume_balance(self) -> Optional[float]:
        if self.cut_volume is None or self.fill_volume is None:
            return None
        return self.cut_volume - self.fill_volume


@dataclass
class ProjectSummary:
    name: str
    scenarios: List[ScenarioSummary]
    # Points durs existants complets (PK et Z), dans l'ordre des PK, et tronçons qui les
    # relient ; de même pour les points durs projet (lit déplacé ou reméandré).
    hard_points: List[HardPoint] = field(default_factory=list)
    segments: List[SegmentMarker] = field(default_factory=list)
    project_hard_points: List[HardPoint] = field(default_factory=list)
    project_segments: List[SegmentMarker] = field(default_factory=list)


def earthwork_volumes(stations: Sequence[StationEarthworks]) -> Tuple[Optional[float], Optional[float]]:
    """Volumes de déblai et de remblai (m³) par la méthode des moyennes des aires : entre
    deux profils calculés consécutifs (par distance existante), surface moyenne × distance
    qui les sépare. Un profil non calculé est simplement sauté (ses voisins calculés sont reliés
    directement) ; rien n'est compté au-delà du premier et du dernier profil calculés.
    (None, None) s'il y a moins de deux profils calculés : pas de longueur d'application."""
    computed = sorted((s for s in stations if s.computed), key=lambda s: s.distance)
    if len(computed) < 2:
        return None, None
    cut = fill = 0.0
    for a, b in zip(computed, computed[1:]):
        length = b.distance - a.distance
        cut += (a.cut + b.cut) / 2 * length
        fill += (a.fill + b.fill) / 2 * length
    return cut, fill
