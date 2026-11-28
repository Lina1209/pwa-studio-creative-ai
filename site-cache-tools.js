/* Safe per-browser PWA shell cache controls. Never clears user data or account storage. */
(() => {
  "use strict";
  const PREFIX = "pwa-studio-shell-";
  async function clearSiteCache() {
    if (!("caches" in window)) throw new Error("Этот браузер не поддерживает очистку кеша приложения.");
    const names = await caches.keys();
    const owned = names.filter(name => name.startsWith(PREFIX));
    const results = await Promise.all(owned.map(name => caches.delete(name)));
    if (results.some(ok => !ok)) throw new Error("Не все кеши удалось очистить. Попробуйте ещё раз.");
    if ("serviceWorker" in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      const ours = registrations.filter(reg => {
        const script = reg.active?.scriptURL || reg.waiting?.scriptURL || reg.installing?.scriptURL || "";
        return script.startsWith(location.origin) && /\/sw\.js(?:$|\?)/.test(script);
      });
      await Promise.all(ours.map(reg => reg.update().catch(() => undefined)));
    }
    return { deleted: owned.length };
  }
  function init() {
    const button = document.getElementById("clearSiteCache");
    const status = document.getElementById("clearSiteCacheStatus");
    if (!button || !status) return;
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      const confirmed = window.confirm("Очистить кеш файлов PWA Studio на этом устройстве? Проекты, изображения, аккаунт и настройки сохранятся.");
      if (!confirmed) return;
      button.disabled = true;
      status.textContent = "Очищаем кеш приложения…";
      try {
        const result = await clearSiteCache();
        status.textContent = result.deleted
          ? "Готово: кеш приложения очищен. Сейчас страница обновится."
          : "Старый кеш не найден. Сейчас страница обновится.";
        window.setTimeout(() => window.location.reload(), 900);
      } catch (error) {
        status.textContent = "Не удалось очистить кеш: " + (error?.message || "неизвестная ошибка");
        button.disabled = false;
      }
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
  window.PWAStudioCacheTools = Object.freeze({ clearSiteCache });
})();