"use strict";

const legalUpdateDialog = document.querySelector("[data-legal-update-dialog]");
if (legalUpdateDialog) {
  if (legalUpdateDialog.open) legalUpdateDialog.close();
  legalUpdateDialog.showModal();
  legalUpdateDialog.addEventListener("cancel", (event) => event.preventDefault());
}

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
    }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 540);
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
    const timeInput = input.dataset.timeTarget
      ? document.getElementById(input.dataset.timeTarget)
      : null;
    if (timeInput?.dataset.timeMode === "now") setCurrentTime(input.dataset.timeTarget);
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

  let completionStarted = false;
  tripForm.addEventListener("submit", (event) => {
    if (completionStarted || !tripForm.checkValidity()) return;
    event.preventDefault();
    completionStarted = true;
    const layout = tripForm.closest(".record-layout");
    layout?.classList.add("is-completing");
    layout?.setAttribute("aria-busy", "true");
    tripForm.querySelector('[type="submit"]').disabled = true;
    window.setTimeout(() => {
      tripForm.requestSubmit();
    }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 620);
  });
}

document.querySelectorAll("[data-route-canvas]").forEach((routeCanvas) => {
  const trackWrap = routeCanvas.closest("[data-route-track-wrap]");
  const trackData = JSON.parse(trackWrap.querySelector("[data-route-track]").textContent);
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
});

const routeCarousel = document.querySelector("[data-route-carousel]");
if (routeCarousel) {
  const slides = [...routeCarousel.querySelectorAll("[data-route-slide]")];
  const viewport = routeCarousel.querySelector("[data-route-slides]");
  const position = routeCarousel.querySelector("[data-route-position]");
  const previous = routeCarousel.querySelector("[data-route-previous]");
  const next = routeCarousel.querySelector("[data-route-next]");
  let activeIndex = 0;

  const updatePosition = () => {
    position.textContent = `${activeIndex + 1} / ${slides.length}`;
    previous.disabled = activeIndex === 0;
    next.disabled = activeIndex === slides.length - 1;
    slides.forEach((slide, index) => {
      slide.classList.toggle("is-active", index === activeIndex);
    });
  };
  const showSlide = (index) => {
    activeIndex = Math.max(0, Math.min(index, slides.length - 1));
    slides[activeIndex].scrollIntoView({ behavior: "smooth", block: "nearest", inline: "start" });
    updatePosition();
  };
  previous.addEventListener("click", () => showSlide(activeIndex - 1));
  next.addEventListener("click", () => showSlide(activeIndex + 1));
  const carouselObserver = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting)
      .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
    if (!visible) return;
    activeIndex = slides.indexOf(visible.target);
    updatePosition();
  }, { root: viewport, threshold: [.55, .8] });
  slides.forEach((slide) => carouselObserver.observe(slide));
  updatePosition();
}

const roundedRectPath = (context, x, y, width, height, radius) => {
  const safeRadius = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + safeRadius, y);
  context.arcTo(x + width, y, x + width, y + height, safeRadius);
  context.arcTo(x + width, y + height, x, y + height, safeRadius);
  context.arcTo(x, y + height, x, y, safeRadius);
  context.arcTo(x, y, x + width, y, safeRadius);
  context.closePath();
};

const wrapCanvasText = (context, text, maxWidth, maxLines = 2) => {
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = "";
  words.forEach((word) => {
    const candidate = line ? `${line} ${word}` : word;
    if (line && context.measureText(candidate).width > maxWidth) {
      lines.push(line);
      line = word;
    } else {
      line = candidate;
    }
  });
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    lines.length = maxLines;
    while (context.measureText(`${lines.at(-1)}…`).width > maxWidth) {
      lines[lines.length - 1] = lines.at(-1).slice(0, -1);
    }
    lines[lines.length - 1] += "…";
  }
  return lines;
};

