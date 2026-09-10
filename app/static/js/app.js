"use strict";

const detectedTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const activeTimezone = document.body.dataset.timezone || detectedTimezone;

const formatLocalTime = (date = new Date()) => {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: activeTimezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      numberingSystem: "latn",
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`;
  } catch (_) {
    const localDate = new Date(date);
    localDate.setMinutes(localDate.getMinutes() - localDate.getTimezoneOffset());
    return localDate.toISOString().slice(0, 16);
  }
};

const setCurrentTime = (id) => {
  const input = document.getElementById(id);
  if (input) input.value = formatLocalTime();
};

document.querySelectorAll("[data-default-now]").forEach((input) => {
  setCurrentTime(input.id);
  input.dataset.timeMode = "now";
});

document.querySelectorAll("[data-time-dialog-open]").forEach((button) => {
  const target = button.dataset.timeDialogOpen;
  const input = document.getElementById(target);
  const dialog = document.querySelector(`[data-time-dialog="${target}"]`);
  if (!input || !dialog) return;
  const dateInput = dialog.querySelector("[data-picker-date]");
  const clockInput = dialog.querySelector("[data-picker-clock]");
  dialog.querySelector("[data-timezone-label]").textContent = activeTimezone;

  button.addEventListener("click", () => {
    if (input.dataset.timeMode === "now") setCurrentTime(target);
    const [date, time] = input.value.split("T");
    dateInput.value = date;
    clockInput.value = time;
    dateInput.disabled = false;
    clockInput.disabled = false;
    dialog.showModal();
  });
  dialog.addEventListener("close", () => {
    dateInput.disabled = true;
    clockInput.disabled = true;
  });
  dialog.querySelector("[data-time-dialog-close]").addEventListener("click", () => dialog.close());
  dialog.querySelector("[data-time-dialog-apply]").addEventListener("click", () => {
    if (!dateInput.reportValidity() || !clockInput.reportValidity()) return;
    input.value = `${dateInput.value}T${clockInput.value}`;
    input.dataset.timeMode = "custom";
    button.classList.add("custom-time");
    button.setAttribute("aria-pressed", "true");
    button.title = `${button.getAttribute("aria-label")} · ${dateInput.value} ${clockInput.value}`;
    dialog.close();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    const inside = event.clientX >= bounds.left && event.clientX <= bounds.right
      && event.clientY >= bounds.top && event.clientY <= bounds.bottom;
    if (!inside) dialog.close();
  });
});

if (document.body.dataset.timezoneAuto === "true" && detectedTimezone) {
  fetch("/api/timezone", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": document.body.dataset.csrfToken,
    },
    body: JSON.stringify({ timezone: detectedTimezone }),
  }).catch(() => {});
}

document.querySelectorAll("form").forEach((form) => {
  form.addEventListener("submit", () => {
    form.querySelectorAll('[data-default-now][data-time-mode="now"]').forEach((input) => {
      setCurrentTime(input.id);
    });
  });
});

const startForm = document.querySelector(".start-form");
if (startForm) {
  let transitionStarted = false;
  startForm.addEventListener("submit", (event) => {
    if (transitionStarted || !startForm.checkValidity()) return;
    event.preventDefault();
    startForm.classList.add("is-transitioning");
    startForm.querySelector('[type="submit"]').disabled = true;
    window.setTimeout(() => {
      transitionStarted = true;
      startForm.requestSubmit();
    }, 420);
  });
}

const debounce = (callback, delay = 180) => {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => callback(...args), delay);
  };
};

const normalizePlaceName = (value) => value
  .trim()
  .toLocaleLowerCase("ru-RU")
  .replace(/\s+/g, " ");

let autocompleteIndex = 0;
const initializeAutocomplete = (input) => {
  if (input.dataset.autocompleteReady) return;
  input.dataset.autocompleteReady = "true";
  const menu = input.parentElement.querySelector(".suggestions");
  if (!menu) return;
  autocompleteIndex += 1;
  menu.id ||= `suggestions-${autocompleteIndex}`;
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", menu.id);
  input.setAttribute("aria-expanded", "false");
  let activeIndex = -1;

  const options = () => [...menu.querySelectorAll(".suggestion")];
  const setOpen = (open) => {
    menu.classList.toggle("open", open);
    input.setAttribute("aria-expanded", String(open));
    if (!open) input.removeAttribute("aria-activedescendant");
  };
  const setActive = (index) => {
    const items = options();
    if (!items.length) return;
    activeIndex = (index + items.length) % items.length;
    items.forEach((item, itemIndex) => {
      const active = itemIndex === activeIndex;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-selected", String(active));
    });
    input.setAttribute("aria-activedescendant", items[activeIndex].id);
    items[activeIndex].scrollIntoView({ block: "nearest" });
  };
  const choose = (option, moveForward = false) => {
    input.value = option.textContent;
    setOpen(false);
    if (input.dataset.timeTarget) setCurrentTime(input.dataset.timeTarget);
    input.dispatchEvent(new Event("change", { bubbles: true }));
    if (moveForward) {
      const formInputs = [...(input.closest("form") || document).querySelectorAll("[data-place-input]")]
        .filter((item) => !item.disabled && item.offsetParent !== null);
      const nextInput = formInputs[formInputs.indexOf(input) + 1];
      nextInput?.focus();
    }
  };

  const load = debounce(async () => {
    const query = input.value.trim();
    try {
      if (input.dataset.suggestionsDisabled === "true") return;
      const endpoint = input.dataset.suggestionsUrl || "/api/places";
      const response = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`);
      if (!response.ok) return;
      const places = await response.json();
      if (input.value.trim() !== query) return;
      menu.replaceChildren();
      places.forEach((place, index) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "suggestion";
        option.id = `${menu.id}-option-${index}`;
        option.setAttribute("role", "option");
        option.textContent = place.name;
        option.addEventListener("mouseenter", () => setActive(index));
        option.addEventListener("click", () => choose(option));
        menu.append(option);
      });
      const isExistingPlace = places.some(
        (place) => normalizePlaceName(place.name) === normalizePlaceName(query),
      );
      if (query && !isExistingPlace) {
        const notice = document.createElement("div");
        notice.className = "new-place-notice";
        notice.setAttribute("role", "status");
        const message = input.dataset.newItemMessage || "Будет создано новое место";
        notice.textContent = `${message} · ${query}`;
        menu.append(notice);
      }
      activeIndex = places.length ? 0 : -1;
      setOpen(places.length > 0 || Boolean(query));
      if (places.length) setActive(0);
    } catch (_) {
      setOpen(false);
    }
  });

  input.addEventListener("input", () => {
    load();
    const timeInput = input.dataset.timeTarget
      ? document.getElementById(input.dataset.timeTarget)
      : null;
    if (input.value.trim() && timeInput && !timeInput.value) setCurrentTime(input.dataset.timeTarget);
  });
  input.addEventListener("focus", load);
  input.addEventListener("change", () => {
    const timeInput = input.dataset.timeTarget
      ? document.getElementById(input.dataset.timeTarget)
      : null;
    if (input.value.trim() && timeInput && !timeInput.value) setCurrentTime(input.dataset.timeTarget);
  });
  input.addEventListener("keydown", (event) => {
    const items = options();
    if ((event.key === "ArrowDown" || event.key === "ArrowUp") && items.length) {
      event.preventDefault();
      setOpen(true);
      setActive(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Enter" && menu.classList.contains("open") && items.length) {
      event.preventDefault();
      choose(items[Math.max(activeIndex, 0)], true);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  });
  document.addEventListener("click", (event) => {
    if (!input.parentElement.contains(event.target)) setOpen(false);
  });
};

document.querySelectorAll("[data-place-input]").forEach(initializeAutocomplete);

const clearForm = document.querySelector("[data-clear-form]");
if (clearForm) {
  clearForm.addEventListener("submit", (event) => {
    if (!window.confirm("Очистить начальную точку? Текущая поездка не сохранится.")) {
      event.preventDefault();
    }
  });
}

const tripForm = document.querySelector("[data-trip-form]");
if (tripForm) {
  const detailBox = tripForm.querySelector("[data-detail-fields]");
  const detailWrap = tripForm.querySelector("[data-detail-wrap]");
  const detailLabel = tripForm.querySelector("[data-detail-label]");
  const detailInput = tripForm.querySelector("#transport_detail");
  const taxiFields = tripForm.querySelector("[data-taxi-fields]");
  const taxiTariff = tripForm.querySelector("#taxi_tariff");
  const costField = tripForm.querySelector("[data-cost-field]");
  const costLabel = tripForm.querySelector("[data-cost-label]");
  const costInput = tripForm.querySelector("#trip_cost");
  const transportControls = [...tripForm.querySelectorAll("[name=transport_type]")];
  const transportCards = transportControls.map((control) => control.closest(".transport-card"));
  initializeAutocomplete(detailInput);
  costInput?.addEventListener("input", () => delete costInput.dataset.automaticZero);
  const updateDetails = () => {
    const selected = transportControls.find((control) => control.checked)?.value;
    const hasDetail = selected === "bus" || selected === "metro" || selected === "other";
    const isTaxi = selected === "taxi";
    const isRental = selected === "ebike" || selected === "scooter";
    const hasCost = isTaxi || isRental;
    transportCards.forEach((card, index) => {
      card.classList.toggle("is-muted", Boolean(selected) && !transportControls[index].checked);
    });
    detailBox.hidden = !hasDetail && !hasCost;
    detailBox.classList.toggle("taxi-layout", isTaxi);
    detailWrap.hidden = !hasDetail;
    costField.hidden = !hasCost;
    taxiFields.hidden = !isTaxi;
    detailInput.required = selected === "other";
    taxiTariff.required = isTaxi;
    costInput.required = isRental;
    if (selected === "metro") {
      detailLabel.textContent = "Ветка метро";
      detailInput.placeholder = "Например, Сокольническая";
      detailInput.dataset.suggestionsUrl = "/api/metro-lines";
      detailInput.dataset.newItemMessage = "Будет добавлена новая ветка метро";
      detailInput.dataset.suggestionsDisabled = "false";
    } else {
      detailInput.dataset.suggestionsDisabled = "true";
      detailInput.parentElement.querySelector(".suggestions")?.classList.remove("open");
      if (selected === "bus") {
        detailLabel.textContent = "Номер автобуса";
        detailInput.placeholder = "Например, 39";
      } else if (selected === "other") {
        detailLabel.textContent = "Вид перемещения";
        detailInput.placeholder = "Например, ролики";
      }
    }
    if (isRental && (!costInput.value || costInput.dataset.automaticZero)) {
      costInput.value = "0";
      costInput.dataset.automaticZero = "true";
    } else if (isTaxi && costInput.dataset.automaticZero) {
      costInput.value = "";
      delete costInput.dataset.automaticZero;
    }
    costLabel.textContent = isRental ? "Стоимость аренды, ₽" : "Стоимость, ₽";
  };
  transportControls.forEach((control) => control.addEventListener("change", updateDetails));
  transportControls.forEach((control, index) => {
    control.addEventListener("keydown", (event) => {
      const direction = {
        ArrowLeft: -1,
        ArrowUp: -1,
        ArrowRight: 1,
        ArrowDown: 1,
      }[event.key];
      if (!direction) return;
      event.preventDefault();
      const nextIndex = (index + direction + transportControls.length) % transportControls.length;
      const nextControl = transportControls[nextIndex];
      nextControl.checked = true;
      nextControl.dispatchEvent(new Event("change", { bubbles: true }));
      nextControl.focus();
      transportCards[nextIndex].scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    });
  });
  updateDetails();
}

const calculator = document.querySelector("[data-calculator]");
if (calculator) {
  const points = calculator.querySelector("[data-points]");
  const addPointButton = calculator.querySelector("[data-add-point]");

  const renumber = () => {
    points.querySelectorAll(".point-row").forEach((row, index) => {
      row.querySelector(".point-index").textContent = String(index + 1).padStart(2, "0");
      row.querySelector(".remove-point").hidden = points.children.length <= 2;
    });
    addPointButton.hidden = points.children.length >= Number(addPointButton.dataset.maxPoints);
  };

  const bindRemove = (row) => {
    row.querySelector(".remove-point").addEventListener("click", () => {
      if (points.children.length > 2) {
        row.remove();
        renumber();
      }
    });
  };

  points.querySelectorAll(".point-row").forEach(bindRemove);
  renumber();

  addPointButton.addEventListener("click", () => {
    if (points.children.length >= Number(addPointButton.dataset.maxPoints)) return;
    const row = document.createElement("div");
    row.className = "point-row autocomplete";
    const maxLength = points.querySelector("input").maxLength;
    row.innerHTML = `<span class="point-index"></span><input name="points" type="text" maxlength="${maxLength}" placeholder="Следующая точка" autocomplete="off" required data-place-input><div class="suggestions" role="listbox"></div><button type="button" class="remove-point" aria-label="Удалить точку">×</button>`;
    points.append(row);
    initializeAutocomplete(row.querySelector("input"));
    bindRemove(row);
    renumber();
    row.querySelector("input").focus();
  });

}

const routeCanvas = document.querySelector("[data-route-canvas]");
if (routeCanvas) {
  const trackData = JSON.parse(document.querySelector("[data-route-track]").textContent);
  const drawRouteTrack = () => {
    const scale = window.devicePixelRatio || 1;
    const width = routeCanvas.clientWidth;
    const height = routeCanvas.clientHeight;
    routeCanvas.width = width * scale;
    routeCanvas.height = height * scale;
    const context = routeCanvas.getContext("2d");
    context.scale(scale, scale);
    const allGeographic = trackData.every((point) => point.latitude != null && point.longitude != null);
    let points;
    if (allGeographic) {
      const longitudes = trackData.map((point) => point.longitude);
      const latitudes = trackData.map((point) => point.latitude);
      const longitudeSpan = Math.max(Math.max(...longitudes) - Math.min(...longitudes), .0001);
      const latitudeSpan = Math.max(Math.max(...latitudes) - Math.min(...latitudes), .0001);
      points = trackData.map((point) => ({
        x: 54 + ((point.longitude - Math.min(...longitudes)) / longitudeSpan) * (width - 108),
        y: 70 + ((Math.max(...latitudes) - point.latitude) / latitudeSpan) * (height - 140),
        name: point.name,
      }));
    } else {
      points = trackData.map((point, index) => ({
        x: 48 + (index / Math.max(trackData.length - 1, 1)) * (width - 96),
        y: height * (.58 + Math.sin(index * 1.7) * .2),
        name: point.name,
      }));
    }
    context.clearRect(0, 0, width, height);
    context.strokeStyle = "#f7f7f2";
    context.lineWidth = 3;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.beginPath();
    context.moveTo(points[0].x, points[0].y);
    for (let index = 1; index < points.length - 1; index += 1) {
      const middleX = (points[index].x + points[index + 1].x) / 2;
      const middleY = (points[index].y + points[index + 1].y) / 2;
      context.quadraticCurveTo(points[index].x, points[index].y, middleX, middleY);
    }
    const lastPoint = points.at(-1);
    context.lineTo(lastPoint.x, lastPoint.y);
    context.stroke();
    points.forEach((point, index) => {
      context.fillStyle = "#090909";
      context.strokeStyle = "#f7f7f2";
      context.lineWidth = 3;
      context.beginPath();
      context.arc(point.x, point.y, index === 0 || index === points.length - 1 ? 7 : 5, 0, Math.PI * 2);
      context.fill();
      context.stroke();
      context.fillStyle = "#f7f7f2";
      context.font = "600 11px Inter, sans-serif";
      context.textAlign = index === 0 ? "left" : index === points.length - 1 ? "right" : "center";
      const labelX = index === 0 ? point.x - 1 : index === points.length - 1 ? point.x + 1 : point.x;
      const labelY = point.y > height / 2 ? point.y - 17 : point.y + 25;
      context.fillText(point.name, labelX, labelY, Math.min(130, width / points.length + 30));
    });
  };
  drawRouteTrack();
  window.addEventListener("resize", debounce(drawRouteTrack, 100));
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = String(value);
  return element.innerHTML;
}

const ESRI_IMAGERY_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

const createImageryLayer = () => new ol.layer.Tile({
  source: new ol.source.XYZ({
    url: ESRI_IMAGERY_TILES,
    attributions: "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community",
    maxZoom: 19,
  }),
});

const createPointStyle = (color) => new ol.style.Style({
  image: new ol.style.Circle({
    radius: 7,
    fill: new ol.style.Fill({ color }),
    stroke: new ol.style.Stroke({ color: "#f7f7f2", width: 2 }),
  }),
});

const initializeOpenLayersMaps = () => {
  const mapDialog = document.querySelector("[data-map-dialog]");
  if (mapDialog) {
    let activeForm = null;
    let pickerMap = null;
    let pickerCoordinates = null;
    const pickerSource = new ol.source.Vector();

    const placePickerMarker = (latitude, longitude) => {
      pickerCoordinates = [latitude, longitude];
      pickerSource.clear();
      pickerSource.addFeature(new ol.Feature({
        geometry: new ol.geom.Point(ol.proj.fromLonLat([longitude, latitude])),
      }));
    };

    document.querySelectorAll("[data-map-pick]").forEach((button) => {
      button.addEventListener("click", () => {
        activeForm = button.closest("form");
        const latitude = Number.parseFloat(activeForm.querySelector("[name=latitude]").value);
        const longitude = Number.parseFloat(activeForm.querySelector("[name=longitude]").value);
        const hasCoordinates = Number.isFinite(latitude) && Number.isFinite(longitude);
        mapDialog.showModal();
        window.setTimeout(() => {
          if (!pickerMap) {
            pickerMap = new ol.Map({
              target: "coordinate-map",
              layers: [
                createImageryLayer(),
                new ol.layer.Vector({
                  source: pickerSource,
                  style: createPointStyle("#191919"),
                }),
              ],
              view: new ol.View({
                center: ol.proj.fromLonLat([37.6184, 55.7512]),
                zoom: 11,
              }),
            });
            pickerMap.on("singleclick", (event) => {
              const [longitude, latitude] = ol.proj.toLonLat(event.coordinate);
              placePickerMarker(latitude, longitude);
            });
          }
          pickerMap.updateSize();
          if (hasCoordinates) {
            pickerMap.getView().setCenter(ol.proj.fromLonLat([longitude, latitude]));
            pickerMap.getView().setZoom(15);
            placePickerMarker(latitude, longitude);
          } else {
            pickerCoordinates = null;
            pickerSource.clear();
            pickerMap.getView().setCenter(ol.proj.fromLonLat([37.6184, 55.7512]));
            pickerMap.getView().setZoom(11);
          }
        }, 50);
      });
    });
    mapDialog.querySelector("[data-map-close]").addEventListener("click", () => mapDialog.close());
    mapDialog.querySelector("[data-map-apply]").addEventListener("click", () => {
      if (!activeForm || !pickerCoordinates) return;
      const [latitude, longitude] = pickerCoordinates;
      activeForm.querySelector("[name=latitude]").value = latitude.toFixed(6);
      activeForm.querySelector("[name=longitude]").value = longitude.toFixed(6);
      activeForm.querySelector("[data-map-pick]").textContent = "Изменить точку на карте";
      mapDialog.close();
    });
  }

  const journeyMapElement = document.getElementById("journey-map");
  const mapDataElement = document.getElementById("map-data");
  if (journeyMapElement && mapDataElement) {
    const mapData = JSON.parse(mapDataElement.textContent);
    const vectorSource = new ol.source.Vector();
    const popupElement = document.createElement("div");
    popupElement.className = "map-popup";
    popupElement.hidden = true;
    journeyMapElement.after(popupElement);
    const popup = new ol.Overlay({
      element: popupElement,
      positioning: "bottom-center",
      offset: [0, -10],
      stopEvent: false,
    });
    const map = new ol.Map({
      target: journeyMapElement,
      layers: [createImageryLayer(), new ol.layer.Vector({ source: vectorSource })],
      overlays: [popup],
      view: new ol.View({
        center: ol.proj.fromLonLat([37.6184, 55.7512]),
        zoom: 10,
      }),
    });

    const pointsById = new Map();
    mapData.places.forEach((place) => {
      const point = ol.proj.fromLonLat([place.lng, place.lat]);
      pointsById.set(place.id, point);
      const marker = new ol.Feature({
        geometry: new ol.geom.Point(point),
        popupHtml: `<strong>${escapeHtml(place.name)}</strong>${place.description ? `<br>${escapeHtml(place.description)}` : ""}`,
      });
      marker.setStyle(createPointStyle(place.color));
      vectorSource.addFeature(marker);
    });
    mapData.trips.forEach((trip) => {
      const origin = pointsById.get(trip.from);
      const destination = pointsById.get(trip.to);
      if (origin && destination) {
        const line = new ol.Feature({
          geometry: new ol.geom.LineString([origin, destination]),
          popupHtml: `${trip.minutes} мин`,
        });
        line.setStyle(new ol.style.Style({
          stroke: new ol.style.Stroke({ color: "rgba(247, 247, 242, .65)", width: 3 }),
        }));
        vectorSource.addFeature(line);
      }
    });
    map.on("singleclick", (event) => {
      const feature = map.forEachFeatureAtPixel(event.pixel, (item) => item);
      const popupHtml = feature?.get("popupHtml");
      popupElement.hidden = !popupHtml;
      popupElement.innerHTML = popupHtml || "";
      popup.setPosition(popupHtml ? event.coordinate : undefined);
    });
    if (mapData.places.length === 1) {
      map.getView().setCenter(pointsById.values().next().value);
      map.getView().setZoom(14);
    } else if (mapData.places.length > 1) {
      map.getView().fit(vectorSource.getExtent(), {
        padding: [80, 48, 100, 48],
        maxZoom: 15,
      });
    }
  }
};

if (window.ol) initializeOpenLayersMaps();
