"use strict";

const formatLocalNow = () => {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 16);
};

const setCurrentTime = (id) => {
  const input = document.getElementById(id);
  if (input) input.value = formatLocalNow();
};

const debounce = (callback, delay = 180) => {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => callback(...args), delay);
  };
};

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
      menu.classList.toggle("open", places.length > 0);
    } catch (_) {
      menu.classList.remove("open");
    }
  });

  input.addEventListener("input", load);
  input.addEventListener("focus", load);
  input.addEventListener("change", () => {
    if (input.value.trim() && input.dataset.timeTarget) setCurrentTime(input.dataset.timeTarget);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") menu.classList.remove("open");
  });
  document.addEventListener("click", (event) => {
    if (!input.parentElement.contains(event.target)) menu.classList.remove("open");
  });
};

document.querySelectorAll("[data-place-input]").forEach(initializeAutocomplete);
document.querySelectorAll("[data-now]").forEach((button) => {
  button.addEventListener("click", () => setCurrentTime(button.dataset.now));
});

const tripForm = document.querySelector("[data-trip-form]");
if (tripForm) {
  const detailBox = tripForm.querySelector("[data-detail-fields]");
  const detailWrap = tripForm.querySelector("[data-detail-wrap]");
  const detailLabel = tripForm.querySelector("[data-detail-label]");
  const detailInput = tripForm.querySelector("#transport_detail");
  const taxiFields = tripForm.querySelector("[data-taxi-fields]");
  const updateDetails = () => {
    const selected = tripForm.querySelector("[name=transport_type]:checked")?.value;
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
  tripForm.querySelectorAll("[name=transport_type]").forEach((radio) => radio.addEventListener("change", updateDetails));
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
