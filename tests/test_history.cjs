const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Node {
  constructor() { this.children = []; this.handlers = {}; this.value = ''; this.dataset = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(fragment) { this.children = fragment.children; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute() {}
  remove() {}
  focus() {}
  querySelector(name) { return nodes[name]; }
}
const nodes = {};
for (const selector of ['[data-history]', '[data-history-search]', 'input', '[data-history-list]', '[data-history-empty]', '[data-history-pagination]', '[data-history-previous]', '[data-history-next]', '[data-history-count]', '[data-history-position]', '[data-history-reset]', 'p']) nodes[selector] = new Node();
nodes['[data-history]'].dataset = { pageSize: '50', page: '1' };
const trips = Array.from({ length: 121 }, (_, i) => ({ id: i + 1, origin: i === 120 ? '<img src=x onerror=alert(1)>' : 'Дом', destination: i % 2 ? 'Работа' : 'Парк', transport: 'Пешком', minutes: 10 }));
const data = new Node(); data.textContent = JSON.stringify(trips);
const document = { querySelector: name => nodes[name], getElementById: () => data, createElement: () => new Node(), createDocumentFragment: () => new Node() };
vm.runInNewContext(fs.readFileSync('app/static/js/history.js', 'utf8'), { document, URLSearchParams });
const list = nodes['[data-history-list]'];
const click = selector => nodes[selector].handlers.click({ preventDefault() {} });
assert.equal(list.children.length, 50);
click('[data-history-next]'); assert.equal(list.children.length, 50);
click('[data-history-next]'); assert.equal(list.children.length, 21);
assert.equal(nodes['[data-history-next]'].hidden, true);
const input = nodes.input;
input.value = '  дОМ   РАБОТА '; input.handlers.input();
assert.equal(list.children.length, 50);
assert.equal(nodes['[data-history-count]'].textContent, '60 найдено');
click('[data-history-next]'); assert.equal(list.children.length, 10);
input.value = 'несуществующее'; input.handlers.input();
assert.equal(list.children.length, 0); assert.equal(nodes['[data-history-empty]'].hidden, false);
input.value = '<img'; input.handlers.input();
assert.equal(list.children.length, 1);
assert.equal(list.children[0].children[0].children[0].children[0].textContent, trips[120].origin);
click('[data-history-reset]'); assert.equal(list.children.length, 50);
console.log('History search, DOM limit, pagination, reset and literal text checks passed');
