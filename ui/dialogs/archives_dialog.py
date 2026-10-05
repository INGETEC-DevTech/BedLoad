# ui/dialogs/archives_dialog.py
from html import escape
from typing import List

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                              QPushButton, QLabel, QMessageBox)
from PyQt6.QtCore import Qt

from database.db_manager import DatabaseManager
from ui import theme


def _plural(count: int, singular: str) -> str:
    return f"{count} {singular}{'s' if count > 1 else ''}"


class ArchivesDialog(QDialog):
    """Projets archivés : rangés hors de l'arborescence de la sidebar, mais toujours en
    base avec tous leurs scénarios et profils. Ils ne peuvent pas être ouverts depuis ici :
    il faut d'abord les restaurer (ils réapparaissent alors dans la sidebar), ou les
    supprimer définitivement. Les modifications sont appliquées à la base immédiatement,
    sans attendre la fermeture du dialogue ; `restored_ids` liste les projets restaurés
    pendant la session, pour que l'appelant rafraîchisse l'arbre et les mette en avant."""

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db = db
        self.restored_ids: List[int] = []
        self.setWindowTitle("Archives")
        self.setMinimumSize(420, 340)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE_MD)

        hint = QLabel(
            "Projets rangés hors de la liste de gauche. Restaurez un projet pour le "
            "retrouver et le rouvrir."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.qss("color: $TEXT_MUTED; font-size: ${FONT_SIZE_SM}px;"))
        layout.addWidget(hint)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        self.empty_label = QLabel("Aucun projet archivé.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(theme.qss("color: $TEXT_MUTED;"))
        layout.addWidget(self.empty_label)

        buttons = QHBoxLayout()
        self.btn_restore = QPushButton("Restaurer")
        self.btn_delete = QPushButton("Supprimer définitivement...")
        self.btn_close = QPushButton("Fermer")
        buttons.addWidget(self.btn_restore)
        buttons.addWidget(self.btn_delete)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

        self.btn_restore.clicked.connect(self.restore_selected)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_close.clicked.connect(self.accept)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.restore_selected())
        self.list_widget.currentItemChanged.connect(lambda *_: self._update_buttons())

        self.reload()

    def reload(self) -> None:
        """Relit la liste des projets archivés depuis la base."""
        self.list_widget.clear()
        for project in self.db.get_archived_projects():
            label = (
                f"{project['name']}  —  {_plural(project['scenario_count'], 'scénario')}, "
                f"{_plural(project['profile_count'], 'profil')}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, {"id": project["id"], "name": project["name"]})
            self.list_widget.addItem(item)

        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        self.list_widget.setVisible(bool(self.list_widget.count()))
        self.empty_label.setVisible(not self.list_widget.count())
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_selection = self.list_widget.currentItem() is not None
        self.btn_restore.setEnabled(has_selection)
        self.btn_delete.setEnabled(has_selection)

    def _current_project(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def restore_selected(self) -> None:
        project = self._current_project()
        if project is None:
            return
        try:
            self.db.set_project_archived(project["id"], False)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))
            self.reload()
            return
        self.restored_ids.append(project["id"])
        self.reload()

    def delete_selected(self) -> None:
        project = self._current_project()
        if project is None:
            return

        # Irréversible : le bouton par défaut reste "Non" (même règle que la suppression
        # d'un projet depuis la sidebar).
        reply = QMessageBox.question(
            self,
            "Confirmation de suppression",
            f"Êtes-vous sûr de vouloir supprimer définitivement « {escape(project['name'])} » ?"
            f'<br><br><b style="color:{theme.DANGER}">Attention :</b> '
            "cela supprimera également tous ses scénarios et leurs profils.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.db.delete_project(project["id"])
        self.reload()
