# ui/forms/project_form.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QDoubleSpinBox,
                                QGroupBox, QScrollArea, QCheckBox)
from PyQt6.QtCore import pyqtSignal

from ui import theme

class ProjectProfileForm(QWidget):
    data_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, theme.SPACE_MD, 0, 0)
        self.main_layout.setSpacing(theme.SPACE_MD)

        # Niveau 3 de la hiérarchie typographique : les libellés restent en retrait des
        # valeurs qu'ils décrivent (14px, cf. la règle globale sur les champs de saisie).
        self.setStyleSheet(theme.qss("""
            QLabel, QCheckBox { font-size: ${FONT_SIZE_BASE}px; color: $TEXT_SECONDARY; }
        """))

        self.inputs = {}
        self._is_loading = False

        self._setup_geo_tab()

        self.chk_overlay = QCheckBox("Afficher le profil existant en fond (vert)")
        self.chk_overlay.stateChanged.connect(self.on_value_changed)
        self.main_layout.addWidget(self.chk_overlay)

    def _create_spinbox(self, min_val, max_val, step, decimals=2, default_val=None):
        sb = QDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setSingleStep(step)
        sb.setDecimals(decimals)
        if default_val is not None:
            sb.setValue(default_val)
        sb.valueChanged.connect(self.on_value_changed)
        return sb

    def _setup_geo_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }") # Évite une double bordure
        widget = QWidget()
        layout = QVBoxLayout(widget)
        # Marge droite plus large : elle réserve la place de la barre de défilement.
        layout.setContentsMargins(0, 0, theme.SPACE_MD, theme.SPACE_SM)
        layout.setSpacing(theme.SPACE_SM)

        grp_anchor = QGroupBox("Ancrage && Topographie")
        form_anchor = QFormLayout(grp_anchor)
        self.inputs['anchor_x'] = self._create_spinbox(-1000, 1000, 0.1)
        self.inputs['anchor_z'] = self._create_spinbox(-100, 1000, 0.01)
        form_anchor.addRow("X bord gauche fond (m):", self.inputs['anchor_x'])
        form_anchor.addRow("Z fond du lit (m NGF):", self.inputs['anchor_z'])
        layout.addWidget(grp_anchor)

        grp_bed = QGroupBox("Lit trapézoïdal")
        form_bed = QFormLayout(grp_bed)
        self.inputs['bed_width'] = self._create_spinbox(0, 1000, 0.1)
        self.inputs['bed_depth'] = self._create_spinbox(0, 100, 0.01)
        self.inputs['bed_side_slope'] = self._create_spinbox(0.01, 100, 0.1)
        form_bed.addRow("Largeur fond (m):", self.inputs['bed_width'])
        form_bed.addRow("Profondeur (m):", self.inputs['bed_depth'])
        form_bed.addRow("Pente bords (H/V):", self.inputs['bed_side_slope'])
        layout.addWidget(grp_bed)

        grp_berms = QGroupBox("Banquettes && Berges")
        form_berms = QFormLayout(grp_berms)
        self.inputs['berm_width_left'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['berm_width_right'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['bank_slope_left'] = self._create_spinbox(0.01, 100, 0.1)
        self.inputs['bank_width_left'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['bank_slope_right'] = self._create_spinbox(0.01, 100, 0.1)
        self.inputs['bank_width_right'] = self._create_spinbox(0, 100, 0.1)
        form_berms.addRow("Banquette RG (m):", self.inputs['berm_width_left'])
        form_berms.addRow("Banquette RD (m):", self.inputs['berm_width_right'])
        form_berms.addRow("Pente Berge G (H/V):", self.inputs['bank_slope_left'])
        form_berms.addRow("Largeur Berge G (m):", self.inputs['bank_width_left'])
        form_berms.addRow("Pente Berge D (H/V):", self.inputs['bank_slope_right'])
        form_berms.addRow("Largeur Berge D (m):", self.inputs['bank_width_right'])
        layout.addWidget(grp_berms)
        # Sans ce stretch final, le QVBoxLayout distribue l'espace restant du QScrollArea
        # en étirant chaque QGroupBox au lieu de le laisser vide en bas.
        layout.addStretch()

        scroll.setWidget(widget)
        self.main_layout.addWidget(scroll)

    def get_data(self) -> dict:
        data = {key: sb.value() for key, sb in self.inputs.items()}
        data['show_overlay'] = self.chk_overlay.isChecked()
        return data

    def set_data(self, data: dict):
        self._is_loading = True

        for key, value in data.items():
            if key in self.inputs:
                self.inputs[key].setValue(float(value))

        self.chk_overlay.setChecked(bool(data.get('show_overlay', False)))
        self._is_loading = False

    def on_value_changed(self):
        if not self._is_loading:
            self.data_changed.emit(self.get_data())
