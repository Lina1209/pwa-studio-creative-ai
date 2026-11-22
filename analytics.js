/* Privacy-minimizing aggregate page-view counter. */
(() => {
  const apiBase = (window.PWA_API_BASE || "").replace(/\/$/, "");
  const allowedRoutes = new Set(["home","create","movie","editor","prompts","library","account","voice","scenes","assistant","guide","rules","settings"]);
  const route = () => {
    const active = document.querySelector(".view.active");
    const name = active?.id?.replace(/^view-/, "") || "home";
    return allowedRoutes.has(name) ? name : "other";
  };
  const randomToken = () => {
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  };
  const day = new Date().toISOString().slice(0, 10);
  const tokenKey = "pwa_analytics_daily_" + day;
  let token;
  try {
    token = localStorage.getItem(tokenKey);
    if (!token || !/^[a-f0-9]{48}$/.test(token)) {
      token = randomToken();
      localStorage.setItem(tokenKey, token);
    }
  } catch (_) {
    token = randomToken();
  }
  // One event per document load; the UUID makes retries safe.
  const eventId = crypto.randomUUID();
  const payload = { event_id: eventId, visitor_token: token, route_group: route() };
  const endpoint = apiBase + "/api/analytics/visit";
  const send = () => fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
    credentials: "omit"
  }).then(r => r.ok ? r.json() : null).then(updateCounter).catch(() => {});
  function updateCounter(stats) {
    if (!stats || !Number.isSafeInteger(stats.total_page_views)) return;
    document.querySelectorAll("[data-total-visits]").forEach(el => {
      el.textContent = new Intl.NumberFormat(document.documentElement.lang || "ru").format(stats.total_page_views);
    });
    document.querySelectorAll("[data-today-visits]").forEach(el => {
      el.textContent = new Intl.NumberFormat(document.documentElement.lang || "ru").format(stats.today_page_views || 0);
    });
  }
  send();
  fetch(apiBase + "/api/analytics/stats", { credentials: "omit" })
    .then(r => r.ok ? r.json() : null).then(updateCounter).catch(() => {});
})();
