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

const initializeAutocomplete = (input) => {
  if (input.dataset.autocompleteReady) return;
  input.dataset.autocompleteReady = "true";
  const menu = input.parentElement.querySelector(".suggestions");
  if (!menu) return;

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
        const message = input.dataset.newItemMessage || "Будет создано новое место";
        notice.textContent = `${message} · ${query}`;
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
