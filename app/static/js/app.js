"use strict";

const formatLocalTime = (date = new Date()) => {
  const localDate = new Date(date);
  localDate.setMinutes(localDate.getMinutes() - localDate.getTimezoneOffset());
  return localDate.toISOString().slice(0, 16);
};

const setCurrentTime = (id) => {
  const input = document.getElementById(id);
  if (input) input.value = formatLocalTime();
};

document.querySelectorAll("[data-default-now]").forEach((input) => {
  setCurrentTime(input.id);
  input.dataset.timeMode = "now";
});

document.querySelectorAll("[data-time-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const panel = document.querySelector(`[data-time-panel="${button.dataset.timeToggle}"]`);
    if (!panel) return;
    panel.hidden = !panel.hidden;
    button.setAttribute("aria-expanded", String(!panel.hidden));
  });
});

const selectTimeChip = (button, target) => {
  const panel = button.closest("[data-time-panel]");
  panel?.querySelectorAll(".time-chip").forEach((chip) => {
    const selected = chip === button;
    chip.classList.toggle("active", selected);
    chip.setAttribute("aria-pressed", String(selected));
  });
  const exact = document.querySelector(`[data-time-exact="${target}"]`);
  if (exact) exact.hidden = !button.hasAttribute("data-time-custom");
};

document.querySelectorAll("[data-time-offset]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.timeTarget;
    const input = document.getElementById(target);
    const offset = Number.parseInt(button.dataset.timeOffset, 10);
    if (!input || !Number.isFinite(offset)) return;
    input.value = formatLocalTime(new Date(Date.now() - offset * 60000));
    input.dataset.timeMode = offset === 0 ? "now" : "fixed";
    selectTimeChip(button, target);
  });
});

document.querySelectorAll("[data-time-custom]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.timeCustom;
    const input = document.getElementById(target);
    if (!input) return;
    input.dataset.timeMode = "custom";
    selectTimeChip(button, target);
    input.focus();
  });
});

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

