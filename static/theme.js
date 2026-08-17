(function initializeEurostatTheme(global) {
  "use strict";

  const STORAGE_KEY = "eurostat-lens-theme-v1";
  const LIGHT = "light";
  const DARK = "dark";

  function normalizeTheme(value) {
    return value === DARK || value === LIGHT ? value : null;
  }

  function loadTheme(storage = global.localStorage) {
    try {
      return normalizeTheme(storage?.getItem(STORAGE_KEY));
    } catch {
      return null;
    }
  }

  function systemTheme(mediaQuery = global.matchMedia?.("(prefers-color-scheme: dark)")) {
    return mediaQuery?.matches ? DARK : LIGHT;
  }

  function resolveInitialTheme({
    storage = global.localStorage,
    mediaQuery = global.matchMedia?.("(prefers-color-scheme: dark)"),
  } = {}) {
    return loadTheme(storage) || systemTheme(mediaQuery);
  }

  function applyTheme(theme, root = global.document?.documentElement) {
    const resolved = normalizeTheme(theme) || LIGHT;
    if (root) {
      root.dataset.theme = resolved;
      root.style.colorScheme = resolved;
    }
    return resolved;
  }

  function saveTheme(theme, storage = global.localStorage) {
    const resolved = normalizeTheme(theme) || LIGHT;
    try {
      storage?.setItem(STORAGE_KEY, resolved);
    } catch {
      // Theme switching should still work when browser storage is unavailable.
    }
    return resolved;
  }

  function setTheme(theme, options = {}) {
    const resolved = applyTheme(theme, options.root);
    saveTheme(resolved, options.storage);
    return resolved;
  }

  function toggleTheme(options = {}) {
    const current =
      normalizeTheme(options.root?.dataset?.theme) ||
      normalizeTheme(global.document?.documentElement?.dataset?.theme) ||
      resolveInitialTheme(options);
    return setTheme(current === DARK ? LIGHT : DARK, options);
  }

  const api = Object.freeze({
    DARK,
    LIGHT,
    STORAGE_KEY,
    applyTheme,
    loadTheme,
    resolveInitialTheme,
    saveTheme,
    setTheme,
    systemTheme,
    toggleTheme,
  });

  global.EurostatTheme = api;
  if (global.document?.documentElement) {
    applyTheme(resolveInitialTheme());
  }
})(globalThis);
