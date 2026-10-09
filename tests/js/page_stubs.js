// Faux DOM et faux Plotly, juste ce qu'il faut pour exécuter le script de la page
// (cf. tests/test_plot_page_script.py) avec JScript : ES3, d'où les compléments ci-dessous.
// Plotly.relayout applique les plages demandées, sans rien recalculer.
if (!Array.prototype.forEach) Array.prototype.forEach = function(f) { for (var i = 0; i < this.length; i++) f(this[i], i); };
if (!Math.hypot) Math.hypot = function(a, b) { return Math.sqrt(a * a + b * b); };
var listeners = {};
function ClassList() { this.set = {}; }
ClassList.prototype.toggle = function(n, force) { if (force) this.set[n] = true; else delete this.set[n]; };
ClassList.prototype.contains = function(n) { return !!this.set[n]; };
function El(id) { this.id = id; this.style = {display: 'block'}; this.classList = new ClassList(); }
El.prototype.getBoundingClientRect = function() { return {left: 0, top: 0}; };
var els = {};
var ids = ['graph', 'empty-state', 'empty-state-text', 'crosshair-v', 'crosshair-h', 'cursor-readout', 'card'];
for (var i = 0; i < ids.length; i++) els[ids[i]] = new El(ids[i]);
var document = {
    addEventListener: function(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    getElementById: function(id) { return els[id]; },
    documentElement: {addEventListener: function() {}}
};
function ResizeObserver() { this.observe = function() {}; }
var relayouts = [];
var Plotly = {
    Icons: {home: {}},
    relayout: function(gd, update) {
        relayouts.push(update);
        var fl = gd._fullLayout;
        for (var k in update) {
            var v = update[k];
            if (k === 'xaxis.range') { fl.xaxis.range = v.slice(); gd.layout.xaxis.autorange = false; }
            if (k === 'yaxis.range') { fl.yaxis.range = v.slice(); gd.layout.yaxis.autorange = false; }
            if (k === 'yaxis.scaleanchor') { fl.yaxis.scaleanchor = v; }
        }
        return {then: function(f) { f(); return this; }};
    }
};
var gd = els['graph'];
function axis(offset, length, range, flip) {
    return {_offset: offset, _length: length, range: range, p2c: function(p) {
        var r = this.range;
        return flip ? r[1] - p * (r[1] - r[0]) / this._length : r[0] + p * (r[1] - r[0]) / this._length; }};
}
function resetLayout(xr, yr, anchor) {
    gd._fullLayout = {xaxis: axis(60, 800, xr), yaxis: axis(40, 400, yr, true), dragmode: 'pan'};
    gd._fullLayout.yaxis.scaleanchor = anchor;
    gd.layout = {xaxis: {autorange: false}, yaxis: {autorange: false}};
    relayouts = [];
}
