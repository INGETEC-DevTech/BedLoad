"""
Assemblage du profil en long à partir des données par profil (PK).

Vue de contrôle uniquement : les deux séries sont lues telles quelles depuis chaque
profil (min(z) du terrain existant relevé, anchor_z du profil projet). Rien n'est
recalculé ni réinjecté dans les profils individuels — anchor_z et la pente restent
indépendants profil par profil.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class LongitudinalProfile:
    """Deux séries (PK, Z) à tracer en fonction du PK : TN existant (thalweg relevé)
    et fond de lit projet (anchor_z). Les deux séries peuvent avoir des longueurs
    différentes si certains profils n'ont pas encore de points existants ou de
    paramètres projet enregistrés."""
    pk_existing: List[float] = field(default_factory=list)
    z_existing: List[float] = field(default_factory=list)
    pk_project: List[float] = field(default_factory=list)
    z_project: List[float] = field(default_factory=list)


def build_longitudinal_profile(
    rows: List[Tuple[float, Optional[float], Optional[float]]]
) -> LongitudinalProfile:
    """Sépare les triplets (pk, min_z_existant, anchor_z_projet) — typiquement issus de
    DatabaseManager.get_longitudinal_data — en deux séries indépendantes, en ignorant
    pour chaque série les profils où la valeur correspondante est absente (None)."""
    profile = LongitudinalProfile()

    for pk, min_z_existing, anchor_z_project in rows:
        if min_z_existing is not None:
            profile.pk_existing.append(pk)
            profile.z_existing.append(min_z_existing)
        if anchor_z_project is not None:
            profile.pk_project.append(pk)
            profile.z_project.append(anchor_z_project)

    return profile
