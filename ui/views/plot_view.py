# ui/views/plot_view.py
import base64
import json
import re
import tempfile
from pathlib import Path

from html import escape

import plotly
from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton,
                             QFileDialog, QMessageBox)

from ui import theme

# Attente du résultat de l'export PNG (cf. PlotView.export_image).
_EXPORT_POLL_MS = 100
_EXPORT_TIMEOUT_MS = 15_000


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
                /* Réticule et coordonnées du curseur : par-dessus le graphique, sans jamais
                   intercepter la souris (Plotly continue de recevoir clics et survols). */
                .cursor-overlay {{ position: absolute; z-index: 3; pointer-events: none; display: none; }}
                #crosshair-v {{ width: 0; border-left: 1px dashed rgba(73, 80, 87, 0.45); }}
                #crosshair-h {{ height: 0; border-top: 1px dashed rgba(73, 80, 87, 0.45); }}
                #cursor-readout {{ padding: 3px 8px; background: rgba(255, 255, 255, 0.92); border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS_SM}px; font-family: {theme.FONT_FAMILY}; font-size: {theme.FONT_SIZE_SM + 1}px; color: {theme.TEXT_SECONDARY}; white-space: pre; font-variant-numeric: tabular-nums; }}
            </style>
        </head>
        <body>
            <div id="card">
                <div id="graph"></div>
                <div id="crosshair-v" class="cursor-overlay"></div>
                <div id="crosshair-h" class="cursor-overlay"></div>
                <div id="cursor-readout" class="cursor-overlay"></div>
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
                // Python. Sans clé, rien n'est mémorisé. Une vue n'est restaurée que si le
                // cadrage par défaut de la figure n'a pas changé depuis (sinon les données ont
                // bougé et le zoom mémorisé ne correspondrait plus à rien : on repart du
                // cadrage par défaut). Ce cadrage est celui de la figure (profils en travers)
                // ou, si elle n'en a pas (profil en long, en cadrage automatique), l'étendue
                // de ses données, calculée par Python (cf. data_extent).
                var viewMemory = {{}};
                var currentViewKey = null;
                var currentFrame = null;        // cadrage explicite de la figure, ou null
                var currentMemoryFrame = null;  // cadrage qui valide la vue mémorisée
                function frameOf(layout) {{
                    var xr = layout.xaxis && layout.xaxis.range;
                    var yr = layout.yaxis && layout.yaxis.range;
                    return (xr && yr) ? JSON.stringify([xr, yr]) : null;
                }}
                // Vue affichée, telle qu'on la mémorise. En vue orthonormée (profils en
                // travers : 1 m en X = 1 m en Z), on retient le CENTRE et l'ÉCHELLE (mètres par
                // pixel), pas les plages : réappliquées telles quelles sur un graphique d'une
                // autre taille (le panneau de formulaires se masque pour le profil en long et
                // réapparaît au retour), des plages seraient élargies par Plotly pour respecter
                // l'échelle, et la vue grossissait un peu plus à chaque aller-retour.
                function captureView(gd) {{
                    var fl = gd._fullLayout;
                    if (gd.layout.xaxis.autorange === true || gd.layout.yaxis.autorange === true) {{
                        return {{auto: true}};
                    }}
                    var xr = fl.xaxis.range, yr = fl.yaxis.range;
                    if (fl.yaxis.scaleanchor === 'x') {{
                        return {{cx: (xr[0] + xr[1]) / 2, cy: (yr[0] + yr[1]) / 2,
                                upp: (xr[1] - xr[0]) / fl.xaxis._length}};
                    }}
                    return {{x: xr.slice(), y: yr.slice()}};
                }}
                // Plages qui reproduisent une vue mémorisée sur le graphique à sa taille ACTUELLE.
                // Une vue {{fit: plages}} (cf. prepareLayoutChange) montre au moins ces plages :
                // en vue orthonormée, centrée sur elles à l'échelle qui les fait tenir.
                function viewUpdate(gd, view) {{
                    if (view.auto) return {{'xaxis.autorange': true, 'yaxis.autorange': true}};
                    if (view.fit) {{
                        var f = view.fit, flf = gd._fullLayout;
                        if (flf.yaxis.scaleanchor !== 'x') return {{'xaxis.range': f.x, 'yaxis.range': f.y}};
                        return viewUpdate(gd, {{
                            cx: (f.x[0] + f.x[1]) / 2, cy: (f.y[0] + f.y[1]) / 2,
                            upp: Math.max(Math.abs(f.x[1] - f.x[0]) / flf.xaxis._length,
                                          Math.abs(f.y[1] - f.y[0]) / flf.yaxis._length)
                        }});
                    }}
                    if (view.upp !== undefined) {{
                        var fl = gd._fullLayout;
                        var hx = view.upp * fl.xaxis._length / 2, hy = view.upp * fl.yaxis._length / 2;
                        return {{'xaxis.range': [view.cx - hx, view.cx + hx], 'yaxis.range': [view.cy - hy, view.cy + hy]}};
                    }}
                    return {{'xaxis.range': view.x, 'yaxis.range': view.y}};
                }}
                function rememberView() {{
                    var graphDiv = document.getElementById('graph');
                    if (currentViewKey === null || !graphDiv._fullLayout || !graphDiv.layout) return;
                    viewMemory[currentViewKey] = {{frame: currentMemoryFrame, view: captureView(graphDiv)}};
                }}
                // Vue mémorisée en cours de restauration : réappliquée si le graphique change de
                // taille juste après (le redimensionnement du panneau arrive souvent APRÈS le
                // nouveau tracé), jusqu'à la première interaction de l'utilisateur.
                var pendingRestore = null;
                var RESTORE_WINDOW_MS = 1500;
                function applyPendingRestore() {{
                    var gd = document.getElementById('graph');
                    var pending = pendingRestore;
                    if (!pending || currentViewKey !== pending.key || Date.now() > pending.until
                            || !gd._fullLayout || gd.style.display === 'none') {{
                        return;
                    }}
                    var target = viewUpdate(gd, pending.view);
                    var fl = gd._fullLayout;
                    var done = (target['xaxis.range'] && sameRange(fl.xaxis.range, target['xaxis.range'])
                            && sameRange(fl.yaxis.range, target['yaxis.range']))
                        ? Promise.resolve() : Plotly.relayout(gd, target);
                    if (pending.view.fit && layoutChange) {{
                        done.then(function() {{ layoutChange.after = visibleRanges(gd); }});
                    }}
                }}
                function sameRange(a, b) {{
                    var span = Math.abs(b[1] - b[0]) || 1;
                    return Math.abs(a[0] - b[0]) < 1e-6 * span && Math.abs(a[1] - b[1]) < 1e-6 * span;
                }}
                function updateGraph(figData, viewKey, dataExtent) {{
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
                        currentMemoryFrame = currentFrame !== null ? currentFrame
                            : (dataExtent ? JSON.stringify(dataExtent) : null);
                        currentViewKey = (viewKey && currentMemoryFrame !== null) ? viewKey : null;
                        var key = currentViewKey;
                        var saved = key !== null ? viewMemory[key] : null;
                        var restore = (saved && saved.frame === currentMemoryFrame) ? saved.view : null;
                        // Graphique rendu visible AVANT le tracé : masqué, Plotly le tracerait à
                        // une taille par défaut puis le recadrerait au redimensionnement.
                        document.getElementById('graph').style.display = 'block';
                        document.getElementById('empty-state').style.display = 'none';
                        pendingRestore = restore ? {{key: key, view: restore, until: Date.now() + RESTORE_WINDOW_MS}} : null;
                        var reacted = Plotly.react(graphDiv, figData.data, figData.layout, config);
                        attachPlotListeners(graphDiv);
                        if (restore) reacted.then(applyPendingRestore);
                        reacted.then(function() {{ updateCursorReadout(); }});
                    }} catch(err) {{
                        showEmptyState("Erreur d'affichage : " + err.message);
                    }}
                }}
                function showEmptyState(msg) {{
                    rememberView();
                    currentViewKey = null;
                    hideCursorReadout();
                    document.getElementById('graph').style.display = 'none';
                    document.getElementById('empty-state-text').innerHTML = msg || 'Données insuffisantes pour tracer le profil.';
                    document.getElementById('empty-state').style.display = 'flex';
                }}
                // --- Interactions souris (zoom, double-clic, Ctrl + molette) ---

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

                // Position d'un événement souris dans la zone de tracé : pixels (bornés à la
                // zone) et coordonnées de données correspondantes, avec les axes ACTUELS.
                function plotCoords(evt) {{
                    var gd = document.getElementById('graph');
                    var fl = gd._fullLayout;
                    if (!fl || !fl.xaxis || !fl.yaxis || !fl.xaxis._length) return null;
                    var rect = gd.getBoundingClientRect();
                    var px = evt.clientX - rect.left - fl.xaxis._offset;
                    var py = evt.clientY - rect.top - fl.yaxis._offset;
                    var inside = px >= 0 && px <= fl.xaxis._length && py >= 0 && py <= fl.yaxis._length;
                    px = Math.min(Math.max(px, 0), fl.xaxis._length);
                    py = Math.min(Math.max(py, 0), fl.yaxis._length);
                    return {{px: px, py: py, x: fl.xaxis.p2c(px), y: fl.yaxis.p2c(py), inside: inside}};
                }}

                // Suivi des appuis/relâchements sur la zone de tracé (en phase de capture, donc
                // AVANT que Plotly n'applique le zoom) : déplacement de chaque clic, pour ne
                // prendre pour un double-clic que de vrais clics, et cadre de zoom réellement
                // tracé, pour l'appliquer fidèlement (cf. fitZoomBox).
                var MIN_BOX_PX = 8;      // en dessous, Plotly prend le cadre pour un simple clic
                var MAX_CLICK_PX = 3;    // déplacement maximal d'un "vrai" clic
                var pointer = {{down: null, lastMoves: [], pendingBox: null}};
                document.addEventListener('mousedown', function(evt) {{
                    var gd = document.getElementById('graph');
                    var onPlot = evt.button === 0 && evt.target.closest && evt.target.closest('.nsewdrag');
                    if (evt.target.closest && evt.target.closest('#graph')) pendingRestore = null;
                    pointer.pendingBox = null;
                    pointer.down = onPlot && gd._fullLayout ? {{
                        clientX: evt.clientX, clientY: evt.clientY, at: plotCoords(evt),
                        ranges: {{x: gd._fullLayout.xaxis.range.slice(), y: gd._fullLayout.yaxis.range.slice()}}
                    }} : null;
                }}, true);
                document.addEventListener('mouseup', function(evt) {{
                    var down = pointer.down;
                    pointer.down = null;
                    if (!down) return;
                    var moved = Math.hypot(evt.clientX - down.clientX, evt.clientY - down.clientY);
                    pointer.lastMoves = pointer.lastMoves.concat([moved]).slice(-2);
                    var fl = document.getElementById('graph')._fullLayout;
                    var end = plotCoords(evt);
                    if (moved < MIN_BOX_PX || !fl || fl.dragmode !== 'zoom' || !down.at || !end) return;
                    pointer.pendingBox = {{
                        x0: down.at.x, y0: down.at.y, x1: end.x, y1: end.y, ranges: down.ranges,
                        dx: Math.abs(end.px - down.at.px), dy: Math.abs(end.py - down.at.py)
                    }};
                }}, true);

                // Zoom au cadre en vue orthonormée (1 m en X = 1 m en Z) : Plotly élargit
                // l'axe qui ne respecte pas le rapport d'aspect, sans recentrer, si bien qu'un
                // cadre étroit pouvait AGRANDIR la vue et la décaler ("ça dézoome"). On
                // l'applique nous-mêmes : la vue contient tout le cadre tracé, centrée sur lui.
                // Un cadre réduit à une bande (moins de 8 px de haut ou de large) zoome selon
                // l'autre direction en gardant le centre actuel, comme Plotly.
                function fitZoomBox(evt) {{
                    var box = pointer.pendingBox;
                    pointer.pendingBox = null;
                    if (!box || !evt || !('xaxis.range[0]' in evt || 'yaxis.range[0]' in evt)) return;
                    var gd = document.getElementById('graph');
                    var fl = gd._fullLayout;
                    if (fl.yaxis.scaleanchor !== 'x') return;  // profil en long : zoom natif
                    var width = fl.xaxis._length, height = fl.yaxis._length;
                    var spanX = box.dx >= MIN_BOX_PX ? Math.abs(box.x1 - box.x0) : 0;
                    var spanY = box.dy >= MIN_BOX_PX ? Math.abs(box.y1 - box.y0) : 0;
                    var unitsPerPx = Math.max(spanX / width, spanY / height);
                    if (!(unitsPerPx > 0)) return;
                    var cx = spanX ? (box.x0 + box.x1) / 2 : (box.ranges.x[0] + box.ranges.x[1]) / 2;
                    var cy = spanY ? (box.y0 + box.y1) / 2 : (box.ranges.y[0] + box.ranges.y[1]) / 2;
                    var hx = unitsPerPx * width / 2, hy = unitsPerPx * height / 2;
                    Plotly.relayout(gd, {{'xaxis.range': [cx - hx, cx + hx], 'yaxis.range': [cy - hy, cy + hy]}});
                }}

                // Double-clic : seulement pour deux vrais clics. Plotly compte aussi comme
                // double-clic deux petits cadres de zoom (moins de 8 px) tracés à la suite,
                // fréquents quand on est déjà très zoomé : ils ramenaient au cadrage complet.
                // (Pas d'écoute de l'événement "dblclick" du navigateur : Plotly l'intercepte.)
                function onPlotlyDoubleClick() {{
                    var moves = pointer.lastMoves;
                    if (moves.length === 2 && moves[0] <= MAX_CLICK_PX && moves[1] <= MAX_CLICK_PX) {{
                        resetToDefaultView();
                    }}
                }}

                function attachPlotListeners(graphDiv) {{
                    if (graphDiv.__hydrotopoListeners) return;
                    graphDiv.on('plotly_doubleclick', onPlotlyDoubleClick);
                    graphDiv.on('plotly_relayout', fitZoomBox);
                    // Vue déplacée ou zoomée (molette, barre d'outils) sans bouger la souris :
                    // les coordonnées sous le curseur ont changé.
                    graphDiv.on('plotly_relayout', function() {{ updateCursorReadout(); }});
                    graphDiv.__hydrotopoListeners = true;
                }}

                // Ctrl + molette : zoom du graphique autour du curseur (ou du centre si le
                // curseur est hors de la zone de tracé), même facteur sur les deux axes pour
                // garder l'échelle orthonormée. Le zoom de toute l'interface que ferait sinon
                // le moteur web est bloqué partout dans la page.
                document.addEventListener('wheel', function(evt) {{
                    if (!evt.ctrlKey) return;
                    evt.preventDefault();
                    pendingRestore = null;
                    var gd = document.getElementById('graph');
                    var fl = gd._fullLayout;
                    if (!fl || !fl.xaxis || !fl.yaxis || gd.style.display === 'none') return;
                    var at = plotCoords(evt);
                    var xr = fl.xaxis.range, yr = fl.yaxis.range;
                    var cx = at && at.inside ? at.x : (xr[0] + xr[1]) / 2;
                    var cy = at && at.inside ? at.y : (yr[0] + yr[1]) / 2;
                    var factor = Math.pow(1.0015, evt.deltaY);  // molette vers l'avant : zoom avant
                    function scaled(range, center) {{
                        return [center + (range[0] - center) * factor, center + (range[1] - center) * factor];
                    }}
                    Plotly.relayout(gd, {{'xaxis.range': scaled(xr, cx), 'yaxis.range': scaled(yr, cy)}});
                }}, {{passive: false}});

                // --- Coordonnées du curseur ---
                // Réticule en tirets à travers la zone de tracé et cotes X / Z du point visé,
                // dans le coin inférieur droit : pour lire une cote n'importe où, pas seulement
                // sur un point du profil. Masqués hors de la zone de tracé.
                var lastMouse = null;
                function hideCursorReadout() {{
                    ['crosshair-v', 'crosshair-h', 'cursor-readout'].forEach(function(id) {{
                        document.getElementById(id).style.display = 'none';
                    }});
                }}
                function updateCursorReadout(evt) {{
                    if (evt) lastMouse = {{clientX: evt.clientX, clientY: evt.clientY}};
                    var gd = document.getElementById('graph');
                    var at = (lastMouse && gd.style.display !== 'none') ? plotCoords(lastMouse) : null;
                    if (!at || !at.inside) {{
                        hideCursorReadout();
                        return;
                    }}
                    var fl = gd._fullLayout;
                    var x0 = fl.xaxis._offset, y0 = fl.yaxis._offset;
                    var v = document.getElementById('crosshair-v');
                    v.style.left = (x0 + at.px) + 'px';
                    v.style.top = y0 + 'px';
                    v.style.height = fl.yaxis._length + 'px';
                    v.style.display = 'block';
                    var h = document.getElementById('crosshair-h');
                    h.style.top = (y0 + at.py) + 'px';
                    h.style.left = x0 + 'px';
                    h.style.width = fl.xaxis._length + 'px';
                    h.style.display = 'block';
                    var r = document.getElementById('cursor-readout');
                    r.textContent = 'X = ' + at.x.toFixed(2) + ' m   ·   Z = ' + at.y.toFixed(2) + ' m NGF';
                    r.style.display = 'block';
                    r.style.left = (x0 + fl.xaxis._length - r.offsetWidth - 8) + 'px';
                    r.style.top = (y0 + fl.yaxis._length - r.offsetHeight - 8) + 'px';
                }}
                document.addEventListener('mousemove', updateCursorReadout);
                document.documentElement.addEventListener('mouseleave', function() {{
                    lastMouse = null;
                    hideCursorReadout();
                }});

                // --- Agrandir / réduire le graphique (cf. MainWindow.toggle_plot_expanded) ---
                // Appelé par Python juste AVANT de masquer ou réafficher les panneaux voisins :
                // la vue affichée est conservée à travers le changement de taille (appliquée
                // au redimensionnement, comme une vue mémorisée). En vue orthonormée, la zone
                // visible est recadrée pour tenir dans la nouvelle taille ; un aller-retour
                // sans toucher au graphique retrouve exactement la vue de départ (sinon chaque
                // aller-retour l'élargirait un peu plus).
                var layoutChange = null;
                function visibleRanges(gd) {{
                    var fl = gd._fullLayout;
                    return {{x: fl.xaxis.range.slice(), y: fl.yaxis.range.slice()}};
                }}
                function prepareLayoutChange() {{
                    var gd = document.getElementById('graph');
                    if (!gd._fullLayout || !gd.layout || gd.style.display === 'none') return;
                    var visible = visibleRanges(gd);
                    var back = layoutChange, view;
                    if (back && back.key === currentViewKey && back.after
                            && sameRange(visible.x, back.after.x) && sameRange(visible.y, back.after.y)) {{
                        view = back.before;
                        layoutChange = null;
                    }} else {{
                        var before = captureView(gd);
                        view = before.auto ? before : {{fit: visible}};
                        layoutChange = {{key: currentViewKey, before: before, after: null}};
                    }}
                    pendingRestore = {{key: currentViewKey, view: view, until: Date.now() + RESTORE_WINDOW_MS}};
                }}

                // --- Export PNG (bouton "Exporter l'image") ---
                // Plotly.toImage est asynchrone et runJavaScript ne sait pas attendre une
                // promesse : Python lance l'export puis vient chercher le résultat (data URL
                // "data:image/png;base64,...", ou "error:<message>").
                var exportedImage = null;
                // Hauteur (px) du bandeau ajouté en haut de l'image pour la légende.
                var CAPTION_HEIGHT = 30;
                function startImageExport(caption) {{
                    exportedImage = null;
                    var gd = document.getElementById('graph');
                    if (!gd._fullLayout || gd.style.display === 'none') {{
                        exportedImage = 'error:Aucun graphique affiché.';
                        return;
                    }}
                    // Taille affichée explicite : sans elle, Plotly exporte en 700 x 450 px
                    // quelle que soit la taille du graphique à l'écran.
                    var size = {{width: gd._fullLayout.width, height: gd._fullLayout.height}};
                    // Légende (projet › scénario › profil — vue) en titre, au-dessus du titre
                    // du graphique. Elle occupe un bandeau AJOUTÉ en haut de l'image : la zone
                    // de tracé garde sa taille, donc exactement le cadrage affiché.
                    var layout = Object.assign({{}}, gd.layout);
                    if (caption) {{
                        var margin = Object.assign({{}}, gd.layout.margin);
                        margin.t = (margin.t !== undefined ? margin.t : 100) + CAPTION_HEIGHT;
                        layout.margin = margin;
                        var title = gd.layout.title && gd.layout.title.text;
                        layout.title = Object.assign({{}}, gd.layout.title, {{
                            text: '<b>' + caption + '</b>'
                                + (title ? '<br><span style="font-size:12px">' + title + '</span>' : '')
                        }});
                        size.height += CAPTION_HEIGHT;
                    }}
                    Plotly.toImage({{data: gd.data, layout: layout}},
                                   {{format: 'png', scale: 2, width: size.width, height: size.height}}).then(
                        function(url) {{ exportedImage = url; }},
                        function(err) {{ exportedImage = 'error:' + err.message; }}
                    );
                }}
                function takeExportedImage() {{
                    var value = exportedImage;
                    exportedImage = null;
                    return value;
                }}

                // Le QWebEngineView change de taille avec la fenêtre principale et les
                // splitters ; Plotly ne le détecte pas seul, d'où ce ResizeObserver. Rien à
                // redimensionner tant que le graphique est masqué (message d'attente) : Plotly
                // rejetterait l'appel ("Resize must be passed a displayed plot div element").
                new ResizeObserver(function() {{
                    var gd = document.getElementById('graph');
                    if (gd._fullLayout && gd.style.display !== 'none') {{
                        Plotly.Plots.resize(gd).then(applyPendingRestore);
                    }}
                }}).observe(document.getElementById('card'));
            </script>
        </body>
        </html>
    """


class PlotView(QWidget):
    # Bouton "Agrandir" / "Réduire" : MainWindow masque ou réaffiche les panneaux voisins.
    expand_toggled = pyqtSignal()

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
        
        button_style = theme.qss("""
            QPushButton { background-color: $SURFACE; color: $TEXT_SECONDARY; border: 1px solid $BORDER_INPUT; border-radius: ${RADIUS_MD}px; padding: ${SPACE_SM}px ${SPACE_MD}px; font-weight: bold; }
            QPushButton:hover { background-color: $BACKGROUND; border-color: $BORDER_HOVER; }
        """)
        self.btn_expand = QPushButton()
        self.btn_expand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand.setStyleSheet(button_style)
        self.btn_expand.clicked.connect(self.expand_toggled.emit)
        self.header_layout.addWidget(self.btn_expand)
        self.set_expanded(False)

        self.btn_export = QPushButton("📷 Exporter l'image")
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.setStyleSheet(button_style)
        self.btn_export.setToolTip("Enregistre le graphique affiché (zoom compris) en image PNG.")
        self.btn_export.clicked.connect(self.export_image)
        self.header_layout.addWidget(self.btn_export)
        # Nom de fichier proposé à l'export (sans extension), mis à jour par MainWindow selon
        # ce qui est affiché.
        self.export_name = "graphique"
        # Légende écrite en haut de l'image exportée (projet › scénario › profil — vue),
        # mise à jour par MainWindow ; vide = pas de légende.
        self.export_caption = ""
        self.main_layout.addLayout(self.header_layout)
        
        # --- MOTEUR WEB ---
        self.browser = QWebEngineView()
        self.main_layout.addWidget(self.browser)
        
        self._is_ready = False
        self._pending_fig = None
        self._pending_view_key = None
        self._has_figure = False
        # Export PNG en cours : chemin de destination et nombre de relances de l'attente.
        self._export_path = None
        self._export_polls = 0
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
        "profile:12:existing", "scenario:3:longitudinal") : le zoom de l'utilisateur sur
        cette vue est mémorisé et retrouvé quand il y revient après avoir affiché autre
        chose. Sans clé, aucune mémoire."""
        if not self._is_ready:
            self._pending_fig = fig
            self._pending_view_key = view_key
            return

        self._has_figure = fig is not None
        if fig is None:
            message = error_message or 'Données insuffisantes pour tracer le profil.'
            self.browser.page().runJavaScript(f"showEmptyState({json.dumps(message)});")
            return

        fig_json = fig.to_json()
        extent = json.dumps(data_extent(fig))
        self.browser.page().runJavaScript(f"updateGraph({fig_json}, {json.dumps(view_key)}, {extent});")

    # --- Agrandir / réduire ---

    def set_expanded(self, expanded: bool):
        """Libellé du bouton selon que le graphique occupe toute la fenêtre ou non."""
        if expanded:
            self.btn_expand.setText("⛶ Réduire")
            self.btn_expand.setToolTip("Revenir à l'affichage normal (Échap).")
        else:
            self.btn_expand.setText("⛶ Agrandir")
            self.btn_expand.setToolTip(
                "Afficher le graphique dans toute la fenêtre (Échap pour revenir)."
            )

    def prepare_layout_change(self, then):
        """À appeler juste avant de changer la taille du graphique (Agrandir / Réduire) :
        la page note la vue affichée pour la conserver, puis `then` est exécuté. Attendre la
        page garantit qu'elle note la vue AVANT le redimensionnement."""
        if not self._is_ready or not self._has_figure:
            then()
            return
        self.browser.page().runJavaScript("prepareLayoutChange();", lambda _result: then())

    # --- Export PNG ---

    def export_image(self):
        """Bouton "Exporter l'image" : enregistre le graphique affiché, tel qu'il est zoomé,
        en PNG (2x la résolution d'écran) à l'emplacement choisi. Plotly génère l'image de
        façon asynchrone côté page : on lance l'export puis on vient chercher le résultat."""
        if not self._is_ready or not self._has_figure:
            QMessageBox.information(self, "Exporter l'image", "Aucun graphique à exporter.")
            return
        if self._export_path is not None:
            return  # export déjà en cours

        name = re.sub(r'[\\/:*?"<>|]', "_", self.export_name or "graphique")
        path, _ = QFileDialog.getSaveFileName(self, "Exporter l'image", f"{name}.png", "Image PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"

        self._export_path = path
        self._export_polls = 0
        # Échappement : Plotly interprète le texte de la légende comme du HTML simplifié.
        caption = json.dumps(escape(self.export_caption or "", quote=False))
        self.browser.page().runJavaScript(f"startImageExport({caption});")
        QTimer.singleShot(_EXPORT_POLL_MS, self._poll_export)

    def _poll_export(self):
        self.browser.page().runJavaScript("takeExportedImage();", self._on_export_result)

    def _on_export_result(self, value):
        if self._export_path is None:
            return
        if not value:
            self._export_polls += 1
            if self._export_polls * _EXPORT_POLL_MS < _EXPORT_TIMEOUT_MS:
                QTimer.singleShot(_EXPORT_POLL_MS, self._poll_export)
                return
            value = "error:délai dépassé"

        path, self._export_path = self._export_path, None
        try:
            if value.startswith("error:"):
                raise ValueError(value[len("error:"):])
            save_png_data_url(path, value)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Export impossible", f"L'image n'a pas pu être enregistrée :\n{e}")


def save_png_data_url(path, data_url: str) -> None:
    """Écrit dans `path` l'image PNG d'une data URL "data:image/png;base64,...". Lève
    ValueError si ce n'est pas une image PNG, OSError si le fichier ne peut être écrit."""
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise ValueError("format d'image inattendu")
    Path(path).write_bytes(base64.b64decode(data_url[len(prefix):]))


def data_extent(fig):
    """Étendue [[x min, x max], [z min, z max]] des données tracées par `fig`, ou None si
    elle ne trace aucun point. Sert, pour une figure en cadrage automatique (profil en
    long), à savoir si une vue mémorisée vaut encore : tant que l'étendue ne change pas,
    le zoom de l'utilisateur est retrouvé ; sinon on repart du cadrage par défaut."""
    xs, ys = [], []
    for trace in fig.data:
        for x, y in zip(getattr(trace, "x", None) or (), getattr(trace, "y", None) or ()):
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                xs.append(float(x))
                ys.append(float(y))
    if not xs:
        return None
    return [[min(xs), max(xs)], [min(ys), max(ys)]]
