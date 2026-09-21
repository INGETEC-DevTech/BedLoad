# app.py
import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow
import traceback
import logging
from core.utils import setup_logger
from ui import theme

# Le bloc QTreeView a été retiré de ce thème global : la sidebar redéfinit entièrement
# l'apparence de son arbre (feuille de style locale + delegate qui peint chaque ligne),
# donc ces règles étaient écrasées sans effet. Idem pour QGroupBox/QTabWidget:disabled,
# qui décrivaient un état "formulaire grisé" remplacé depuis par la page d'accueil.
QSS_THEME = theme.qss("""
/* Base de la fenêtre */
QMainWindow, QWidget {
    background-color: $BACKGROUND;
    font-family: $FONT_FAMILY;
    font-size: ${FONT_SIZE_BASE}px;
    color: $TEXT_PRIMARY;
}

/* Allègement des cadres (QGroupBox) */
QGroupBox {
    font-weight: bold;
    border: none;
    border-top: 1px solid $BORDER;
    margin-top: 20px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding-bottom: 5px;
    color: $TEXT_SECONDARY;
}

/* Onglets modernisés */
QTabWidget::pane {
    border: 1px solid $BORDER;
    background: $SURFACE;
    border-radius: ${RADIUS_SM}px;
}
QTabBar::tab {
    background: $HOVER;
    border: 1px solid $BORDER;
    padding: 8px 20px;
    margin-right: 2px;
    border-top-left-radius: ${RADIUS_SM}px;
    border-top-right-radius: ${RADIUS_SM}px;
}
QTabBar::tab:selected {
    background: $SURFACE;
    border-bottom-color: $SURFACE;
    color: $PRIMARY_TEXT;
    font-weight: bold;
}

/* Boutons flat design */
QPushButton {
    background-color: $SURFACE;
    border: 1px solid $BORDER_INPUT;
    border-radius: ${RADIUS_SM}px;
    padding: 6px 12px;
}
QPushButton:hover {
    background-color: $HOVER;
}
QPushButton:pressed {
    background-color: $PRESSED;
}
QPushButton:disabled {
    background-color: $BACKGROUND;
    color: $TEXT_MUTED;
    border: 1px solid $HOVER;
}

/* Champs de saisie */
QLineEdit, QTableWidget, QDoubleSpinBox {
    border: 1px solid $BORDER_INPUT;
    border-radius: 3px;
    padding: 4px;
    background: $SURFACE;
}
QLineEdit:focus, QTableWidget:focus, QDoubleSpinBox:focus {
    border: 1px solid $BORDER_FOCUS;
}
QLineEdit:disabled, QTableWidget:disabled, QDoubleSpinBox:disabled {
    background-color: $SURFACE_ALT;
    color: $TEXT_MUTED;
}

/* Cases à cocher */
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid $BORDER_INPUT;
    border-radius: 3px;
    background: $SURFACE;
}
QCheckBox::indicator:checked {
    background-color: $PRIMARY;
    border: 1px solid $PRIMARY;
}
QCheckBox:disabled {
    color: $TEXT_MUTED;
}
""")

def global_exception_handler(exc_type, exc_value, exc_tb):
    """Intercepte les erreurs critiques pour éviter la fermeture silencieuse."""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    # Enregistrement silencieux du crash
    logging.critical(f"Crash inattendu : {exc_value}\n{error_msg}")

    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Icon.Critical)
    msg_box.setWindowTitle("Erreur critique")
    msg_box.setText("Le logiciel a rencontré une erreur inattendue.")
    msg_box.setInformativeText(str(exc_value))
    msg_box.setDetailedText(error_msg)
    msg_box.exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    setup_logger()
    logging.info("=== Démarrage d'HydroTopo V2 ===")
    
    # Interception de toutes les erreurs globales
    sys.excepthook = global_exception_handler
    
    app.setStyle("Fusion") 
    app.setStyleSheet(QSS_THEME)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())