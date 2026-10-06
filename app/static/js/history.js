"use strict";

(() => {
  const root = document.querySelector("[data-history]");
  if (!root) return;
  const dataElement = document.getElementById("history-data");
  let trips;
  try {
    trips = JSON.parse(dataElement.textContent);
    if (!Array.isArray(trips)) return;
  } catch (_) {
    return; // Keep the server-rendered search and pagination usable.
  }
  const normalize = (value) => value.toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ").trim();
  const indexed = trips.map((trip) => ({ trip, origin: normalize(trip.origin), destination: normalize(trip.destination) }));
  // Keep personal history only in this page's memory, never in browser storage.
  dataElement.remove();
  const form = root.querySelector("[data-history-search]");
  const input = form.querySelector("input");
  const list = root.querySelector("[data-history-list]");
  const empty = root.querySelector("[data-history-empty]");
  const pagination = root.querySelector("[data-history-pagination]");
  const previous = root.querySelector("[data-history-previous]");
  const next = root.querySelector("[data-history-next]");
  const pageSize = Number(root.dataset.pageSize);
  let page = Number(root.dataset.page);
  let matches = [];
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const card = (trip) => {
    const link = element("a", "journey-card-link");
    link.href = `/trips/${trip.id}`;
    const article = element("article", "journey-card journey-card-compact");
    const route = element("div", "journey-route");
    const origin = element("strong", "", trip.origin);
    origin.title = trip.origin;
    const destination = element("strong", "", trip.destination);
    destination.title = trip.destination;
    const arrow = element("span", "material-symbols-rounded route-arrow", "chevron_right");
    arrow.setAttribute("aria-hidden", "true");
    route.append(origin, arrow, destination);
    const meta = element("div", "journey-meta");
    meta.append(element("span", "", trip.transport));
    const duration = element("b", "", `${trip.minutes} `);
    duration.append(element("small", "", "мин"));
    article.append(route, meta, duration);
    link.append(article);
    return link;
  };
  const render = () => {
    const pageCount = Math.max(1, Math.ceil(matches.length / pageSize));
    page = Math.min(Math.max(1, page), pageCount);
    const fragment = document.createDocumentFragment();
    matches.slice((page - 1) * pageSize, page * pageSize).forEach((trip) => fragment.append(card(trip)));
    list.replaceChildren(fragment);
    root.querySelector("[data-history-count]").textContent = `${matches.length} ${input.value.trim() ? "найдено" : "поездок"}`;
    empty.hidden = matches.length > 0;
    empty.querySelector("p").textContent = input.value.trim() ? "По этим местам поездок нет." : "Поездок пока нет.";
    pagination.hidden = pageCount <= 1;
    previous.hidden = page === 1;
    next.hidden = page === pageCount;
    root.querySelector("[data-history-position]").textContent = `${page} / ${pageCount}`;
    previous.href = `?${new URLSearchParams({ q: input.value, page: page - 1 })}`;
    next.href = `?${new URLSearchParams({ q: input.value, page: page + 1 })}`;
  };
  const search = () => {
    const words = normalize(input.value).split(/\s+/).filter(Boolean);
    matches = indexed.filter((item) => words.every((word) => item.origin.includes(word) || item.destination.includes(word))).map((item) => item.trip);
    render();
  };
  input.addEventListener("input", () => { page = 1; search(); });
  form.addEventListener("submit", (event) => { event.preventDefault(); page = 1; search(); });
  root.querySelector("[data-history-reset]").addEventListener("click", (event) => {
    event.preventDefault(); input.value = ""; page = 1; search(); input.focus();
  });
  previous.addEventListener("click", (event) => { event.preventDefault(); page--; render(); });
  next.addEventListener("click", (event) => { event.preventDefault(); page++; render(); });
  search();
})();
