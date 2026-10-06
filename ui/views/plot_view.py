# ui/views/plot_view.py
import json
import tempfile
from pathlib import Path

import plotly
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton

from ui import theme

def _get_or_create_plotly_cache_dir() -> tuple[Path, str]:
    cache_dir = Path(tempfile.gettempdir()) / "hydrotopo_plotly_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    js_path = cache_dir / f"plotly-{plotly.__version__}.min.js"
    if not js_path.exists():
        js_path.write_text(plotly.offline.get_plotlyjs(), encoding="utf-8")
    return cache_dir, js_path.name

def _build_page_html(plotly_js_filename: str) -> str:
    """Page HTML hébergée par le QWebEngineView : un conteneur Plotly plus l'écran
    d'attente, et les fonctions JS (updateGraph / showEmptyState) appelées depuis Python
    (cf. PlotView.update_plot). Fonction de module, sans dépendance à Qt, pour pouvoir
    charger exactement cette page dans un navigateur ordinaire."""
    return f"""
        <html>
        <head>
            <script type="text/javascript" src="{plotly_js_filename}"></script>
            <style>
                body {{ margin: 0; padding: 0; background-color: transparent; height: 100vh; overflow: hidden; }}
                #card {{ position: relative; width: 100%; height: 100%; background-color: {theme.SURFACE}; border-radius: 10px; border: 1px solid {theme.BORDER}; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05); overflow: hidden; }}
                #graph {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; }}
                #empty-state {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 2; display: flex; flex-direction: column; justify-content: center; align-items: center; background-color: {theme.SURFACE}; font-family: {theme.FONT_FAMILY}; color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_TITLE}px; }}
                .icon-placeholder {{ margin-bottom: {theme.SPACE_LG}px; opacity: 0.5; }}
            </style>
        </head>
        <body>
            <div id="card">
                <div id="graph"></div>
                <div id="empty-state">
                    <svg class="icon-placeholder" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M3 3v18h18"/><path d="M18 9l-5 5-4-4-4 4"/>
                    </svg>
                    <span id="empty-state-text">Chargement du moteur graphique...</span>
                </div>
            </div>
            <script>
                // Mémoire des vues : le zoom/déplacement fait par l'utilisateur sur une vue
                // (un profil, un onglet) est retrouvé quand il la quitte pour une autre (ex.
                // le profil en long) puis y revient. Plotly (uirevision) ne le garde qu'entre
                // deux figures successives, d'où cette mémoire par clé de vue, fournie par
                // Python. Sans clé, ou si la figure n'a pas de cadrage explicite (profil en
                // long), rien n'est mémorisé. Une vue n'est restaurée que si le cadrage par
                // défaut de la figure n'a pas changé depuis (sinon les données ont bougé et le
                // zoom mémorisé ne correspondrait plus à rien : on repart du cadrage par défaut).
                var viewMemory = {{}};
                var currentViewKey = null;
                var currentFrame = null;
                function frameOf(layout) {{
                    var xr = layout.xaxis && layout.xaxis.range;
                    var yr = layout.yaxis && layout.yaxis.range;
                    return (xr && yr) ? JSON.stringify([xr, yr]) : null;
                }}
                function snapshotView(layout) {{
                    return {{
                        x: layout.xaxis.range ? layout.xaxis.range.slice() : null,
                        y: layout.yaxis.range ? layout.yaxis.range.slice() : null,
                        xauto: layout.xaxis.autorange === true,
                        yauto: layout.yaxis.autorange === true
                    }};
                }}
                function rememberView() {{
                    var graphDiv = document.getElementById('graph');
                    if (currentViewKey === null || !graphDiv.layout) return;
                    viewMemory[currentViewKey] = {{ frame: currentFrame, view: snapshotView(graphDiv.layout) }};
                }}
                function viewUpdate(view) {{
                    var update = {{}};
                    ['x', 'y'].forEach(function(axis) {{
                        if (view[axis + 'auto']) {{
                            update[axis + 'axis.autorange'] = true;
                        }} else {{
                            update[axis + 'axis.range'] = view[axis];
                        }}
                    }});
                    return update;
                }}
                function updateGraph(figData, viewKey) {{
                    try {{
                        if (typeof Plotly === 'undefined') return;
                        var graphDiv = document.getElementById('graph');
                        // Double-clic et bouton "Réinitialiser" : notre propre retour au cadrage
                        // par défaut (cf. resetToDefaultView) à la place de celui de Plotly.
                        var config = {{
                            displaylogo: false, displayModeBar: 'hover', doubleClick: false,
                            modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d', 'resetScale2d'],
                            modeBarButtonsToAdd: [{{
                                name: 'resetDefaultView', title: 'Revenir au cadrage par défaut',
                                icon: Plotly.Icons.home, click: resetToDefaultView
                            }}]
                        }};
                        rememberView();
                        currentFrame = frameOf(figData.layout);
                        if (currentFrame === null && figData.layout.xaxis && figData.layout.yaxis) {{
                            // Pas de cadrage explicite (profil en long) : on impose le cadrage
                            // automatique. Sinon uirevision peut conserver l'état "cadrage
                            // automatique désactivé" laissé par le zoom d'une autre vue, et
                            // afficher une plage par défaut vide.
                            figData.layout.xaxis.autorange = true;
                            figData.layout.yaxis.autorange = true;
                        }}
                        currentViewKey = (viewKey && currentFrame !== null) ? viewKey : null;
                        var key = currentViewKey;
                        var saved = key !== null ? viewMemory[key] : null;
                        var restore = (saved && saved.frame === currentFrame) ? saved.view : null;
                        var reacted = Plotly.react(graphDiv, figData.data, figData.layout, config);
                        document.getElementById('graph').style.display = 'block';
                        document.getElementById('empty-state').style.display = 'none';
                        Plotly.Plots.resize(graphDiv);
                        if (restore) {{
                            reacted.then(function() {{
                                if (currentViewKey !== key) return;
                                if (JSON.stringify(snapshotView(graphDiv.layout)) !== JSON.stringify(restore)) {{
                                    Plotly.relayout(graphDiv, viewUpdate(restore));
                                }}
                            }});
                        }}
                    }} catch(err) {{
                        showEmptyState("Erreur d'affichage : " + err.message);
                    }}
                }}
                function showEmptyState(msg) {{
                    rememberView();
                    currentViewKey = null;
                    document.getElementById('graph').style.display = 'none';
                    document.getElementById('empty-state-text').innerHTML = msg || 'Données insuffisantes pour tracer le profil.';
                    document.getElementById('empty-state').style.display = 'flex';
                }}
                // Retour au cadrage par défaut de la figure AFFICHÉE : ses plages explicites
                // (currentFrame : profils en travers), ou le cadrage automatique sur toutes
                // ses données (profil en long). Le "reset" natif de Plotly revient aux plages
                // du premier affichage, qui avec Plotly.react peuvent être celles d'une autre
                // vue (constaté : un double-clic sur le profil en long ramenait au cadrage de
                // l'onglet Hydraulique). La vue ainsi retrouvée est mémorisée comme une autre.
                function resetToDefaultView() {{
                    var graphDiv = document.getElementById('graph');
                    if (!graphDiv.layout || graphDiv.style.display === 'none') return;
                    if (currentFrame !== null) {{
                        var frame = JSON.parse(currentFrame);
                        Plotly.relayout(graphDiv, {{'xaxis.range': frame[0], 'yaxis.range': frame[1]}});
                    }} else {{
                        Plotly.relayout(graphDiv, {{'xaxis.autorange': true, 'yaxis.autorange': true}});
                    }}
                }}
                document.getElementById('graph').addEventListener('dblclick', resetToDefaultView);

                // Le QWebEngineView change de taille avec la fenêtre principale et les
                // splitters ; Plotly ne le détecte pas seul, d'où ce ResizeObserver.
                new ResizeObserver(function() {{
                    Plotly.Plots.resize(document.getElementById('graph'));
                }}).observe(document.getElementById('card'));
            </script>
        </body>
        </html>
    """


