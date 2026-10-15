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

const routeScreen = document.querySelector("#route-screen");
const routeTitle = document.querySelector("#route-title");
const routeWhen = document.querySelector("#route-when");
const routeSteps = document.querySelector("#route-steps");
const routeMap = document.querySelector("#route-map");
const shownRoutes = new WeakMap();
let routeLeaflet = null;
let routeWatch = 0;

document.querySelector("#route-close").addEventListener("click", closeRoute);
school.querySelector(".see-route").addEventListener("click", () => openShownRoute(school));
home.querySelector(".see-route").addEventListener("click", () => openShownRoute(home));

function renderRide(ride, route) {
  shownRoutes.set(ride, route);
  ride.querySelector(".leave").textContent = `Leave by: ${clock(route.leaveAt)}`;
  ride.querySelector(".eta").textContent = `ETA: ${clock(route.arriveAt)}`;
  ride.querySelector(".ride-times").hidden = false;
  ride.querySelector(".message").hidden = true;
}

function openShownRoute(ride) {
  const route = shownRoutes.get(ride);
  if (route) {
    showRoute(route);
  }
}

function showRoute(route) {
  routeTitle.textContent = route.label || "Route";
  routeWhen.textContent = `Leave by ${clock(route.leaveAt)} · ETA ${clock(route.arriveAt)}`;
  routeSteps.replaceChildren();
  for (const [index, step] of (route.steps || []).entries()) {
    const item = document.createElement("li");
    if (index === 0) {
      item.className = "next";
    }
    const title = document.createElement("span");
    title.className = "step-title";
    title.textContent = index === 0 ? `Next: ${step.title}` : step.title;
    const detail = document.createElement("span");
    detail.className = "step-detail";
    detail.textContent = step.detail || "";
    item.append(title, detail);
    if (step.leaveAt) {
      const when = document.createElement("span");
      when.className = "step-time";
      when.textContent = `Leave ${clock(step.leaveAt)} · Arrive ${clock(step.arriveAt)}`;
      item.append(when);
    }
    routeSteps.append(item);
  }
  routeScreen.hidden = false;
  drawRoute(route);
  watchRouteLocation();
}

function closeRoute() {
  routeScreen.hidden = true;
  if (routeWatch) {
    navigator.geolocation.clearWatch(routeWatch);
    routeWatch = 0;
  }
  if (routeLeaflet) {
    routeLeaflet.remove();
    routeLeaflet = null;
  }
}

function drawRoute(route) {
  if (!window.L) {
    return;
  }
  if (routeLeaflet) {
    routeLeaflet.remove();
  }
  routeLeaflet = L.map(routeMap, { zoomControl: false });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(routeLeaflet);
  const points = decodePath(route.path || "");
  const markers = [];
  if (points.length) {
    const line = L.polyline(points, { color: "#2f6fed", weight: 5 }).addTo(routeLeaflet);
    markers.push(line);
  }
  for (const step of route.steps || []) {
    if (step.mode === "transit" && step.lat != null && step.lng != null) {
      markers.push(L.circleMarker([step.lat, step.lng], {
        radius: 7,
        color: "#243028",
        fillColor: "#f6e2a8",
        fillOpacity: 1,
      }).addTo(routeLeaflet).bindTooltip(step.title));
    }
  }
  if (markers.length) {
    routeLeaflet.fitBounds(L.featureGroup(markers).getBounds(), { padding: [24, 24] });
  } else {
    routeLeaflet.setView([47.66, -122.31], 12);
  }
  setTimeout(() => routeLeaflet.invalidateSize(), 0);
}

function watchRouteLocation() {
  if (!navigator.geolocation || !routeLeaflet) {
    return;
  }
  if (routeWatch) {
    navigator.geolocation.clearWatch(routeWatch);
  }
  const dot = L.circleMarker([0, 0], {
    radius: 8,
    color: "white",
    weight: 2,
    fillColor: "#e85c5c",
    fillOpacity: 1,
  }).addTo(routeLeaflet);
  dot.setStyle({ opacity: 0, fillOpacity: 0 });
  routeWatch = navigator.geolocation.watchPosition((position) => {
    dot.setLatLng([position.coords.latitude, position.coords.longitude]);
    dot.setStyle({ opacity: 1, fillOpacity: 1 });
  });
}

