# viz/figures.py
"""
Figures affichées par l'application : coupe du profil existant, du profil projet, de
l'onglet Hydraulique, et profil en long d'un scénario.

Couche de présentation : assemble les calculs de core (sections, hydraulique, déblais /
remblais, cf. core.controller) et les tracés de viz.plots, avec les textes et couleurs
d'affichage (encadré des résultats hydrauliques, avertissement de débordement).
"""
from __future__ import annotations
import math
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import plotly.graph_objects as go

from core.controller import (CUSTOM_ZONE, LEFT_ARM, RIGHT_ARM, TARGET_NOT_REACHED, HydraulicsSolution,
                             OverflowDiagnosis, ProfileController)
from core.earthworks import compute_earthworks
from core.geometry import build_project_cross_section
from core.hydraulics import subsection_dividers, target_discharge_reached
from core.longitudinal import StationEarthworks, build_longitudinal_profile
from ui import theme
from viz.plots import EXISTING_COLOR, PROJECT_COLOR, plot_overlay, plot_single_profile, plot_longitudinal_profile

# Fond de l'avertissement "l'eau déborderait hors du profil" (orange theme.WARNING, comme
# une alerte non bloquante).
OVERFLOW_WARNING_BACKGROUND = "rgba(255, 247, 237, 0.97)"

_controller = ProfileController()


class ViewMode(Enum):
    """Onglet affiché, donc figure à construire (cf. build_figure)."""
    EXISTING = "existing"
    PROJECT = "project"
    HYDRAULICS = "hydraulics"


def format_discharge(q: float) -> str:
    """Débit (m³/s) pour l'affichage, sans l'unité : 2 décimales, ou 3 chiffres significatifs
    sous 1 m³/s, pour qu'un petit débit garde sa précision (0.0318 et 0.0315 m³/s, et non
    0.03 tous les deux)."""
    if q == 0 or abs(q) >= 1:
        return f"{q:.2f}"
    return f"{q:.{2 - math.floor(math.log10(abs(q)))}f}"


def build_figure(
    existing_data: List[Dict[str, Any]],
    project_data: Dict[str, Any],
    mode: ViewMode,
    show_overlay: bool = False,
) -> Optional[go.Figure]:
    """Figure de l'onglet `mode`, ou None si les données ne suffisent pas à la tracer.
    ValueError (message lisible) si la géométrie ou la zone d'écoulement est incohérente."""
    if mode is ViewMode.EXISTING:
        return _existing_figure(existing_data)
    if mode is ViewMode.HYDRAULICS:
        return _hydraulics_figure(existing_data, project_data, project_data, show_overlay)
    return _project_figure(existing_data, project_data, show_overlay)


def build_longitudinal_figure(
    rows: List[Tuple[float, Optional[float], Optional[float]]],
    hard_points: Optional[List[Dict[str, Any]]] = None,
    earthworks: Optional[List[StationEarthworks]] = None,
    orthonormal: bool = False,
) -> Optional[go.Figure]:
    """Profil en long d'un scénario à partir des lignes (distance existante, min_z_existant,
    anchor_z_projet, nom, distance projet) renvoyées par DatabaseManager.get_longitudinal_data, des points durs du
    projet (format DatabaseManager.get_hard_points) et des déblais / remblais de chaque
    profil (cf. ProfileController.station_earthworks). `orthonormal` : 1 m en distance =
    1 m en altitude (case « Échelle orthonormée » du scénario)."""
    profile = build_longitudinal_profile(rows, hard_points)
    if not (profile.pk_existing or profile.pk_project or profile.hard_points or profile.project_hard_points):
        return None
    profile.earthworks = list(earthworks or [])
    return plot_longitudinal_profile(profile, orthonormal=orthonormal)


def _existing_figure(existing_data: List[Dict[str, Any]]) -> Optional[go.Figure]:
    section = _controller.to_cross_section(existing_data, name="Existant")
    if section is None:
        return None
    return plot_single_profile(section, color=EXISTING_COLOR)


def _project_figure(
    existing_data: List[Dict[str, Any]],
    project_data: Dict[str, Any],
    show_overlay: bool,
) -> go.Figure:
    """Éditeur de géométrie pure : aucun calcul hydraulique ni annotation de résultats
    (ceux-ci vivent dans l'onglet Hydraulique, cf. _hydraulics_figure)."""
    params = _controller.to_project_parameters(project_data)
    section_proj = build_project_cross_section(params, name="Projet")

    if show_overlay:
        section_ext = _controller.to_cross_section(existing_data, name="Existant", allow_empty=True)
        # Les deux profils affichés ensemble : on montre aussi ce qu'il faut enlever
        # (déblai) ou ajouter (remblai) pour passer de l'un à l'autre, par zone.
        earthworks = (compute_earthworks(section_ext, section_proj)
                      if len(section_ext.points) >= _controller.MIN_SECTION_POINTS else None)
        return plot_overlay(section_ext, section_proj, earthworks=earthworks)
    return plot_single_profile(section_proj, color=PROJECT_COLOR)


