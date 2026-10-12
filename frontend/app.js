const scheduleCard = document.querySelector("#schedule");
const events = document.querySelector("#events");
const empty = document.querySelector("#empty");
const error = document.querySelector("#error");
const edit = document.querySelector("#edit");
const editor = document.querySelector("#editor");
const viewDate = document.querySelector("#view-date");
const eventDate = document.querySelector("#event-date");
const activity = document.querySelector("#activity");
const start = document.querySelector("#start");
const end = document.querySelector("#end");
const repeat = document.querySelector("#repeat");
const untilLabel = document.querySelector("#until-label");
const until = document.querySelector("#until");
const note = document.querySelector("#schedule-note");
const prompt = document.querySelector("#schedule-prompt");
const food = document.querySelector("#food");
const water = document.querySelector("#water");

const repeatLabels = {
  daily: "Every day",
  weekdays: "Weekdays",
  weekly: "Every week",
  monthly: "Every month",
};

const choiceLabels = {
  delete: "Delete the old one",
  keep: "Keep the old one",
  merge: "Merge",
  only_that_day: "Only that day",
  all_future: "That day and after",
};

food.addEventListener("click", () => checkOff("meal"));
water.addEventListener("click", () => checkOff("water"));
edit.addEventListener("click", toggleEdit);
editor.addEventListener("submit", addEvent);
repeat.addEventListener("change", syncRepeat);
viewDate.addEventListener("change", () => {
  eventDate.value = viewDate.value;
  clearPrompt();
  loadSchedule();
});

viewDate.value = localDateValue();
eventDate.value = viewDate.value;
load();

async function load() {
  try {
    const [schedule, icons] = await Promise.all([
      getJSON(`/api/today?date=${viewDate.value}`),
      getJSON("/api/icons"),
    ]);
    renderSchedule(schedule);
    renderIcon(food, icons.food);
    renderIcon(water, icons.water);
    error.hidden = true;
  } catch (problem) {
    error.hidden = false;
  }
}

function toggleEdit() {
  const editing = scheduleCard.classList.toggle("editing");
  editor.hidden = !editing;
  edit.textContent = editing ? "Done" : "Edit";
  if (!editing) {
    clearPrompt();
  }
}

async function loadSchedule() {
  try {
    renderSchedule(await getJSON(`/api/today?date=${viewDate.value}`));
    error.hidden = true;
  } catch (problem) {
    showNote(problem.message);
  }
}

function localDateValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

async function addEvent(event) {
  event.preventDefault();
  await saveEvent();
}

function syncRepeat() {
  const repeating = repeat.value !== "";
  untilLabel.hidden = !repeating;
  if (!repeating) {
    until.value = "";
  }
}

async function saveEvent(choice) {
  clearPrompt();
  const name = activity.value.trim();
  const startTime = start.value;
  try {
    const saved = await postJSON("/api/today", {
      activity_name: name,
      start_time: startTime,
      end_time: end.value,
      date: eventDate.value,
      repeating_frequency: repeat.value,
      repeating_ends: until.value,
      choice,
    });
    if (saved.prompt) {
      showPrompt(saved, saveEvent);
      return;
    }
    if (choice !== "keep" && eventDate.value !== viewDate.value) {
      viewDate.value = eventDate.value;
    }
    const shown = await getJSON(`/api/today?date=${viewDate.value}`);
    renderSchedule(shown);
    editor.reset();
    syncRepeat();
    eventDate.value = viewDate.value;
    error.hidden = true;
    const visible = shown.some(
      (event) => event.activity_name === name && event.start_time === startTime,
    );
    if (!visible && choice !== "keep") {
      showNote("Saved. It does not fall on this day.");
    }
  } catch (problem) {
    showNote(problem.message);
  }
}

async function removeEvent(name, choice) {
  clearPrompt();
  try {
    const saved = await postJSON("/api/today/delete", {
      activity_name: name,
      date: viewDate.value,
      choice,
    });
    if (saved.prompt) {
      showPrompt(saved, (picked) => removeEvent(name, picked));
      return;
    }
    renderSchedule(saved);
    error.hidden = true;
  } catch (problem) {
    showNote(problem.message);
  }
}

function showPrompt(result, onChoice) {
  prompt.replaceChildren();
  const text = document.createElement("p");
  text.textContent = result.prompt;
  const choices = document.createElement("div");
  choices.className = "choices";
  for (const choice of result.choices) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = choiceLabels[choice] || choice;
    button.addEventListener("click", () => onChoice(choice));
    choices.append(button);
  }
  prompt.append(text, choices);
  prompt.hidden = false;
}

function clearPrompt() {
  prompt.hidden = true;
  prompt.replaceChildren();
  note.hidden = true;
}

function showNote(message) {
  note.textContent = message;
  note.hidden = false;
}

async function checkOff(kind) {
  const button = kind === "meal" ? food : water;
  button.disabled = true;
  try {
    const icons = await getJSON(`/api/icons/${kind}`, { method: "POST" });
    renderIcon(food, icons.food);
    renderIcon(water, icons.water);
    error.hidden = true;
  } catch (problem) {
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
}

function renderSchedule(schedule) {
  events.replaceChildren();
  empty.hidden = schedule.length > 0;
  for (const event of schedule) {
    const item = document.createElement("li");
    const details = document.createElement("div");
    const when = document.createElement("span");
    when.className = "when";
    when.textContent = `${event.start_time}–${event.end_time}`;
    details.append(when, document.createTextNode(event.activity_name));
    const frequency = repeatLabels[event.repeating_frequency];
    if (frequency) {
      const repeatLine = document.createElement("span");
      repeatLine.className = "repeat";
      repeatLine.textContent = frequency;
      details.append(repeatLine);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => removeEvent(event.activity_name));
    item.append(details, remove);
    events.append(item);
  }
}

const iconPictures = {
  meal: {
    done: ["/images/full_yoshi.jpg", "Yoshi is full"],
    waiting: ["/images/hungry_yoshi.png", "Yoshi is hungry"],
  },
  water: {
    done: ["/images/not_thirsty_yoshi.jpg", "Yoshi has had water"],
    waiting: ["/images/thirsty_yoshi_square.jpg", "Yoshi is thirsty"],
  },
};

function renderIcon(button, icon) {
  button.dataset.status = icon.status;
  button.querySelector(".message").textContent = icon.message;
  const pictures = iconPictures[icon.kind];
  const [src, alt] = icon.status === "done" ? pictures.done : pictures.waiting;
  const image = button.querySelector("img");
  image.src = src;
  image.alt = alt;
}

async function getJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(response.statusText);
  }
  return response.json();
}

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}
