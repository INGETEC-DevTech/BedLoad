# ui/forms/distance_field.py
from typing import Optional, Tuple

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ui import theme

# Bornes et précision d'une distance quand le lit n'a pas encore de zone couverte par ses
# points durs (mêmes valeurs que les saisies de la barre latérale, cf. ui.sidebar).
_DISTANCE_MIN = -1_000_000.0
_DISTANCE_MAX = 1_000_000.0
_DISTANCE_DECIMALS = 3


class DistanceField(QWidget):
    """Distance du profil ouvert le long d'un lit (existant ou projet), en haut de l'onglet
    correspondant. Bornée par la zone couverte par les points durs de ce lit. Chaque valeur
    validée (Entrée, sortie du champ, flèches) est signalée par `distance_edited` :
    MainWindow l'enregistre, ou rétablit la valeur enregistrée si elle est refusée. Masquée
    pour un brouillon, qui n'a pas de distance."""

    distance_edited = pyqtSignal(float)

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_XS)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(_DISTANCE_DECIMALS)
        self.spin.setSingleStep(1.0)
        self.spin.setRange(_DISTANCE_MIN, _DISTANCE_MAX)
        # Pas de signal à chaque frappe : seulement une fois la valeur validée.
        self.spin.setKeyboardTracking(False)
        self.spin.valueChanged.connect(self._on_value_changed)
        self.lbl_label = QLabel(label)
        form.addRow(self.lbl_label, self.spin)
        layout.addLayout(form)

        self.lbl_hint = QLabel()
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(theme.qss("color: $TEXT_MUTED; font-size: ${FONT_SIZE_SM}px;"))
        layout.addWidget(self.lbl_hint)

    def set_distance(self, value: float, zone: Optional[Tuple[float, float]], reference: str):
        """Affiche `value` (sans rien signaler), bornée par `zone` (élargie si besoin à la
        valeur actuelle, pour ne jamais la modifier en silence) ; `reference` nomme le
        premier point dur de ce lit, pour le texte d'aide."""
        low, high = zone if zone is not None else (_DISTANCE_MIN, _DISTANCE_MAX)
        self.spin.blockSignals(True)
        self.spin.setRange(min(low, value), max(high, value))
        self.spin.setValue(value)
        self.spin.blockSignals(False)
        text = f"Distance {reference}"
        if zone is not None:
            text += f", entre {zone[0]:g} et {zone[1]:g} m (zone couverte par ses points durs)"
        self.lbl_hint.setText(text + ".")

    def value(self) -> float:
        return self.spin.value()

    def _on_value_changed(self, value: float):
        self.distance_edited.emit(value)
