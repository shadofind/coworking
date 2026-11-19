(() => {
  const form = document.querySelector("#booking-form");
  if (!form) return;

  const place = form.querySelector("#id_place");
  const date = form.querySelector("#id_day");
  const start = form.querySelector("#id_start_hour");
  const end = form.querySelector("#id_end_hour");
  const grid = document.querySelector("#availability-grid");
  const caption = document.querySelector("#availability-caption");
  const apiUrl = form.dataset.availabilityUrl;
  const labels = { free: "Свободно", busy: "Занято", past: "Прошедшее время" };

  function updateSelection() {
    const first = Number(start.value);
    const last = Number(end.value);
    grid.querySelectorAll(".slot").forEach((slot) => {
      const hour = Number(slot.dataset.hour);
      slot.classList.toggle("selected", hour >= first && hour < last && !slot.disabled);
    });
  }

  async function loadAvailability() {
    if (!place.value || !date.value) return;
    caption.textContent = "Проверяем свободные часы…";
    grid.replaceChildren();
    try {
      const params = new URLSearchParams({ place: place.value, date: date.value });
      const response = await fetch(`${apiUrl}?${params}`, {
        headers: { Accept: "application/json" },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось загрузить доступность.");
      caption.textContent = `${data.place} · ${new Date(`${data.date}T12:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}`;
      data.slots.forEach(({ hour, status }) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `slot ${status}`;
        button.dataset.hour = hour;
        button.textContent = `${String(hour).padStart(2, "0")}:00`;
        button.title = labels[status];
        button.setAttribute("aria-label", `${hour}:00 — ${labels[status]}`);
        button.disabled = status !== "free";
        button.addEventListener("click", () => {
          start.value = String(hour);
          end.value = String(hour + 1);
          updateSelection();
        });
        grid.append(button);
      });
      updateSelection();
    } catch (error) {
      caption.textContent = error.message;
    }
  }

  place.addEventListener("change", loadAvailability);
  date.addEventListener("change", loadAvailability);
  start.addEventListener("change", updateSelection);
  end.addEventListener("change", updateSelection);
  loadAvailability();
})();