def _hydraulics_figure(
    existing_data: List[Dict[str, Any]],
    project_data: Dict[str, Any],
    hydro_data: Dict[str, Any],
    show_overlay: bool,
) -> Optional[go.Figure]:
    solved = _controller.solve_hydraulics(existing_data, project_data, hydro_data)
    if solved is None:
        return None
    section, hydro_source, bounds, res = solved.section, solved.hydro_source, solved.bounds, solved.res
    color = EXISTING_COLOR if hydro_source == 'existing' else PROJECT_COLOR

    # Ligne d'eau tracée sur tous les lits en eau, y compris ceux qui débordent (étendus
    # jusqu'au bord du profil) : elle reste visible en cas de débordement. Verticales de
    # découpage en lits : profil projet seulement (le profil existant n'est pas découpé).
    water = dict(water_level=res["water_z"], water_intervals=res["water_intervals"], calc_bounds=bounds,
                 dividers=subsection_dividers(section, bounds))

    # --- Génération de la figure ---
    if show_overlay:
        # L'AUTRE profil (existant si la source est le projet, et vice-versa) est
        # superposé en fond. plot_overlay colore son 1er argument en "existant" (vert)
        # et son 2e en "projet" (violet), quel que soit le rôle qu'il joue ici.
        if hydro_source == 'existing':
            other_params = _controller.to_project_parameters(project_data)
            other_section = build_project_cross_section(other_params, name="Projet")
            fig = plot_overlay(section, other_section, frame_all=True, **water)
        else:
            other_section = _controller.to_cross_section(existing_data, name="Existant", allow_empty=True)
            fig = plot_overlay(other_section, section, frame_all=True, **water)
    else:
        fig = plot_single_profile(section, color=color, **water)

    # --- Incrustation des résultats ---
    results = _results_text(solved)
    if results:
        fig.add_annotation(
            text=results, align="left", showarrow=False,
            xref="paper", yref="paper", x=0.02, y=0.96, xanchor="left", yanchor="top",
            bgcolor="rgba(255, 255, 255, 0.95)", bordercolor=theme.BORDER,
            borderwidth=1, borderpad=14, font=dict(size=13, color=theme.TEXT_SECONDARY)
        )

    # --- Avertissement de débordement --- (affiché même sans résultat : c'est justement
    # le cas où tout le lit a été ignoré et Q vaut 0)
    diagnosis = _controller.overflow_diagnosis(solved)
    if diagnosis:
        fig.add_annotation(
            text=overflow_warning_text(solved, diagnosis), align="left", showarrow=False,
            xref="paper", yref="paper", x=0.02, y=0.03, xanchor="left", yanchor="bottom",
            bgcolor=OVERFLOW_WARNING_BACKGROUND, bordercolor=theme.WARNING,
            borderwidth=1, borderpad=10, font=dict(size=12, color=theme.WARNING),
        )

    return fig


