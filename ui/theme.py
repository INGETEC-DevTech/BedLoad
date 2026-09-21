# ui/theme.py
"""
Design tokens de l'application : couleurs, espacements, typographie.

Tout le reste de l'UI (app.py, ui/…) référence ces constantes par leur *rôle*
(PRIMARY, TEXT_MUTED, SPACE_MD…) plutôt que de recopier une valeur hexadécimale.
C'est ce qui évite les divergences silencieuses constatées auparavant : le bleu
primaire existait par exemple en deux versions selon qu'on regardait le thème
global ou la feuille de style locale de la sidebar.
"""

from string import Template

# --- Identité ---
PRIMARY = "#0d6efd"          # aplats et accents (boutons, barre de projet actif)
PRIMARY_HOVER = "#0b5ed7"
PRIMARY_PRESSED = "#0a58ca"
PRIMARY_LIGHT = "#e6f2ff"    # fond des éléments sélectionnés
# Variante foncée réservée au *texte* bleu sur fond clair : PRIMARY manque de
# contraste en petite taille (~3.7:1 sur blanc, contre ~7:1 ici).
PRIMARY_TEXT = "#0056b3"

# --- Surfaces ---
BACKGROUND = "#f8f9fa"       # fond général de la fenêtre et de la sidebar
SURFACE = "#ffffff"          # cartes, champs de saisie, onglet actif
SURFACE_ALT = "#f1f3f5"      # champs désactivés
HOVER = "#e9ecef"            # survol neutre, onglet inactif
PRESSED = "#dee2e6"

# --- Texte ---
TEXT_PRIMARY = "#212529"
TEXT_SECONDARY = "#495057"
TEXT_MUTED = "#adb5bd"

# --- Bordures ---
BORDER = "#dee2e6"
BORDER_INPUT = "#ced4da"
BORDER_HOVER = "#b6bec5"
BORDER_FOCUS = "#80bdff"

# --- Sémantique ---
DANGER = "#dc3545"

# --- Espacements (px) ---
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

# --- Rayons ---
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_PILL = 12

# --- Typographie ---
FONT_FAMILY = '"Segoe UI", "Helvetica Neue", sans-serif'
FONT_SIZE_SM = 11            # légendes, texte d'aide
FONT_SIZE_BASE = 13          # libellés de champs, texte courant
FONT_SIZE_VALUE = 14         # valeurs saisies (champs, tableaux)
FONT_SIZE_TITLE = 15         # titres de section, bandeau de contexte

_TOKENS = {key: value for key, value in dict(globals()).items() if key.isupper()}


def qss(template: str) -> str:
    """Interpole les tokens ($PRIMARY, $SPACE_MD…) dans une feuille de style Qt.

    On passe par string.Template plutôt que par une f-string : le QSS est truffé
    d'accolades qu'il faudrait sinon toutes doubler, ce qui le rendrait illisible.
    """
    return Template(template).substitute(_TOKENS)
