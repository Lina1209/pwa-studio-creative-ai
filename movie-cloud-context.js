(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.PWAMovieCloudContext = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function capture(userId, authContextVersion) {
    if (!userId || !Number.isInteger(authContextVersion)) return null;
    return Object.freeze({ ownerId: String(userId), authContextVersion });
  }
  function isCurrent(context, currentUserId, currentVersion) {
    return !!context &&
      context.ownerId === (currentUserId || null) &&
      context.authContextVersion === currentVersion;
  }
  function setPendingContext(state, context) {
    state.pendingContext = context || null;
  }
  function takePendingContext(state, currentCheck) {
    const context = state.pendingContext || null;
    state.pendingContext = null;
    return context && currentCheck(context) ? context : null;
  }
  return Object.freeze({ capture, isCurrent, setPendingContext, takePendingContext });
});