class PlotView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG
        )
        self.main_layout.setSpacing(theme.SPACE_LG)
        
        # --- EN-TÊTE ---
        self.header_layout = QHBoxLayout()
        self.lbl_title = QLabel("Visualisation de la coupe transversale")
        self.lbl_title.setStyleSheet(theme.qss(
            "font-size: 16px; font-weight: bold; color: $TEXT_PRIMARY;"
        ))
        self.header_layout.addWidget(self.lbl_title)
        
        self.header_layout.addStretch() 
        
        self.btn_export = QPushButton("📷 Exporter l'image")
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.setStyleSheet(theme.qss("""
            QPushButton { background-color: $SURFACE; color: $TEXT_SECONDARY; border: 1px solid $BORDER_INPUT; border-radius: ${RADIUS_MD}px; padding: ${SPACE_SM}px ${SPACE_MD}px; font-weight: bold; }
            QPushButton:hover { background-color: $BACKGROUND; border-color: $BORDER_HOVER; }
        """))
        self.header_layout.addWidget(self.btn_export)
        self.main_layout.addLayout(self.header_layout)
        
        # --- MOTEUR WEB ---
        self.browser = QWebEngineView()
        self.main_layout.addWidget(self.browser)
        
        self._is_ready = False
        self._pending_fig = None
        self._pending_view_key = None
        self.browser.loadFinished.connect(self.on_page_loaded)

        cache_dir, plotly_js_filename = _get_or_create_plotly_cache_dir()
        
        html_base = _build_page_html(plotly_js_filename)
        
        # Écriture du fichier et chargement (L'étape qui manquait !)
        html_path = cache_dir / "index.html"
        html_path.write_text(html_base, encoding="utf-8")
        self.browser.load(QUrl.fromLocalFile(str(html_path)))
        
    def on_page_loaded(self, ok: bool):
        if not ok: return
        self._is_ready = True
        
        # S'il y a un graphique en attente, on l'affiche. 
        # Sinon, on efface "Chargement..." pour afficher un texte d'accueil stylisé.
        if self._pending_fig is not None:
            self.update_plot(self._pending_fig, view_key=self._pending_view_key)
            self._pending_fig = None
        else:
            self.browser.page().runJavaScript("showEmptyState('👈 Sélectionnez un scénario ou un profil pour commencer');")

    def update_plot(self, fig, error_message: str = None, view_key: str = None):
        """Affiche `fig` (ou un message si None). `view_key` identifie la vue affichée (ex.
        "profile:12:existing") : le zoom de l'utilisateur sur cette vue est mémorisé et
        retrouvé quand il y revient après avoir affiché autre chose. Sans clé, aucune
        mémoire (ex. profil en long)."""
        if not self._is_ready:
            self._pending_fig = fig
            self._pending_view_key = view_key
            return

        if fig is None:
            message = error_message or 'Données insuffisantes pour tracer le profil.'
            self.browser.page().runJavaScript(f"showEmptyState({json.dumps(message)});")
            return

        fig_json = fig.to_json()
        self.browser.page().runJavaScript(f"updateGraph({fig_json}, {json.dumps(view_key)});")