function decodePath(encoded) {
  const points = [];
  let index = 0;
  let lat = 0;
  let lng = 0;
  while (index < encoded.length) {
    let shift = 0;
    let result = 0;
    let byte = 0;
    do {
      byte = encoded.charCodeAt(index) - 63;
      index += 1;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lat += result & 1 ? ~(result >> 1) : result >> 1;
    shift = 0;
    result = 0;
    do {
      byte = encoded.charCodeAt(index) - 63;
      index += 1;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lng += result & 1 ? ~(result >> 1) : result >> 1;
    points.push([lat / 1e5, lng / 1e5]);
  }
  return points;
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

// Fill text, image, and audio for each reason. Leave a field blank until that file exists.
const reasons = [
  { text: "Your beautiful face outdoes the 7 wonders of the earth!", image: "/videos/yoshi_flower.mp4", audio: "/audios/one.mp3" },
  { text: "Your beautiful smile stuns my world!", image: "/videos/yoshi_rolling.mp4", audio: "/audios/two.mp3" },
  { text: "Your wonderful eyes shines brighter than the sun!", image: "/videos/yoshi_egg.mp4", audio: "/audios/three.mp3" },
  { text: "Your sense of humor makes life much easier!", image: "/videos/yoshi_standing.mp4", audio: "/audios/four.mp3" },
  { text: "Your IQ and EQ that makes you such a lovely person to talk to!", image: "/videos/yoshi_flower.mp4", audio: "/audios/five.mp3" },
  { text: "Your hugs and hands that strengthens me as I have someone to live this life with!", image: "/videos/yoshi_rolling.mp4", audio: "/audios/six.mp3" },
  { text: "Your picky eating habits and exquisite taste that teaches me another perspective!", image: "/videos/yoshi_egg.mp4", audio: "/audios/seven.mp3" },
  { text: "Your little arguments that may make me mad, but always teaches me something new every single day!", image: "/videos/yoshi_standing.mp4", audio: "/audios/eight.mp3" },
  { text: "Your principles and opinions that shape me into a better person!", image: "/videos/yoshi_flower.mp4", audio: "/audios/nine.mp3" },
  { text: "Your personality and behaviors that sparks a cuteness aggression", image: "/videos/yoshi_rolling.mp4", audio: "/audios/ten.mp3" },
  { text: "Despite our fights, it teaches me more about our relationship. It makes me grow in this relationship.", image: "/videos/yoshi_egg.mp4", audio: "/audios/eleven.mp3" },
  { text: "Despite our disagreements, I would never want to have it with anyone else. You're the reaason I never get tired of resolving disagreements in this relationship.", image: "/videos/yoshi_standing.mp4", audio: "/audios/twelve.mp3" },
  { text: "You give me a reason to become a better person. A reason to step out of my comfort zone and become a partner capable of providing you with a life we dream of.", image: "/videos/yoshi_flower.mp4", audio: "/audios/thirteen.mp3" },
  { text: "You give me the courage to try and a reason to fail, because no matter what, I believe you'll be there with me every step of our journey together.", image: "/videos/yoshi_rolling.mp4", audio: "/audios/fourteen.mp3" },
  { text: "I mean it when you bring colors into my life. You bring all sorts of emotion from fun to sadness, from fights to laughters, and that's what makes life much more beautiful.", image: "/videos/yoshi_egg.mp4", audio: "/audios/fifteen.mp3" },
  { text: "I mean it when you are beautiful, because you alone makes me realize how lucky I am to have you. People may have wealth, people may have strength, people may have looks, but trust me when I take pride because no one can have a partner like you.", image: "/videos/yoshi_standing.mp4", audio: "/audios/sixteen.mp3" },
  { text: "I mean it when you make me feel and do stuffs I never thought I was capable of. Because of you Celine, I saw traits in myself that I never thought was there.", image: "/videos/yoshi_flower.mp4", audio: "/audios/seventeen.mp3" },
  { text: "I mean it Celine when you showed me what true love is. A love that is not always about laughs and fun, but a love that is beautiful and meaningful in its own special way.", image: "/videos/yoshi_rolling.mp4", audio: "/audios/eighteen.mp3" },
  { text: "You are the reason it's so hard to resist spending money, to resist skipping class and work. Because being with you makes me feel safe, makes me feel peace, makes me feel like I'm home.", image: "/videos/yoshi_egg.mp4", audio: "/audios/nineteen.mp3" },
  { text: "Our inside jokes. If you know you know hehe.", image: "/videos/yoshi_standing.mp4", audio: "/audios/twenty.mp3" },
  { text: "YOU. YOU are the sole reason why I love you. Celine, no matter what the other reasons are, they cannot be compared to this one reason. Because I don't need a reason to love you. Being yourself is the biggest and greatest reason I fell for you. For that reason, please walk with me and let's see together what the future has in store for us!", image: "/videos/yoshi_flower.mp4", audio: "/audios/twentyone.mp3" },
];

const reasonsCard = document.querySelector("#reasons");
const reasonText = document.querySelector("#reason-text");
const reasonCount = document.querySelector("#reason-count");
const reasonPlay = document.querySelector("#reason-play");
const reasonImage = document.querySelector("#reason-image");
let reasonIndex = 0;
let reasonVoice = null;
let reasonSwipe = false;
let reasonStartX = 0;
let reasonStartY = 0;

reasonsCard.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) {
    return;
  }
  reasonStartX = event.clientX;
  reasonStartY = event.clientY;
  reasonSwipe = false;
});

reasonsCard.addEventListener("pointerup", (event) => {
  const across = event.clientX - reasonStartX;
  const down = event.clientY - reasonStartY;
  if (Math.abs(across) >= 40 && Math.abs(across) > Math.abs(down)) {
    reasonSwipe = true;
    stepReason(across < 0 ? 1 : -1);
    return;
  }
  if (event.target.closest("#reason-play")) {
    playReason();
  }
});

function showReason(index) {
  reasonIndex = index;
  const reason = reasons[index];
  reasonText.textContent = reason.text;
  reasonCount.textContent = `${index + 1} / ${reasons.length}`;
  reasonPlay.setAttribute("aria-label", `Play reason ${index + 1}`);
  if (reason.image) {
    reasonImage.hidden = false;
    reasonImage.src = reason.image;
    reasonImage.play().catch(() => {});
  } else {
    reasonImage.hidden = true;
    reasonImage.removeAttribute("src");
    reasonImage.pause();
  }
  stopReason();
}

function stepReason(direction) {
  const next = (reasonIndex + direction + reasons.length) % reasons.length;
  showReason(next);
}

function playReason() {
  const src = reasons[reasonIndex].audio;
  if (!src) {
    return;
  }
  stopReason();
  reasonVoice = new Audio(src);
  reasonVoice.play().catch(() => {});
}

function stopReason() {
  if (!reasonVoice) {
    return;
  }
  reasonVoice.pause();
  reasonVoice = null;
}

showReason(0);

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
