from typing import List, Dict, Optional, Tuple

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, QCheckBox,
                              QComboBox, QDialogButtonBox, QLabel)

from ui import theme


class ScenarioDialog(QDialog):
    """Création d'un scénario dans un projet : un nom, et en option un scénario source du
    même projet dont tous les profils sont dupliqués dans le nouveau scénario (copie
    indépendante). Sans source, le nouveau scénario démarre vide."""

    def __init__(self, parent=None, scenarios: List[Dict] = None, default_name: str = "",
                 source_scenario_id: Optional[int] = None, title: str = "Nouveau scénario"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        scenarios = scenarios or []

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE_MD)

        form = QFormLayout()
        self.name_edit = QLineEdit(default_name)
        self.name_edit.selectAll()
        form.addRow("Nom du scénario :", self.name_edit)
        layout.addLayout(form)

        self.keep_profiles_check = QCheckBox("Conserver les profils d'un scénario existant")
        layout.addWidget(self.keep_profiles_check)

        self.source_combo = QComboBox()
        for scenario in scenarios:
            self.source_combo.addItem(scenario["name"], scenario["id"])
        layout.addWidget(self.source_combo)

        hint = QLabel(
            "Tous les profils du scénario source (profil existant, profil projet, "
            "hydraulique) sont copiés : les modifier ensuite n'affecte pas la source. "
            "Sans cette option, le nouveau scénario démarre vide."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.qss("color: $TEXT_MUTED; font-size: ${FONT_SIZE_SM}px;"))
        layout.addWidget(hint)

        if not scenarios:
            self.keep_profiles_check.setEnabled(False)
            self.keep_profiles_check.setToolTip("Ce projet n'a encore aucun scénario à reprendre.")
        elif source_scenario_id is not None:
            self.keep_profiles_check.setChecked(True)
            index = self.source_combo.findData(source_scenario_id)
            if index >= 0:
                self.source_combo.setCurrentIndex(index)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.keep_profiles_check.toggled.connect(self._update_state)
        self.name_edit.textChanged.connect(self._update_state)
        self._update_state()

    def _update_state(self, _=None):
        self.source_combo.setEnabled(self.keep_profiles_check.isChecked())
        ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setEnabled(bool(self.name_edit.text().strip()))

    def get_values(self) -> Tuple[str, Optional[int]]:
        """(nom saisi, id du scénario source ou None si l'option n'est pas cochée)."""
        source_id = self.source_combo.currentData() if self.keep_profiles_check.isChecked() else None
        return self.name_edit.text().strip(), source_id