const createRouteShareImage = async (payload) => {
  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = 1350;
  const context = canvas.getContext("2d");
  context.fillStyle = "#090909";
  context.fillRect(0, 0, canvas.width, canvas.height);
  const glow = context.createRadialGradient(860, 120, 0, 860, 120, 680);
  glow.addColorStop(0, "rgba(255,255,255,.09)");
  glow.addColorStop(1, "rgba(255,255,255,0)");
  context.fillStyle = glow;
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "#30302d";
  context.lineWidth = 2;
  roundedRectPath(context, 42, 42, 996, 1266, 38);
  context.stroke();

  context.fillStyle = "#8f8f88";
  context.font = "500 22px Inter, sans-serif";
  context.fillText("СОХРАНЁННЫЙ МАРШРУТ", 92, 116);
  context.fillStyle = "#f7f7f2";
  context.font = "600 66px Inter, sans-serif";
  const titleLines = wrapCanvasText(context, payload.title, 880, 2);
  titleLines.forEach((line, index) => context.fillText(line, 92, 208 + index * 76));
  let cursorY = 238 + titleLines.length * 76;
  context.fillStyle = "#a2a29b";
  context.font = "500 29px Inter, sans-serif";
  wrapCanvasText(context, `Из ${payload.origin} в ${payload.destination}`, 880, 2)
    .forEach((line, index) => context.fillText(line, 92, cursorY + index * 38));
  cursorY += 108;

  context.fillStyle = "#777771";
  context.font = "500 22px Inter, sans-serif";
  const chain = payload.route.points.map((point) => point.name).join("  ·  ");
  wrapCanvasText(context, chain, 880, 3)
    .forEach((line, index) => context.fillText(line, 92, cursorY + index * 31));
  cursorY += 128;

  const metrics = [
    [String(payload.route.total_minutes), "минут"],
    [payload.route.total_distance_km ?? "—", "километров"],
    [String(payload.route.segments.length), "отрезков"],
  ];
  metrics.forEach(([value, label], index) => {
    const x = 92 + index * 302;
    context.fillStyle = "#111110";
    context.strokeStyle = "#30302d";
    roundedRectPath(context, x, cursorY, 278, 158, 24);
    context.fill();
    context.stroke();
    context.fillStyle = "#f7f7f2";
    context.font = "600 52px Inter, sans-serif";
    context.fillText(String(value), x + 25, cursorY + 69, 225);
    context.fillStyle = "#8f8f88";
    context.font = "500 19px Inter, sans-serif";
    context.fillText(label, x + 25, cursorY + 120);
  });
  cursorY += 215;

  context.fillStyle = "#8f8f88";
  context.font = "500 20px Inter, sans-serif";
  context.fillText("ПО ОТРЕЗКАМ", 92, cursorY);
  cursorY += 48;
  payload.route.segments.slice(0, 5).forEach((segment, index) => {
    context.fillStyle = "#f7f7f2";
    context.font = "600 25px Inter, sans-serif";
    context.fillText(String(index + 1).padStart(2, "0"), 92, cursorY);
    context.font = "600 27px Inter, sans-serif";
    context.fillText(`${segment.from} · ${segment.to}`, 150, cursorY, 620);
    context.fillStyle = "#8f8f88";
    context.font = "500 21px Inter, sans-serif";
    context.textAlign = "right";
    context.fillText(`${segment.transport} · ${segment.minutes} мин`, 980, cursorY);
    context.textAlign = "left";
    cursorY += 70;
  });

  context.fillStyle = "#62625c";
  context.font = "500 19px Inter, sans-serif";
  context.fillText("ДНЕВНИК ПОЕЗДОК", 92, 1256);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("image")), "image/png");
  });
};