const initializeAutocomplete = (input) => {
  if (input.dataset.autocompleteReady) return;
  input.dataset.autocompleteReady = "true";
  const menu = input.parentElement.querySelector(".suggestions");
  if (!menu) return;

  const load = debounce(async () => {
    const query = input.value.trim();
    try {
      const response = await fetch(`/api/places?q=${encodeURIComponent(query)}`);
      if (!response.ok) return;
      const places = await response.json();
      if (input.value.trim() !== query) return;
      menu.replaceChildren();
      places.forEach((place) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "suggestion";
        option.setAttribute("role", "option");
        option.textContent = place.name;
        option.addEventListener("click", () => {
          input.value = place.name;
          menu.classList.remove("open");
          if (input.dataset.timeTarget) setCurrentTime(input.dataset.timeTarget);
          input.dispatchEvent(new Event("change", { bubbles: true }));
        });
        menu.append(option);
      });
      const isExistingPlace = places.some(
        (place) => normalizePlaceName(place.name) === normalizePlaceName(query),
      );
      if (query && !isExistingPlace) {
        const notice = document.createElement("div");
        notice.className = "new-place-notice";
        notice.setAttribute("role", "status");
        notice.textContent = `Будет создано новое место · ${query}`;
        menu.append(notice);
      }
      menu.classList.toggle("open", places.length > 0 || Boolean(query));
    } catch (_) {
      menu.classList.remove("open");
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
    if (event.key === "Escape") menu.classList.remove("open");
  });
  document.addEventListener("click", (event) => {
    if (!input.parentElement.contains(event.target)) menu.classList.remove("open");
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
  const transportControls = [...tripForm.querySelectorAll("[name=transport_type]")];
  const updateDetails = () => {
    const selected = transportControls.find((control) => control.checked)?.value;
    const isTransit = selected === "bus" || selected === "metro";
    const isTaxi = selected === "taxi";
    detailBox.hidden = !isTransit && !isTaxi;
    detailWrap.hidden = !isTransit;
    taxiFields.hidden = !isTaxi;
    if (isTransit) {
      detailLabel.textContent = selected === "bus" ? "Номер автобуса" : "Ветка метро";
      detailInput.placeholder = selected === "bus" ? "Например, 39" : "Например, Сокольническая";
    }
  };
  transportControls.forEach((control) => control.addEventListener("change", updateDetails));
  updateDetails();
}

const calculator = document.querySelector("[data-calculator]");
if (calculator) {
  const points = calculator.querySelector("[data-points]");
  const result = document.querySelector("[data-result]");

  const renumber = () => {
    points.querySelectorAll(".point-row").forEach((row, index) => {
      row.querySelector(".point-index").textContent = String(index + 1).padStart(2, "0");
      row.querySelector(".remove-point").hidden = points.children.length <= 2;
    });
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

  calculator.querySelector("[data-add-point]").addEventListener("click", () => {
    const row = document.createElement("div");
    row.className = "point-row autocomplete";
    row.innerHTML = '<span class="point-index"></span><input type="text" placeholder="Следующая точка" autocomplete="off" required data-place-input><div class="suggestions" role="listbox"></div><button type="button" class="remove-point" aria-label="Удалить точку">×</button>';
    points.append(row);
    initializeAutocomplete(row.querySelector("input"));
    bindRemove(row);
    renumber();
    row.querySelector("input").focus();
  });

  calculator.addEventListener("submit", async (event) => {
    event.preventDefault();
    const pointNames = [...points.querySelectorAll("input")].map((input) => input.value.trim()).filter(Boolean);
    if (pointNames.length < 2) return;
    const button = calculator.querySelector("[type=submit]");
    button.disabled = true;
    button.firstChild.textContent = "Считаем ";
    try {
      const response = await fetch("/api/calculate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": calculator.querySelector("[data-csrf]").value },
        body: JSON.stringify({ points: pointNames }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Ошибка расчёта");
      const known = data.segments.filter((segment) => segment.known).length;
      result.innerHTML = `
        <div class="result-summary">
          <div><p>Оценка пути</p><strong>${data.total_minutes}</strong> <small>мин</small></div>
          <span class="confidence ${data.complete ? "" : "partial"}">${data.complete ? "Все отрезки известны" : `${known} из ${data.segments.length} отрезков`}</span>
        </div>
        <div class="segment-list">
          ${data.segments.map((segment, index) => `
            <article class="segment ${segment.known ? "" : "unknown"}" style="animation-delay:${index * 70}ms">
              <div><h3>${escapeHtml(segment.from)} <span>→</span> ${escapeHtml(segment.to)}</h3><p>${segment.known ? `${escapeHtml(segment.transport)} · ${segment.samples} наблюд.` : "Сначала запишите такую поездку"}</p></div>
              <strong>${segment.known ? `${segment.minutes} мин` : "Нет данных"}</strong>
            </article>`).join("")}
        </div>`;
    } catch (error) {
      result.innerHTML = `<div class="result-placeholder"><span>!</span><h2>Не получилось посчитать</h2><p>${escapeHtml(error.message)}</p></div>`;
    } finally {
      button.disabled = false;
      button.firstChild.textContent = "Посчитать ";
    }
  });
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = String(value);
  return element.innerHTML;
}

const initializeYandexMaps = () => {
  const mapDialog = document.querySelector("[data-map-dialog]");
  if (mapDialog) {
    let activeForm = null;
    let pickerMap = null;
    let pickerMarker = null;

    const placePickerMarker = (coordinates) => {
      if (pickerMarker) {
        pickerMarker.geometry.setCoordinates(coordinates);
        return;
      }
      pickerMarker = new ymaps.Placemark(
        coordinates,
        {},
        { preset: "islands#circleDotIcon", iconColor: "#191919" },
      );
      pickerMap.geoObjects.add(pickerMarker);
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
            pickerMap = new ymaps.Map("coordinate-map", {
              center: [55.7512, 37.6184],
              zoom: 11,
              controls: ["zoomControl"],
            });
            pickerMap.events.add("click", (event) => placePickerMarker(event.get("coords")));
          }
          pickerMap.container.fitToViewport();
          if (hasCoordinates) {
            pickerMap.setCenter([latitude, longitude], 15);
            placePickerMarker([latitude, longitude]);
          } else {
            if (pickerMarker) pickerMap.geoObjects.remove(pickerMarker);
            pickerMarker = null;
            pickerMap.setCenter([55.7512, 37.6184], 11);
          }
        }, 50);
      });
    });
    mapDialog.querySelector("[data-map-close]").addEventListener("click", () => mapDialog.close());
    mapDialog.querySelector("[data-map-apply]").addEventListener("click", () => {
      if (!activeForm || !pickerMarker) return;
      const [latitude, longitude] = pickerMarker.geometry.getCoordinates();
      activeForm.querySelector("[name=latitude]").value = latitude.toFixed(6);
      activeForm.querySelector("[name=longitude]").value = longitude.toFixed(6);
      mapDialog.close();
    });
  }

  const journeyMapElement = document.getElementById("journey-map");
  const mapDataElement = document.getElementById("map-data");
  if (journeyMapElement && mapDataElement) {
    const mapData = JSON.parse(mapDataElement.textContent);
    const map = new ymaps.Map(journeyMapElement, {
      center: [55.7512, 37.6184],
      zoom: 10,
      controls: ["zoomControl"],
    });

    const pointsById = new Map();
    mapData.places.forEach((place) => {
      const point = [place.lat, place.lng];
      pointsById.set(place.id, point);
      map.geoObjects.add(new ymaps.Placemark(
        point,
        {
          balloonContentHeader: escapeHtml(place.name),
          balloonContentBody: escapeHtml(place.address || "Адрес не указан"),
        },
        { preset: "islands#circleDotIcon", iconColor: place.color },
      ));
    });
    mapData.trips.forEach((trip) => {
      const origin = pointsById.get(trip.from);
      const destination = pointsById.get(trip.to);
      if (origin && destination) {
        map.geoObjects.add(new ymaps.Polyline(
          [origin, destination],
          { balloonContent: `${trip.minutes} мин` },
          { strokeColor: "#5f5f59", strokeWidth: 3, strokeOpacity: 0.65 },
        ));
      }
    });
    const bounds = map.geoObjects.getBounds();
    if (mapData.places.length === 1) map.setCenter(pointsById.values().next().value, 14);
    else if (bounds) map.setBounds(bounds, { checkZoomRange: true, zoomMargin: 48 });
  }
};

if (window.ymaps) ymaps.ready(initializeYandexMaps);
