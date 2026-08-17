import assert from "node:assert/strict";
import test from "node:test";

await import("../static/theme.js");

const theme = globalThis.EurostatTheme;

function storageWith(value = null) {
  let stored = value;
  return {
    getItem() {
      return stored;
    },
    setItem(_key, nextValue) {
      stored = nextValue;
    },
    value() {
      return stored;
    },
  };
}

test("stored theme takes precedence over the system preference", () => {
  assert.equal(
    theme.resolveInitialTheme({
      storage: storageWith("light"),
      mediaQuery: { matches: true },
    }),
    "light",
  );
});

test("system preference is used when no theme has been stored", () => {
  assert.equal(
    theme.resolveInitialTheme({
      storage: storageWith(),
      mediaQuery: { matches: true },
    }),
    "dark",
  );
});

test("theme toggles update the root and persist the choice", () => {
  const storage = storageWith();
  const root = { dataset: { theme: "light" }, style: {} };
  const result = theme.toggleTheme({ storage, root });

  assert.equal(result, "dark");
  assert.equal(root.dataset.theme, "dark");
  assert.equal(root.style.colorScheme, "dark");
  assert.equal(storage.value(), "dark");
});

test("invalid stored values safely fall back to the system preference", () => {
  assert.equal(
    theme.resolveInitialTheme({
      storage: storageWith("sepia"),
      mediaQuery: { matches: false },
    }),
    "light",
  );
});