document.querySelectorAll("[data-saved-route-card]").forEach((card) => {
  const payload = JSON.parse(card.querySelector("[data-saved-route-share]").textContent);
  const status = card.querySelector("[data-share-route-status]");
  const linkButton = card.querySelector("[data-share-route-link]");
  const imageButton = card.querySelector("[data-share-route-image]");
  const setStatus = (message) => { status.textContent = message; };

  linkButton.addEventListener("click", async () => {
    linkButton.disabled = true;
    try {
      if (navigator.share) {
        await navigator.share({
          title: payload.title,
          text: `${payload.origin} — ${payload.destination}`,
          url: payload.shareUrl,
        });
        setStatus("Ссылка отправлена");
      } else {
        await navigator.clipboard.writeText(payload.shareUrl);
        setStatus("Ссылка скопирована");
      }
    } catch (error) {
      if (error.name !== "AbortError") setStatus("Не удалось отправить ссылку");
    } finally {
      linkButton.disabled = false;
    }
  });

  imageButton.addEventListener("click", async () => {
    imageButton.disabled = true;
    setStatus("Готовим карточку…");
    try {
      const blob = await createRouteShareImage(payload);
      const file = new File([blob], "route-card.png", { type: "image/png" });
      if (navigator.share && navigator.canShare?.({ files: [file] })) {
        await navigator.share({ title: payload.title, files: [file] });
        setStatus("Карточка отправлена");
      } else {
        const downloadUrl = URL.createObjectURL(blob);
        const download = document.createElement("a");
        download.href = downloadUrl;
        download.download = "route-card.png";
        download.click();
        window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
        setStatus("Карточка сохранена как PNG");
      }
    } catch (error) {
      if (error.name !== "AbortError") setStatus("Не удалось создать картинку");
    } finally {
      imageButton.disabled = false;
    }
  });
});

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = String(value);
  return element.innerHTML;
}

const createOpenStreetMapLayer = () => new ol.layer.Tile({
  source: new ol.source.OSM(),
});

const createPointStyle = (color) => new ol.style.Style({
  image: new ol.style.Circle({
    radius: 7,
    fill: new ol.style.Fill({ color }),
    stroke: new ol.style.Stroke({ color: "#f7f7f2", width: 2 }),
  }),
});

const createPlacementStyle = (color) => new ol.style.Style({
  image: new ol.style.Circle({
    radius: 12,
    fill: new ol.style.Fill({ color }),
    stroke: new ol.style.Stroke({ color: "#f7f7f2", width: 3 }),
  }),
  zIndex: 20,
});

