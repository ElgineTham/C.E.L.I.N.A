self.addEventListener("push", (event) => {
  const payload = event.data ? event.data.json() : {};
  const title = payload.title || "C.E.L.I.N.A";
  const body = payload.body || "You have a reminder.";
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      data: { url: "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url || "/"));
});
