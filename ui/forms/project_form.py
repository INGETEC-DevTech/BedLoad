# ui/forms/project_form.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTabWidget, QFormLayout, 
                               QDoubleSpinBox, QGroupBox, QScrollArea)
from PyQt6.QtCore import pyqtSignal

class ProjectProfileForm(QWidget):
    data_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)
        
        # Initialisation des variables pour stocker les widgets
        self.inputs = {}
        self._is_loading = False
        
        self._setup_geo_tab()
        self._setup_hydro_tab()

    def _create_spinbox(self, min_val, max_val, step, decimals=2):
        """Fonction utilitaire pour créer et configurer un QDoubleSpinBox."""
        sb = QDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setSingleStep(step)
        sb.setDecimals(decimals)
        sb.valueChanged.connect(self.on_value_changed)
        return sb

    def _setup_geo_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Ancrage
        grp_anchor = QGroupBox("Ancrage sur le terrain")
        form_anchor = QFormLayout(grp_anchor)
        self.inputs['anchor_x'] = self._create_spinbox(-1000, 1000, 0.1)
        self.inputs['anchor_z'] = self._create_spinbox(-100, 1000, 0.01)
        form_anchor.addRow("X du bord gauche (m):", self.inputs['anchor_x'])
        form_anchor.addRow("Z du fond du lit (m NGF):", self.inputs['anchor_z'])
        layout.addWidget(grp_anchor)

        # Lit trapézoïdal
        grp_bed = QGroupBox("Lit trapézoïdal")
        form_bed = QFormLayout(grp_bed)
        self.inputs['bed_width'] = self._create_spinbox(0, 1000, 0.1)
        self.inputs['bed_depth'] = self._create_spinbox(0, 100, 0.01)
        self.inputs['bed_side_slope'] = self._create_spinbox(0.01, 100, 0.1)
        form_bed.addRow("Largeur fond du lit (m):", self.inputs['bed_width'])
        form_bed.addRow("Profondeur (m):", self.inputs['bed_depth'])
        form_bed.addRow("Pente des bords (H/V):", self.inputs['bed_side_slope'])
        layout.addWidget(grp_bed)
        
        # Banquettes et Berges... (version condensée pour l'exemple)
        grp_berms = QGroupBox("Banquettes & Berges")
        form_berms = QFormLayout(grp_berms)
        self.inputs['berm_width_left'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['berm_width_right'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['bank_slope_left'] = self._create_spinbox(0.01, 100, 0.1)
        self.inputs['bank_width_left'] = self._create_spinbox(0, 100, 0.1)
        self.inputs['bank_slope_right'] = self._create_spinbox(0.01, 100, 0.1)
        self.inputs['bank_width_right'] = self._create_spinbox(0, 100, 0.1)
        form_berms.addRow("Largeur BANQ RG (m):", self.inputs['berm_width_left'])
        form_berms.addRow("Largeur BANQ RD (m):", self.inputs['berm_width_right'])
        form_berms.addRow("Pente BG (H/V):", self.inputs['bank_slope_left'])
        form_berms.addRow("Largeur BG (m):", self.inputs['bank_width_left'])
        form_berms.addRow("Pente BD (H/V):", self.inputs['bank_slope_right'])
        form_berms.addRow("Largeur BD (m):", self.inputs['bank_width_right'])
        layout.addWidget(grp_berms)

        scroll.setWidget(widget)
        self.tabs.addTab(scroll, "Géométrie")

    def _setup_hydro_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        grp_hydro = QGroupBox("Ligne d'eau")
        form_hydro = QFormLayout(grp_hydro)
        self.inputs['h_eau'] = self._create_spinbox(0, 100, 0.01, 4)
        self.inputs['x_eau_gauche'] = self._create_spinbox(-1000, 1000, 0.1)
        self.inputs['x_eau_droite'] = self._create_spinbox(-1000, 1000, 0.1)
        
        form_hydro.addRow("h_eau (m):", self.inputs['h_eau'])
        form_hydro.addRow("X de l'eau (gauche):", self.inputs['x_eau_gauche'])
        form_hydro.addRow("X de l'eau (droite):", self.inputs['x_eau_droite'])
        layout.addWidget(grp_hydro)
        layout.addStretch()
        
        self.tabs.addTab(widget, "Hydraulique")

    def get_data(self) -> dict:
        return {key: sb.value() for key, sb in self.inputs.items()}

    def set_data(self, data: dict):
        self._is_loading = True
        for key, value in data.items():
            if key in self.inputs:
                self.inputs[key].setValue(float(value))
        self._is_loading = False

    def on_value_changed(self):
        if not self._is_loading:
            self.data_changed.emit(self.get_data())