const initializeOpenLayersMaps = () => {
  const mapPanel = document.querySelector("[data-map-panel]");
  const panelOpenButton = document.querySelector("[data-map-panel-open]");
  const setMapPanelOpen = (open) => {
    if (!mapPanel || !panelOpenButton) return;
    mapPanel.classList.toggle("is-open", open);
    mapPanel.setAttribute("aria-hidden", String(!open));
    panelOpenButton.setAttribute("aria-expanded", String(open));
  };
  panelOpenButton?.addEventListener("click", () => {
    mapPanel?.dispatchEvent(new Event("open-places"));
    setMapPanelOpen(true);
  });
  mapPanel?.querySelector("[data-map-panel-close]")
    ?.addEventListener("click", () => setMapPanelOpen(false));

  const journeyMapElement = document.getElementById("journey-map");
  const mapDataElement = document.getElementById("map-data");
  if (journeyMapElement && mapDataElement) {
    const mapData = JSON.parse(mapDataElement.textContent);
    const placeEditors = new Map(mapData.placeEditors.map((place) => [place.id, place]));
    const vectorSource = new ol.source.Vector();
    const placementSource = new ol.source.Vector();
    const pointFeaturesById = new Map();
    const placementPanel = document.querySelector("[data-map-placement]");
    const placementName = placementPanel?.querySelector("[data-map-placement-name]");
    const placementDescription = placementPanel?.querySelector("[data-map-placement-description]");
    const placementColor = placementPanel?.querySelector("[data-map-placement-color]");
    const placementColorButton = placementPanel?.querySelector("[data-map-placement-color-button]");
    const placementLatitude = placementPanel?.querySelector("[data-map-placement-latitude]");
    const placementLongitude = placementPanel?.querySelector("[data-map-placement-longitude]");
    const placementApply = placementPanel?.querySelector("[data-map-placement-apply]");
    const placementApplyIcon = placementPanel?.querySelector("[data-map-placement-apply-icon]");
    const placementCancel = placementPanel?.querySelector("[data-map-placement-cancel]");
    const mapPage = journeyMapElement.closest(".map-page");
    let activePlaceId = null;
    let placementCoordinates = null;
    let hiddenPointFeature = null;
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
    const baseMapLayer = createOpenStreetMapLayer();
    const placementLayer = new ol.layer.Vector({ source: placementSource });
    const map = new ol.Map({
      target: journeyMapElement,
      layers: [
        baseMapLayer,
        new ol.layer.Vector({ source: vectorSource }),
        placementLayer,
      ],
      controls: [
        new ol.control.Zoom(),
        new ol.control.Attribution({ collapsible: false }),
      ],
      overlays: [popup],
      view: new ol.View({
        center: ol.proj.fromLonLat([37.6184, 55.7512]),
        zoom: 10,
      }),
    });

    const setPlacementMarker = (latitude, longitude) => {
      placementCoordinates = [latitude, longitude];
      if (placementLatitude) placementLatitude.value = latitude.toFixed(6);
      if (placementLongitude) placementLongitude.value = longitude.toFixed(6);
      placementSource.clear();
      const marker = new ol.Feature({
        geometry: new ol.geom.Point(ol.proj.fromLonLat([longitude, latitude])),
      });
      const markerColor = placementColor?.value || "#191919";
      marker.setStyle(createPlacementStyle(markerColor));
      placementSource.addFeature(marker);
    };

    const restoreHiddenPoint = () => {
      if (!hiddenPointFeature) return;
      const place = placeEditors.get(hiddenPointFeature.get("placeId"));
      hiddenPointFeature.setStyle(createPointStyle(place?.color || "#191919"));
      hiddenPointFeature = null;
    };

    const preparePlaceEditor = () => {
      placementPanel.hidden = false;
      placementApply.disabled = false;
      placementApply.classList.remove("is-saving");
      placementApply.setAttribute("aria-label", "Сохранить место");
      placementApply.title = "Сохранить место";
      if (placementApplyIcon) placementApplyIcon.textContent = "check";
      mapPage?.classList.add("is-picking");
      setMapPanelOpen(false);
      popupElement.hidden = true;
      popup.setPosition(undefined);
    };

    const closePlaceEditor = () => {
      if (placementApply?.disabled) return;
      restoreHiddenPoint();
      placementSource.clear();
      placementCoordinates = null;
      activePlaceId = null;
      placementPanel.hidden = true;
      mapPage?.classList.remove("is-picking");
      panelOpenButton?.focus({ preventScroll: true });
    };

    const startPlaceEditor = (placeId) => {
      if (placementApply?.disabled) return;
      if (!placementPanel || !placementName || !placementDescription
          || !placementColor || !placementApply) return;
      const place = placeEditors.get(Number(placeId));
      if (!place) return;
      restoreHiddenPoint();
      activePlaceId = place.id;
      placementPanel.action = place.updateUrl;
      placementName.value = place.name;
      placementDescription.value = place.description;
      placementColor.value = place.color;
      placementColorButton?.style.setProperty("--marker-color", place.color);
      const latitude = Number.parseFloat(place.lat);
      const longitude = Number.parseFloat(place.lng);
      const hasCoordinates = Number.isFinite(latitude) && Number.isFinite(longitude);
      preparePlaceEditor();
      if (hasCoordinates) {
        hiddenPointFeature = pointFeaturesById.get(place.id) || null;
        hiddenPointFeature?.setStyle(new ol.style.Style({}));
        setPlacementMarker(latitude, longitude);
        map.getView().animate({
          center: ol.proj.fromLonLat([longitude, latitude]),
          zoom: 15,
          duration: 450,
        });
      } else {
        placementCoordinates = null;
        if (placementLatitude) placementLatitude.value = "";
        if (placementLongitude) placementLongitude.value = "";
        placementSource.clear();
      }
    };

    const startNewPlaceEditor = (latitude, longitude) => {
      if (placementApply?.disabled) return;
      if (!placementPanel || !placementName || !placementDescription
          || !placementColor || !placementApply || !mapData.createUrl) return;
      restoreHiddenPoint();
      activePlaceId = "new";
      placementPanel.action = mapData.createUrl;
      placementName.value = "";
      placementDescription.value = "";
      placementColor.value = "#111111";
      placementColorButton?.style.setProperty("--marker-color", "#111111");
      preparePlaceEditor();
      setPlacementMarker(latitude, longitude);
    };

    mapPanel?.addEventListener("open-places", () => {
      if (placementApply?.disabled) return;
      if (activePlaceId !== null) closePlaceEditor();
    });
    mapPanel?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-map-edit-place]");
      if (button) startPlaceEditor(button.dataset.mapEditPlace);
    });
    placementColor?.addEventListener("input", () => {
      placementColorButton?.style.setProperty("--marker-color", placementColor.value);
      if (!placementCoordinates) return;
      setPlacementMarker(...placementCoordinates);
    });
    placementCancel?.addEventListener("click", closePlaceEditor);
    placementPanel?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (placementApply.disabled) return;
      if (activePlaceId === null) {
        event.preventDefault();
        return;
      }
      placementApply.disabled = true;
      placementApply.classList.add("is-saving");
      placementApply.setAttribute("aria-label", "Сохраняем место");
      placementApply.title = "Сохраняем место";
      if (placementApplyIcon) placementApplyIcon.textContent = "progress_activity";
      const status = placementPanel.querySelector("[data-map-save-status]");
      status.textContent = "";
      try {
        const response = await fetch(placementPanel.action, {
          method: "POST", body: new FormData(placementPanel),
          headers: { Accept: "application/json" },
        });
        const result = await response.json();
        if (!response.ok || !result.place) throw new Error(result.error || "Не удалось сохранить место");
        const place = result.place;
        placeEditors.set(place.id, place);
        restoreHiddenPoint();
        placementApply.disabled = false;
        closePlaceEditor();
        refreshMapPlaces();
      } catch (error) {
        status.textContent = error.message || "Не удалось сохранить место. Попробуйте ещё раз.";
      } finally {
        placementApply.disabled = false;
        placementApply.classList.remove("is-saving");
        placementApply.setAttribute("aria-label", "Сохранить место");
        placementApply.title = "Сохранить место";
        if (placementApplyIcon) placementApplyIcon.textContent = "check";
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && activePlaceId !== null) closePlaceEditor();
    });

    const pointsById = new Map();
    const refreshMapPlaces = () => {
      vectorSource.clear();
      pointsById.clear();
      pointFeaturesById.clear();
    [...placeEditors.values()].filter((place) => place.lat !== null && place.lng !== null).forEach((place) => {
      const point = ol.proj.fromLonLat([place.lng, place.lat]);
      pointsById.set(place.id, point);
      const marker = new ol.Feature({
        geometry: new ol.geom.Point(point),
        placeId: place.id,
        popupHtml: `<strong>${escapeHtml(place.name)}</strong>${place.description ? `<br>${escapeHtml(place.description)}` : ""}`,
      });
      marker.setStyle(createPointStyle(place.color));
      pointFeaturesById.set(place.id, marker);
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

      const scroll = mapPanel?.querySelector(".map-panel-scroll");
      if (scroll) {
        scroll.innerHTML = "";
        if (!placeEditors.size) {
          const empty = document.createElement("div");
          empty.className = "map-panel-empty";
          empty.textContent = "Сохранённых мест пока нет. Нажмите на карту, чтобы добавить место.";
          scroll.append(empty);
        }
        for (const mapped of [false, true]) {
          const places = [...placeEditors.values()].filter(place => (place.lat !== null && place.lng !== null) === mapped);
          if (!places.length) continue;
          const group = document.createElement("section");
          group.className = "map-place-group";
          group.innerHTML = `<div class="map-place-group-head"><h2>${mapped ? "На карте" : "Без точки на карте"}</h2><span>${places.length}</span></div>`;
          for (const place of places) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "map-place-editor";
            button.dataset.mapEditPlace = place.id;
            button.setAttribute("aria-label", `Редактировать место ${place.name}`);
            button.innerHTML = `<i style="--marker: ${escapeHtml(place.color)}"></i><span><strong>${escapeHtml(place.name)}</strong><small>${escapeHtml(place.description || (mapped ? "Точка указана" : "Нужна точка"))}</small></span><span class="material-symbols-rounded ui-chevron" aria-hidden="true">chevron_right</span>`;
            group.append(button);
          }
          scroll.append(group);
        }
      }
      const count = panelOpenButton?.querySelector("span");
      if (count) count.textContent = placeEditors.size;
    };
    refreshMapPlaces();
    const activeMapPointers = new Set();
    let mapGestureStart = null;
    let mapGestureMoved = false;
    let mapGestureMultitouch = false;
    map.on("singleclick", (event) => {
      if (mapGestureMoved || mapGestureMultitouch) return;
      if (activePlaceId !== null) {
        const [longitude, latitude] = ol.proj.toLonLat(event.coordinate);
        setPlacementMarker(latitude, longitude);
        return;
      }
      const feature = map.forEachFeatureAtPixel(event.pixel, (item) => item);
      const placeId = feature?.get("placeId");
      if (placeId) {
        popupElement.hidden = true;
        popup.setPosition(undefined);
        startPlaceEditor(placeId);
        return;
      }
      const popupHtml = feature?.get("popupHtml");
      if (!popupHtml) {
        const [longitude, latitude] = ol.proj.toLonLat(event.coordinate);
        startNewPlaceEditor(latitude, longitude);
        return;
      }
      popupElement.hidden = !popupHtml;
      popupElement.innerHTML = popupHtml || "";
      popup.setPosition(popupHtml ? event.coordinate : undefined);
    });
    journeyMapElement.addEventListener("pointerdown", (event) => {
      if (activeMapPointers.size === 0) {
        mapGestureStart = { x: event.clientX, y: event.clientY };
        mapGestureMoved = false;
        mapGestureMultitouch = false;
      }
      activeMapPointers.add(event.pointerId);
      if (activeMapPointers.size > 1) mapGestureMultitouch = true;
    }, { capture: true });
    window.addEventListener("pointermove", (event) => {
      if (!activeMapPointers.has(event.pointerId) || !mapGestureStart) return;
      if (Math.hypot(event.clientX - mapGestureStart.x, event.clientY - mapGestureStart.y) > 10) {
        mapGestureMoved = true;
      }
    }, { capture: true });
    const finishMapPointer = (event) => {
      activeMapPointers.delete(event.pointerId);
      if (activeMapPointers.size === 0) mapGestureStart = null;
    };
    window.addEventListener("pointerup", finishMapPointer, { capture: true });
    window.addEventListener("pointercancel", (event) => {
      if (activeMapPointers.has(event.pointerId)) mapGestureMoved = true;
      finishMapPointer(event);
    }, { capture: true });
    map.on("pointermove", (event) => {
      journeyMapElement.style.cursor = activePlaceId !== null
        ? "crosshair"
        : map.hasFeatureAtPixel(event.pixel) ? "pointer" : "";
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
    const initialPickId = Number.parseInt(mapPage?.dataset.mapPickPlace || "", 10);
    if (Number.isInteger(initialPickId)) {
      startPlaceEditor(initialPickId);
    }
  }
};

if (window.ol) initializeOpenLayersMaps();

document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.dataset.confirmBound = "true";
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js", {
      scope: "/",
      updateViaCache: "none",
    }).catch(() => {});
  });
}

