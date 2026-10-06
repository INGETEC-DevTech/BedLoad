# ui/forms/hydraulics_form.py
from typing import List

import pandas as pd
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QScrollArea,
                                QRadioButton, QCheckBox, QDoubleSpinBox, QLabel, QComboBox,
                                QPushButton, QMessageBox, QDialog)
from PyQt6.QtCore import pyqtSignal

from core.controller import ALL_ZONE, CUSTOM_ZONE, LEFT_ARM, RIGHT_ARM
from core.hydraulics import suggest_arm_split
from core.models import Point, dataframe_to_points
from ui import theme
from ui.dialogs.point_picker_dialog import PointPickerDialog


class HydraulicsForm(QWidget):
    # Signal émis vers MainWindow quand les données changent (auto-save + maj graphique)
    data_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, theme.SPACE_MD, 0, 0)
        self.main_layout.setSpacing(theme.SPACE_MD)

        self.setStyleSheet(theme.qss("""
            QLabel, QRadioButton, QCheckBox { font-size: ${FONT_SIZE_BASE}px; color: $TEXT_SECONDARY; }
        """))

        self.inputs = {}
        self._is_loading = False
        # Points du profil existant (cf. set_existing_points).
        self._existing_points = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, theme.SPACE_MD, theme.SPACE_SM)
        layout.setSpacing(theme.SPACE_SM)

        # --- Source du calcul ---
        grp_source = QGroupBox("Calculer sur :")
        layout_source = QVBoxLayout(grp_source)
        self.radio_source_existing = QRadioButton("Profil existant")
        self.radio_source_project = QRadioButton("Profil projet")
        self.radio_source_project.setChecked(True)
        layout_source.addWidget(self.radio_source_existing)
        layout_source.addWidget(self.radio_source_project)
        layout.addWidget(grp_source)

        self.radio_source_project.toggled.connect(self._update_overlay_label)

        # --- Mode de dimensionnement ---
        grp_mode = QGroupBox("Mode de dimensionnement")
        layout_mode = QVBoxLayout(grp_mode)
        self.radio_calc_q = QRadioButton("Imposer H (Calculer le Débit)")
        self.radio_calc_h = QRadioButton("Imposer Q (Calculer la Hauteur d'eau)")
        self.radio_calc_q.setChecked(True)
        layout_mode.addWidget(self.radio_calc_q)
        layout_mode.addWidget(self.radio_calc_h)
        layout.addWidget(grp_mode)

        self.radio_calc_q.toggled.connect(self._toggle_hydro_fields)

        # --- Paramètres hydrauliques ---
        grp_hydro = QGroupBox("Paramètres Hydrauliques")
        form_hydro = QFormLayout(grp_hydro)

        self.inputs['h_eau'] = self._create_spinbox(0.01, 100, 0.05, 3, default_val=0.42)
        self.inputs['q_target'] = self._create_spinbox(0.1, 10000, 0.5, 2, default_val=15.0)
        # Regroupé avec Ks : ce sont les deux seuls paramètres de la formule de
        # Manning-Strickler, ce champ n'a rien à faire dans l'onglet Géométrie.
        self.inputs['slope'] = self._create_spinbox(0.0001, 1.0, 0.001, 4)
        self.inputs['ks_pro'] = self._create_spinbox(10, 100, 1, 1, default_val=25.0)
        # Un seul Ks pour le lit majeur (les deux rives partagent la même rugosité) :
        # stocké ici, pas encore utilisé dans le calcul hydraulique.
        self.inputs['floodplain_ks'] = self._create_spinbox(0, 200, 1, 1, default_val=25.0)

        form_hydro.addRow("Tirant d'eau h (m):", self.inputs['h_eau'])
        form_hydro.addRow("Débit Cible Q (m³/s):", self.inputs['q_target'])
        form_hydro.addRow("Pente long. (m/m):", self.inputs['slope'])
        form_hydro.addRow("Strickler (Ks):", self.inputs['ks_pro'])
        form_hydro.addRow("Strickler (Ks) – Lit majeur:", self.inputs['floodplain_ks'])
        layout.addWidget(grp_hydro)

        # --- Zone d'écoulement : tout le profil, un seul bras, ou entre deux X ---
        # Avec deux bras (ex. de part et d'autre d'une île), l'eau remplit par défaut tous
        # ceux qu'atteint la cote d'eau ; on peut la cantonner à un seul. Toutes les limites
        # agissent comme des parois verticales (cf. core.controller.flow_zone_bounds).
        grp_zone = QGroupBox("Zone d'écoulement")
        layout_zone = QVBoxLayout(grp_zone)
        layout_zone.setSpacing(theme.SPACE_SM)

        self.radio_zone_all = QRadioButton("Tout le profil (l'eau remplit tous les bras qu'elle atteint)")
        self.radio_zone_arm = QRadioButton("Un seul bras")
        self.radio_zone_custom = QRadioButton("Entre deux X")
        self.radio_zone_all.setChecked(True)

        self.inputs['hydro_arm_split_x'] = self._create_spinbox(-1_000_000, 1_000_000, 0.5, 3, default_val=0.0)
        self.combo_arm = QComboBox()
        self.combo_arm.addItem("Bras gauche", LEFT_ARM)
        self.combo_arm.addItem("Bras droit", RIGHT_ARM)
        self.combo_arm.currentIndexChanged.connect(self.on_value_changed)
        self.btn_pick_split = QPushButton("Choisir un point...")
        self.btn_pick_split.setToolTip(
            "Choisir la séparation parmi les points du profil existant (le point haut entre "
            "les deux bras est proposé)."
        )
        self.btn_pick_split.clicked.connect(self._pick_arm_split)
        row_split = QHBoxLayout()
        row_split.addWidget(self.inputs['hydro_arm_split_x'], stretch=1)
        row_split.addWidget(self.btn_pick_split)

        self.arm_panel = QWidget()
        form_arm = QFormLayout(self.arm_panel)
        form_arm.setContentsMargins(theme.SPACE_LG, 0, 0, 0)
        form_arm.addRow("Bras en eau :", self.combo_arm)
        form_arm.addRow("Séparation des bras X (m):", row_split)

        self.inputs['hydro_x_left'] = self._create_spinbox(-1_000_000, 1_000_000, 0.5, 3, default_val=0.0)
        self.inputs['hydro_x_right'] = self._create_spinbox(-1_000_000, 1_000_000, 0.5, 3, default_val=0.0)
        self.custom_panel = QWidget()
        form_custom = QFormLayout(self.custom_panel)
        form_custom.setContentsMargins(theme.SPACE_LG, 0, 0, 0)
        form_custom.addRow("X gauche (m):", self.inputs['hydro_x_left'])
        form_custom.addRow("X droite (m):", self.inputs['hydro_x_right'])

        layout_zone.addWidget(self.radio_zone_all)
        layout_zone.addWidget(self.radio_zone_arm)
        layout_zone.addWidget(self.arm_panel)
        layout_zone.addWidget(self.radio_zone_custom)
        layout_zone.addWidget(self.custom_panel)

        hint_zone = QLabel(
            "Les limites agissent comme des parois verticales : l'eau ne s'étend pas au-delà, "
            "et elles ne comptent pas dans le périmètre mouillé. Le terrain exclu du calcul est "
            "grisé sur le graphique."
        )
        hint_zone.setWordWrap(True)
        hint_zone.setStyleSheet(theme.qss("color: $TEXT_MUTED; font-size: ${FONT_SIZE_SM}px;"))
        layout_zone.addWidget(hint_zone)
        layout.addWidget(grp_zone)

        for radio in (self.radio_zone_all, self.radio_zone_arm, self.radio_zone_custom):
            radio.toggled.connect(self._on_zone_toggled)

        # --- Superposition de l'autre profil ---
        self.chk_overlay = QCheckBox()
        self.chk_overlay.stateChanged.connect(self.on_value_changed)
        row_overlay = QHBoxLayout()
        row_overlay.setContentsMargins(theme.SPACE_SM, 0, 0, 0)
        row_overlay.addWidget(self.chk_overlay)
        row_overlay.addStretch()
        layout.addLayout(row_overlay)

        layout.addStretch()

        scroll.setWidget(widget)
        self.main_layout.addWidget(scroll)

        self._toggle_hydro_fields()
        self._update_overlay_label()
        self._update_zone_fields()

    def set_existing_points(self, existing_data: list):
        """Reçoit les points du profil existant (MainWindow), pour choisir la séparation des
        bras parmi eux."""
        self._existing_points = existing_data

    def _existing_section_points(self) -> List[Point]:
        return dataframe_to_points(pd.DataFrame(self._existing_points)) if self._existing_points else []

    def _update_zone_fields(self):
        self.arm_panel.setEnabled(self.radio_zone_arm.isChecked())
        self.custom_panel.setEnabled(self.radio_zone_custom.isChecked())

    def _on_zone_toggled(self, checked: bool):
        # Chaque bascule déclenche deux toggled (le bouton quitté puis le bouton choisi) :
        # on ne réagit qu'au second.
        if not checked:
            return
        # Premier passage en "Un seul bras" (séparation encore à sa valeur par défaut) :
        # on propose directement le point haut entre les deux bras du profil existant.
        arm_first_use = (self.radio_zone_arm.isChecked() and not self._is_loading
                         and self.inputs['hydro_arm_split_x'].value() == 0.0)
        if arm_first_use:
            suggestion = suggest_arm_split(self._existing_section_points())
            if suggestion is not None:
                self._set_split_silently(suggestion.x)
        self._update_zone_fields()
        self.on_value_changed()

    def _set_split_silently(self, x: float):
        spin = self.inputs['hydro_arm_split_x']
        spin.blockSignals(True)
        spin.setValue(x)
        spin.blockSignals(False)

    def _pick_arm_split(self):
        """Choix de la séparation des bras parmi les points du profil existant, le point haut
        entre les deux bras (cf. suggest_arm_split) étant présélectionné et signalé."""
        points = self._existing_section_points()
        if not points:
            QMessageBox.information(
                self, "Aucun point disponible",
                "Renseignez d'abord des points dans l'onglet Profil existant."
            )
            return

        suggestion = suggest_arm_split(points)
        items, current_row = [], 0
        for row, pt in enumerate(points):
            label = f"X = {pt.x:.2f} m  |  Z = {pt.z:.2f} m NGF"
            if pt is suggestion:
                label += "   ← point haut entre les deux bras"
                current_row = row
            items.append(label)

        dialog = PointPickerDialog(self, "Séparation des bras", "Point de séparation (X, Z) :",
                                   items, current_row=current_row)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        index = dialog.selected_index()
        if index is None:
            return
        self._set_split_silently(points[index].x)
        self.on_value_changed()

    def _create_spinbox(self, min_val, max_val, step, decimals=2, default_val=None):
        sb = QDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setSingleStep(step)
        sb.setDecimals(decimals)
        if default_val is not None:
            sb.setValue(default_val)
        sb.valueChanged.connect(self.on_value_changed)
        return sb

    def _toggle_hydro_fields(self):
        is_calc_q = self.radio_calc_q.isChecked()
        self.inputs['h_eau'].setEnabled(is_calc_q)
        self.inputs['q_target'].setEnabled(not is_calc_q)
        self.on_value_changed()

    def _update_overlay_label(self):
        # Le libellé nomme toujours l'AUTRE profil que celui sur lequel porte le calcul.
        other = "existant" if self.radio_source_project.isChecked() else "projet"
        self.chk_overlay.setText(f"Afficher le profil {other} en fond")
        self.on_value_changed()

    def get_data(self) -> dict:
        data = {key: sb.value() for key, sb in self.inputs.items()}
        data['calc_mode'] = 'Q_FROM_H' if self.radio_calc_q.isChecked() else 'H_FROM_Q'
        data['hydro_source'] = 'existing' if self.radio_source_existing.isChecked() else 'project'
        data['show_overlay'] = self.chk_overlay.isChecked()
        if self.radio_zone_arm.isChecked():
            data['hydro_zone'] = self.combo_arm.currentData()
        elif self.radio_zone_custom.isChecked():
            data['hydro_zone'] = CUSTOM_ZONE
        else:
            data['hydro_zone'] = ALL_ZONE
        return data

    def set_data(self, data: dict):
        self._is_loading = True

        mode = data.get('calc_mode', 'Q_FROM_H')
        self.radio_calc_q.setChecked(mode == 'Q_FROM_H')
        self.radio_calc_h.setChecked(mode == 'H_FROM_Q')

        source = data.get('hydro_source', 'project')
        self.radio_source_existing.setChecked(source == 'existing')
        self.radio_source_project.setChecked(source != 'existing')

        self.chk_overlay.setChecked(bool(data.get('show_overlay', False)))
        zone = data.get('hydro_zone')
        if zone is None:
            # Profil enregistré avant le choix du bras (ancienne case "Lit de calcul").
            zone = CUSTOM_ZONE if data.get('hydro_bounds_enabled') else ALL_ZONE
        self.radio_zone_arm.setChecked(zone in (LEFT_ARM, RIGHT_ARM))
        self.radio_zone_custom.setChecked(zone == CUSTOM_ZONE)
        self.radio_zone_all.setChecked(zone not in (LEFT_ARM, RIGHT_ARM, CUSTOM_ZONE))
        self.combo_arm.setCurrentIndex(max(0, self.combo_arm.findData(zone)))

        for key, value in data.items():
            if key in self.inputs:
                self.inputs[key].setValue(float(value))
        # Profil enregistré avant l'ajout de la zone d'écoulement : pas de limites en base,
        # on remet les valeurs par défaut plutôt que de garder celles du profil précédent.
        for key in ('hydro_x_left', 'hydro_x_right', 'hydro_arm_split_x'):
            if key not in data:
                self.inputs[key].setValue(0.0)

        self._toggle_hydro_fields()
        self._update_overlay_label()
        self._update_zone_fields()
        self._is_loading = False

    def on_value_changed(self):
        if not self._is_loading:
            self.data_changed.emit(self.get_data())