def _results_text(solved: HydraulicsSolution) -> Optional[str]:
    """Encadré "Résultats hydrauliques" (texte enrichi Plotly), ou None s'il n'y a rien à
    afficher (aucune surface mouillée)."""
    zone, bounds, res = solved.zone, solved.bounds, solved.res
    calc_mode, q_target = solved.calc_mode, solved.q_target
    is_h_calculated = calc_mode == 'H_FROM_Q'
    # "Imposer H" au-dessus d'une extrémité libre du profil : l'eau déborderait hors du
    # profil levé (non modélisé), le débit n'est pas calculable. Les résultats restent
    # affichés, comme d'habitude, avec le tirant d'eau saisi.
    overflowing = not is_h_calculated and bool(res["overflow_sides"])
    if not (res["S"] > 0 or (overflowing and res["water_intervals"])):
        return None
    h_relative = res["water_z"] - solved.z_ref

    def highlighted_line(label: str, value_str: str) -> str:
        # La grandeur calculée : toute la ligne en gras et en couleur d'accent,
        # pour qu'on repère d'un coup d'œil LE résultat qui bouge avec la saisie.
        return f'<span style="color:{theme.PRIMARY}"><b>{label} : {value_str} [Calculé]</b></span>'

    def discreet_line(label: str, value_str: str, tag: Optional[str] = None) -> str:
        line = f"<b>{label} :</b> {value_str}"
        return f"{line} <i>[{tag}]</i>" if tag else line

    def not_computable_line(label: str, value_str: str) -> str:
        return f'<span style="color:{theme.WARNING}"><b>{label} : {value_str}</b></span>'

    if overflowing:
        q_line = not_computable_line("Débit (Q)", "non calculable (débordement)")
    elif not is_h_calculated:
        q_line = highlighted_line("Débit (Q)", f"{format_discharge(res['Q'])} m³/s")
    elif target_discharge_reached(res["Q"], q_target):
        q_line = discreet_line("Débit (Q)", f"{format_discharge(res['Q'])} m³/s", "Saisi")
    else:
        # Débit cible trop fort : l'eau est laissée au niveau maximal sans
        # débordement, Q est la capacité correspondante (cf. avertissement).
        q_line = not_computable_line(
            "Débit (Q)", f"{format_discharge(res['Q'])} m³/s "
                         f"(cible {format_discharge(q_target)} m³/s non atteinte)"
        )
    h_line = (
        highlighted_line("Tirant d'eau (h)", f"{h_relative:.2f} m")
        if is_h_calculated
        else discreet_line("Tirant d'eau (h)", f"{h_relative:.2f} m", "Saisi")
    )

    if overflowing:
        v_line = discreet_line("Vitesse moyenne (V)", "non calculable")
        s_line = discreet_line("Surface mouillée (S)", "non calculable")
    else:
        v_line = discreet_line("Vitesse moyenne (V)", f"{res['V']:.2f} m/s")
        s_line = discreet_line("Surface mouillée (S)", f"{res['S']:.2f} m²")

    text = (
        f'<span style="color:{theme.TEXT_PRIMARY}"><b>Résultats hydrauliques</b></span><br><br>'
        f"{q_line}<br>{v_line}<br>{s_line}<br>{h_line}"
    )
    zone_label = None
    if zone == LEFT_ARM:
        zone_label = f"bras gauche seul (X < {bounds[1]:.2f} m)"
    elif zone == RIGHT_ARM:
        zone_label = f"bras droit seul (X > {bounds[0]:.2f} m)"
    elif zone == CUSTOM_ZONE:
        zone_label = f"X = {bounds[0]:.2f} → {bounds[1]:.2f} m"
    if zone_label:
        text += "<br>" + discreet_line("Zone d'écoulement", zone_label)

    # Plusieurs zones en eau (typiquement les deux bras) : répartition du débit,
    # chacune avec son propre rayon hydraulique (cf. compute_hydraulic_params).
    if len(res["wet_intervals"]) > 1 and not overflowing:
        text += "<br><b>Répartition du débit :</b>"
        for (x0, x1), q in zip(res["wet_intervals"], res["bed_discharges"]):
            share = 100 * q / res["Q"] if res["Q"] else 0
            text += (f"<br>&nbsp;&nbsp;• X {x0:.2f} → {x1:.2f} m : "
                     f"{format_discharge(q)} m³/s ({share:.0f} %)")

    # Section découpée en lits (profil projet) : débit et vitesse de chaque partie
    # mouillée, calculée séparément (cf. compute_hydraulic_params).
    if res["subsections"] and not overflowing:
        text += "<br><b>Détail par partie mouillée :</b>"
        for part in res["subsections"]:
            share = 100 * part["Q"] / res["Q"] if res["Q"] else 0
            text += (f"<br>&nbsp;&nbsp;• {part['name']} : {format_discharge(part['Q'])} m³/s "
                     f"({share:.0f} %), V = {part['V']:.2f} m/s")
    return text


def overflow_warning_text(solved: HydraulicsSolution, diagnosis: OverflowDiagnosis) -> str:
    """Message de l'avertissement de débordement (cf. ProfileController.overflow_diagnosis),
    qui rappelle la capacité maximale sans débordement pour situer la valeur saisie."""
    res = solved.res
    capacity = ""
    if diagnosis.level is not None:
        capacity = (f"<br>Capacité maximale sans débordement : Q = {format_discharge(diagnosis.q_max)} m³/s "
                    f"(cote Z = {diagnosis.level:.2f} m NGF).")

    if diagnosis.kind == TARGET_NOT_REACHED:
        reason = (
            "au-delà, l'eau déborderait hors du profil (débordement non modélisé) : la cote "
            "d'eau est laissée à ce niveau maximal."
            if diagnosis.level is not None else
            "la cote d'eau est plafonnée au sommet du profil calculé."
        )
        return (
            f"<b>⚠ Débit cible non atteint</b> : {format_discharge(solved.q_target)} m³/s demandés, "
            f"{format_discharge(res['Q'])} m³/s calculés —<br>{reason}{capacity}"
        )

    side_label = {"left": "gauche", "right": "droite"}
    details = " et ".join(f"{side_label[side]} (Z = {z:.2f} m NGF)" for side, z in diagnosis.end_levels.items())
    return (
        f"<b>⚠ Débordement</b> : la cote d'eau (Z = {res['water_z']:.2f} m NGF) dépasse "
        f"l'extrémité {details} du profil.<br>"
        "L'eau déborderait hors du profil levé (débordement non modélisé) : débit non "
        f"calculable.{capacity}"
    )
