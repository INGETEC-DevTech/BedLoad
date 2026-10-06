"""
Assemblage du profil en long à partir des données par profil (distance au premier point
dur).

Vue de contrôle uniquement : les deux séries sont lues telles quelles depuis chaque
profil (min(z) du terrain existant relevé, anchor_z du profil projet). Rien n'est
recalculé ni réinjecté dans les profils individuels — anchor_z et la pente restent
indépendants profil par profil.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.hard_points import HardPoint, complete_points


@dataclass
class HardPointMarker:
    """Un point dur positionné sur le profil en long : distance au premier point dur (0
    pour celui-ci) et altitude, avec son nom pour l'identifier sur le graphique."""
    distance: float
    z: float
    name: str


@dataclass
class SegmentMarker:
    """Tronçon entre deux points durs voisins, avec sa pente (m/m)."""
    start: HardPointMarker
    end: HardPointMarker
    slope: float


@dataclass
class LongitudinalProfile:
    """Deux séries (distance au premier point dur, Z) à tracer en fonction de cette
    distance : TN existant (thalweg relevé) et fond de lit projet (anchor_z). Les champs
    gardent le préfixe `pk_` par cohérence avec le reste du module. Les deux séries
    peuvent avoir des longueurs différentes si certains profils n'ont pas encore de
    points existants ou de paramètres projet enregistrés. `hard_points` liste les points
    durs complets (PK et Z), dans l'ordre des PK, et `segments` les tronçons qui les
    relient avec leur pente."""
    pk_existing: List[float] = field(default_factory=list)
    z_existing: List[float] = field(default_factory=list)
    pk_project: List[float] = field(default_factory=list)
    z_project: List[float] = field(default_factory=list)
    hard_points: List[HardPointMarker] = field(default_factory=list)
    segments: List[SegmentMarker] = field(default_factory=list)
    # Profils en travers : (distance, nom) de chacun, qu'il ait des valeurs ou non, pour
    # les repérer sur le graphique ; et nom du profil de chaque point des deux séries
    # (pour le survol).
    stations: List[Tuple[float, str]] = field(default_factory=list)
    names_existing: List[str] = field(default_factory=list)
    names_project: List[str] = field(default_factory=list)


def build_longitudinal_profile(
    rows: List[Tuple],
    hard_points: Optional[List[Dict]] = None,
) -> LongitudinalProfile:
    """Sépare les lignes (distance, min_z_existant, anchor_z_projet[, nom du profil]) —
    typiquement issues de DatabaseManager.get_longitudinal_data — en deux séries
    indépendantes, en ignorant pour chaque série les profils où la valeur correspondante
    est absente (None). Chaque profil est aussi repéré (distance, nom) dans `stations`.

    `hard_points` (format DatabaseManager.get_hard_points : [{name, pk, z}]) positionne
    en plus tous les points durs complets, à leur distance au premier d'entre eux (la
    référence "distance 0" des profils), et les tronçons qui les relient avec leur pente.
    Un point incomplet (PK ou Z manquant) n'est pas placé à une position arbitraire : il
    est simplement absent du graphique."""
    profile = LongitudinalProfile()

    for row in rows:
        pk, min_z_existing, anchor_z_project = row[:3]
        # 4e élément facultatif : le nom du profil (cf. get_longitudinal_data).
        name = row[3] if len(row) > 3 and row[3] else f"{pk:g} m"
        profile.stations.append((pk, name))
        if min_z_existing is not None:
            profile.pk_existing.append(pk)
            profile.z_existing.append(min_z_existing)
            profile.names_existing.append(name)
        if anchor_z_project is not None:
            profile.pk_project.append(pk)
            profile.z_project.append(anchor_z_project)
            profile.names_project.append(name)

    points = complete_points(HardPoint.from_dict(p) for p in (hard_points or []))
    if points:
        reference = points[0].pk
        profile.hard_points = [
            HardPointMarker(distance=p.pk - reference, z=p.z, name=p.name or f"Point dur {i}")
            for i, p in enumerate(points, start=1)
        ]
        profile.segments = [
            SegmentMarker(start=a, end=b, slope=(a.z - b.z) / (b.distance - a.distance))
            for a, b in zip(profile.hard_points, profile.hard_points[1:])
            if b.distance > a.distance
        ]

    return profile