const placesPage = document.querySelector(".places-page");
if (placesPage) {
  const form = placesPage.querySelector(".search-bar");
  const input = form.querySelector("input");
  let timer;
  let controller;
  const searchPlaces = async () => {
    controller?.abort();
    controller = new AbortController();
    const url = new URL(form.action);
    const searchStatus = placesPage.querySelector("[data-place-search-status]");
    searchStatus.textContent = "";
    if (input.value.trim()) url.searchParams.set("q", input.value.trim());
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error("search");
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      for (const selector of [".places-list", ".search-summary", ".history-pagination"]) {
        const current = placesPage.querySelector(selector);
        const next = page.querySelector(selector);
        if (current && next) current.replaceWith(next);
        else if (current) current.remove();
        else if (next) placesPage.append(next);
      }
      history.replaceState(null, "", url);
    } catch (error) {
      if (error.name !== "AbortError") searchStatus.textContent = "Не удалось выполнить поиск. Попробуйте ещё раз.";
    }
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(searchPlaces, 180);
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    clearTimeout(timer);
    searchPlaces();
  });
  placesPage.addEventListener("submit", (event) => {
    if (event.target.matches("form[data-confirm]") && !event.target.dataset.confirmBound
        && !window.confirm(event.target.dataset.confirm)) event.preventDefault();
  });
}
