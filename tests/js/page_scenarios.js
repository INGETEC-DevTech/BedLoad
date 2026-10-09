// Scénarios souris du profil en long et de la case « Échelle orthonormée » (cf.
// tests/test_plot_page_script.py). Zone de tracé simulée : 800 x 400 px, décalée de
// (60, 40) px. Les libellés restent sans accents : la console de JScript les abîme.
var failures = [], passes = 0;
function check(name, cond) { if (cond) passes++; else failures.push(name); }
function near(a, b) { return Math.abs(a - b) < 1e-9 * Math.max(1, Math.abs(b)); }
function nearRange(r, a, b) { return r && near(r[0], a) && near(r[1], b); }
function target(cls, inGraph) {
    return {cls: cls, closest: function(sel) {
        if (sel === '#graph') return inGraph ? gd : null;
        return (this.cls && sel.indexOf(this.cls) >= 0) ? this : null; }};
}
function fire(type, props) {
    var evt = props; evt.stopped = false; evt.prevented = false;
    evt.stopPropagation = function() { this.stopped = true; };
    evt.preventDefault = function() { this.prevented = true; };
    if (!evt.target) evt.target = target('', true);
    var list = listeners[type] || [];
    for (var i = 0; i < list.length; i++) list[i](evt);
    return evt;
}
var E = Math.exp(1);
// Bande de l'axe X : sous la zone de tracé (py > 400) ; de l'axe Y : à sa gauche (px < 0).
var X_BAND_Y = 40 + 400 + 20, Y_BAND_X = 30;

setFreeAxes(true);
// 1. Glisser vers la droite sur l'axe X : étire X seul, autour du centre de la vue.
resetLayout([0, 300], [45, 50]);
var down = fire('mousedown', {button: 0, clientX: 460, clientY: X_BAND_Y, target: target('ewdrag', true)});
check('1 appui sur axe X intercepte', down.stopped && down.prevented);
fire('mousemove', {clientX: 610, clientY: X_BAND_Y, buttons: 1});
check('1 X etire de e autour du centre', nearRange(gd._fullLayout.xaxis.range, 150 - 150 / E, 150 + 150 / E));
check('1 Y inchange', nearRange(gd._fullLayout.yaxis.range, 45, 50));
check('1 curseur ew pendant le glissement', gd.classList.contains('over-x-axis'));
fire('mouseup', {});
fire('mousemove', {clientX: 700, clientY: X_BAND_Y, buttons: 0});
check('1 plus de relayout apres relachement', relayouts.length === 1);

// 2. Glisser vers le haut sur l'axe Y : étire Y seul ; vers le bas : comprime.
resetLayout([0, 300], [45, 50]);
fire('mousedown', {button: 0, clientX: Y_BAND_X, clientY: 240});
fire('mousemove', {clientX: Y_BAND_X, clientY: 90, buttons: 1});
check('2 Y etire de e autour du centre', nearRange(gd._fullLayout.yaxis.range, 47.5 - 2.5 / E, 47.5 + 2.5 / E));
check('2 X inchange', nearRange(gd._fullLayout.xaxis.range, 0, 300));
check('2 curseur ns', gd.classList.contains('over-y-axis') && !gd.classList.contains('over-x-axis'));
fire('mousemove', {clientX: Y_BAND_X, clientY: 390, buttons: 1});
check('2 Y comprime vers le bas', nearRange(gd._fullLayout.yaxis.range, 47.5 - 2.5 * E, 47.5 + 2.5 * E));
fire('mouseup', {});
resetLayout([0, 300], [45, 50]);
fire('mousedown', {button: 0, clientX: 460, clientY: X_BAND_Y});
fire('mousemove', {clientX: 310, clientY: X_BAND_Y, buttons: 1});
check('2b X comprime vers la gauche', nearRange(gd._fullLayout.xaxis.range, 150 - 150 * E, 150 + 150 * E));
fire('mouseup', {});
// Bouton relâché hors de la page (aucun mouseup reçu) : le glissement s'arrête.
resetLayout([0, 300], [45, 50]);
fire('mousedown', {button: 0, clientX: 460, clientY: X_BAND_Y});
fire('mousemove', {clientX: 500, clientY: 200, buttons: 0});
check('2c glissement abandonne sans bouton', relayouts.length === 0 && !gd.classList.contains('over-x-axis'));

// 3. Molette au-dessus de l'axe X : X seul, autour du curseur (X = 75 m).
resetLayout([0, 300], [45, 50]);
var wheel = fire('wheel', {clientX: 260, clientY: X_BAND_Y, deltaY: -100, ctrlKey: false});
var f = Math.pow(1.0015, -100);
check('3 molette interceptee', wheel.prevented);
check('3 X zoome autour du curseur', nearRange(gd._fullLayout.xaxis.range, 75 - 75 * f, 75 + 225 * f));
check('3 Y inchange', nearRange(gd._fullLayout.yaxis.range, 45, 50));
resetLayout([0, 300], [45, 50]);
fire('wheel', {clientX: Y_BAND_X, clientY: 140, deltaY: 100, ctrlKey: false});
var g = Math.pow(1.0015, 100);
check('3b Y dezoome autour du curseur', nearRange(gd._fullLayout.yaxis.range, 48.75 - 3.75 * g, 48.75 + 1.25 * g));
check('3b X inchange', nearRange(gd._fullLayout.xaxis.range, 0, 300));
resetLayout([0, 300], [45, 50]);
var inside = fire('wheel', {clientX: 300, clientY: 200, deltaY: -100, ctrlKey: false});
check('3c molette sur la zone de trace : rien', !inside.prevented && relayouts.length === 0);

