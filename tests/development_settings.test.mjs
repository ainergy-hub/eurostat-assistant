import assert from "node:assert/strict";
import test from "node:test";

import {
  MODEL_STORAGE_KEY,
  loadSelectedModel,
  readableSettingName,
  saveSelectedModel,
} from "../static/development_settings.js";

const models = [
  { id: "openai/gpt-4.1-mini" },
  { id: "openai/gpt-4.1" },
];

function storageWith(value = null) {
  let stored = value;
  return {
    getItem(key) {
      assert.equal(key, MODEL_STORAGE_KEY);
      return stored;
    },
    setItem(key, nextValue) {
      assert.equal(key, MODEL_STORAGE_KEY);
      stored = nextValue;
    },
    value() {
      return stored;
    },
  };
}

test("loads an available saved model", () => {
  assert.equal(
    loadSelectedModel(models, models[0].id, storageWith(models[1].id)),
    models[1].id,
  );
});

test("falls back when a saved model is no longer enabled", () => {
  assert.equal(loadSelectedModel(models, models[0].id, storageWith("retired/model")), models[0].id);
});

test("only saves models exposed by the deployment", () => {
  const storage = storageWith();
  assert.equal(saveSelectedModel(models[1].id, models, storage), true);
  assert.equal(storage.value(), models[1].id);
  assert.equal(saveSelectedModel("unknown/model", models, storage), false);
});

test("formats internal setting names for readers", () => {
  assert.equal(readableSettingName("inspect_dimensions"), "Inspect Dimensions");
});
