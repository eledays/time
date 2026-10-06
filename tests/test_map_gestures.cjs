const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('app/static/js/app.js', 'utf8');
const handlers = {};
let created = 0, moved = 0;
const listen = (name, callback) => { handlers[name] = callback; };
const context = {
  map: { on: listen, forEachFeatureAtPixel: () => null },
  journeyMapElement: { addEventListener: listen },
  window: { addEventListener: listen },
  activePlaceId: null,
  ol: { proj: { toLonLat: coordinate => coordinate } },
  startNewPlaceEditor: () => created++,
  setPlacementMarker: () => moved++,
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('    const activeMapPointers'), source.indexOf('    map.on("pointermove", (event) => {', source.indexOf('    const activeMapPointers'))), context);
const event = (id, x = 0) => ({ pointerId: id, clientX: x, clientY: 0 });
const click = () => handlers.singleclick({ coordinate: [1, 2], pixel: [1, 2] });
handlers.pointerdown(event(1)); handlers.pointerup(event(1)); click();
assert.equal(created, 1, 'single tap creates a place');
handlers.pointerdown(event(1)); handlers.pointerdown(event(2));
handlers.pointerup(event(2)); handlers.pointerup(event(1)); click();
assert.equal(created, 1, 'pinch without movement cannot create a place');
handlers.pointerdown(event(1)); handlers.pointerup(event(1)); click();
assert.equal(created, 2, 'tap works after pinch');
handlers.pointerdown(event(1)); handlers.pointermove(event(1, 30)); handlers.pointerup(event(1, 30)); click();
assert.equal(created, 2, 'drag cannot create a place');
handlers.pointerdown(event(1)); handlers.pointercancel(event(1)); click();
assert.equal(created, 2, 'cancelled gesture cannot create a place');
context.activePlaceId = 5;
handlers.pointerdown(event(1)); handlers.pointerdown(event(2)); handlers.pointerup(event(1)); handlers.pointerup(event(2)); click();
assert.equal(moved, 0, 'pinch cannot move an edited place');
handlers.pointerdown(event(1)); handlers.pointerup(event(1)); click();
assert.equal(moved, 1, 'single tap moves an edited place');
console.log('7 map gesture checks passed');
