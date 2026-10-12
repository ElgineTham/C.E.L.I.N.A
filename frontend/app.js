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
const school = document.querySelector("#school");
const home = document.querySelector("#home");
const notify = document.querySelector("#notify");
const notifyNote = document.querySelector("#notify-note");

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

notify.addEventListener("click", allowNotifications);
food.addEventListener("click", () => checkOff("meal"));
water.addEventListener("click", () => checkOff("water"));
school.querySelector(".here").addEventListener("click", () => useHere("school"));
home.querySelector(".here").addEventListener("click", () => useHere("home"));
edit.addEventListener("click", toggleEdit);
editor.addEventListener("submit", addEvent);
repeat.addEventListener("change", syncRepeat);
viewDate.addEventListener("change", () => {
  eventDate.value = viewDate.value;
  clearPrompt();
  loadSchedule();
  loadRoutes();
});

viewDate.value = localDateValue();
eventDate.value = viewDate.value;
registerWorker();
syncNotify();
load();

function registerWorker() {
  if (!("serviceWorker" in navigator)) {
    return;
  }
  navigator.serviceWorker.register("/sw.js");
}

function syncNotify() {
  if (!("Notification" in window) || Notification.permission === "granted") {
    notify.hidden = true;
    return;
  }
  if (Notification.permission === "denied") {
    notify.hidden = true;
    showNotifyNote("Notifications are off in iPhone Settings.");
  }
}

async function allowNotifications() {
  const iphone = /iPhone|iPad/.test(navigator.userAgent);
  const standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
  if (iphone && !standalone) {
    showNotifyNote("Open C.E.L.I.N.A from the home screen icon, then tap Allow notifications.");
    return;
  }
  if (!("Notification" in window) || !("serviceWorker" in navigator)) {
    showNotifyNote("This phone cannot show notifications.");
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    showNotifyNote("Notifications stay off until you allow them.");
    return;
  }
  try {
    const registration = await navigator.serviceWorker.ready;
    const key = await getJSON("/api/vapid");
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key.publicKey),
    });
    await postJSON("/api/push", subscription.toJSON());
    notify.hidden = true;
    showNotifyNote("Notifications are on.");
  } catch (problem) {
    showNotifyNote("Notifications could not be turned on.");
  }
}

function showNotifyNote(message) {
  notifyNote.hidden = false;
  notifyNote.textContent = message;
}

function urlBase64ToUint8Array(value) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from(raw, (character) => character.charCodeAt(0));
}

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
    loadRoutes();
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
    loadRoutes();
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
    loadRoutes();
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

async function loadRoutes() {
  setRide(school, "Looking up the bus.");
  setRide(home, "Looking up the bus.");
  try {
    const routes = await getJSON(`/api/routes?date=${viewDate.value}`);
    renderRide(school, routes.school);
    renderRide(home, routes.home);
  } catch (problem) {
    const message = "The bus route could not be loaded.";
    setRide(school, message);
    setRide(home, message);
  }
}

async function useHere(side) {
  const ride = side === "school" ? school : home;
  const button = ride.querySelector(".here");
  button.disabled = true;
  setRide(ride, "Finding where you are.");
  try {
    const position = await currentPosition();
    const origin = `${position.coords.latitude},${position.coords.longitude}`;
    const route = await postJSON("/api/routes", { side, origin });
    renderRide(ride, route);
  } catch (problem) {
    setRide(ride, problem.message || "Current location is unavailable.");
  } finally {
    button.disabled = false;
  }
}

function currentPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Current location is unavailable."));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, () => {
      reject(new Error("Current location is unavailable."));
    }, { timeout: 10000 });
  });
}

function renderRide(ride, route) {
  ride.querySelector(".leave").textContent = `Leave by: ${clock(route.leaveAt)}`;
  ride.querySelector(".eta").textContent = `ETA: ${clock(route.arriveAt)}`;
  const link = ride.querySelector(".see-route");
  link.href = route.mapsUrl;
  ride.querySelector(".ride-times").hidden = false;
  ride.querySelector(".message").hidden = true;
}

function setRide(ride, message) {
  ride.querySelector(".ride-times").hidden = true;
  const status = ride.querySelector(".message");
  status.hidden = false;
  status.textContent = message;
}

function clock(iso) {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Los_Angeles",
  });
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