// 4. Échelle orthonormée : l'autre axe suit, le rapport est conservé.
resetLayout([0, 300], [0, 150], 'x');
fire('mousedown', {button: 0, clientX: 460, clientY: X_BAND_Y});
fire('mousemove', {clientX: 610, clientY: X_BAND_Y, buttons: 1});
fire('mouseup', {});
var fl = gd._fullLayout;
var uppX = (fl.xaxis.range[1] - fl.xaxis.range[0]) / 800, uppY = (fl.yaxis.range[1] - fl.yaxis.range[0]) / 400;
check('4 rapport 1:1 conserve (glisser)', near(uppX, uppY) && near(uppX, 0.375 / E));
resetLayout([0, 300], [0, 150], 'x');
fire('wheel', {clientX: Y_BAND_X, clientY: 140, deltaY: -200, ctrlKey: false});
fl = gd._fullLayout;
check('4 rapport 1:1 conserve (molette)',
      near((fl.xaxis.range[1] - fl.xaxis.range[0]) / 800, (fl.yaxis.range[1] - fl.yaxis.range[0]) / 400));

// 5. Ailleurs (zone de tracé, Ctrl + molette, profils en travers) : rien ne change.
resetLayout([0, 300], [45, 50]);
var onPlot = fire('mousedown', {button: 0, clientX: 300, clientY: 200, target: target('nsewdrag', true)});
check('5 appui sur la zone de trace laisse a Plotly', !onPlot.stopped && relayouts.length === 0);
fire('mouseup', {});
fire('wheel', {clientX: 260, clientY: X_BAND_Y, deltaY: -100, ctrlKey: true});
check('5 Ctrl + molette : les deux axes', relayouts.length === 1 && relayouts[0]['yaxis.range'] !== undefined);
fire('mousemove', {clientX: 300, clientY: 200, buttons: 0});
check('5 pas de curseur d axe sur la zone de trace', !gd.classList.contains('over-x-axis') && !gd.classList.contains('over-y-axis'));
fire('mousemove', {clientX: 460, clientY: X_BAND_Y, buttons: 0});
check('5 curseur ew au survol de l axe X', gd.classList.contains('over-x-axis'));
setFreeAxes(false);
check('5 curseur retire en quittant le profil en long', !gd.classList.contains('over-x-axis'));
resetLayout([0, 300], [45, 50]);
var cross = fire('mousedown', {button: 0, clientX: 460, clientY: X_BAND_Y, target: target('ewdrag', true)});
fire('wheel', {clientX: 260, clientY: X_BAND_Y, deltaY: -100, ctrlKey: false});
fire('mousemove', {clientX: 460, clientY: X_BAND_Y, buttons: 0});
check('5 profil en travers : axes laisses a Plotly', !cross.stopped && relayouts.length === 0 && !gd.classList.contains('over-x-axis'));
setFreeAxes(true);

// 6. Case « Échelle orthonormée ».
resetLayout([0, 300], [45, 50]);
setOrthonormal(true);
var u = relayouts[0];
check('6 cochee : ancrage 1:1', u['yaxis.scaleanchor'] === 'x' && u['yaxis.scaleratio'] === 1);
check('6 cochee : X garde, Y recentre a la meme echelle',
      nearRange(u['xaxis.range'], 0, 300) && nearRange(u['yaxis.range'], 47.5 - 75, 47.5 + 75));
resetLayout([0, 300], [-27.5, 122.5], 'x');
setOrthonormal(false);
u = relayouts[0];
check('6 decochee : axes independants, vue gardee', u['yaxis.scaleanchor'] === null
      && nearRange(u['xaxis.range'], 0, 300) && nearRange(u['yaxis.range'], -27.5, 122.5));
resetLayout([0, 300], [45, 50]);
gd.layout.xaxis.autorange = true; gd.layout.yaxis.autorange = true;
setOrthonormal(true);
u = relayouts[0];
check('6 cadrage automatique : laisse a Plotly', u['yaxis.scaleanchor'] === 'x' && u['xaxis.range'] === undefined && u['yaxis.range'] === undefined);

// 7. Double-clic (retour au cadrage par défaut) : la case reste dans son état.
resetLayout([10, 20], [0, 5], 'x');
currentFrame = null;
resetToDefaultView();
u = relayouts[0];
check('7 double-clic : cadrage automatique sans toucher a l echelle',
      u['xaxis.autorange'] === true && u['yaxis.autorange'] === true && u['yaxis.scaleanchor'] === undefined
      && gd._fullLayout.yaxis.scaleanchor === 'x');

WScript.Echo(passes + ' verifications reussies, ' + failures.length + ' echec(s)' + (failures.length ? ' : ' + failures.join(' | ') : ''));
WScript.Quit(failures.length ? 1 : 0);
