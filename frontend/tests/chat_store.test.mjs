import assert from "node:assert/strict";

import {
  LEGACY_STORAGE_KEY,
  normalizeLegacyState,
  requestPersistentStorage,
} from "../static/chat_store.js";

const legacyState = {
  activeChatId: "second",
  chats: [
    {
      id: "first",
      title: "Population",
      createdAt: "2026-07-26T10:00:00.000Z",
      updatedAt: "2026-07-26T10:01:00.000Z",
      messages: [
        { role: "user", content: "Population?" },
        { role: "assistant", content: "Population answer" },
      ],
    },
    {
      id: "second",
      title: "Inflation",
      createdAt: "2026-07-26T11:00:00.000Z",
      updatedAt: "2026-07-26T11:02:00.000Z",
      messages: [{ role: "user", content: "Inflation?" }],
      events: [{ type: "request_error", message: "Example" }],
    },
    { id: "", messages: [] },
    { id: "malformed" },
  ],
};

const normalized = normalizeLegacyState(legacyState);
assert.equal(normalized.activeChatId, "second");
assert.equal(normalized.chats.length, 2);
assert.equal(normalized.chats[0].messageCount, 2);
assert.equal(normalized.chats[0].turnCount, 1);
assert.equal(normalized.chats[0].eventCount, 0);
assert.equal(normalized.chats[1].eventCount, 1);
assert.deepEqual(normalized.chats[1].events, legacyState.chats[1].events);
assert.equal(normalizeLegacyState({ chats: [] }), null);
assert.equal(normalizeLegacyState(null), null);

const fallbackActive = normalizeLegacyState({
  activeChatId: "missing",
  chats: [{ id: "available", messages: [] }],
});
assert.equal(fallbackActive.activeChatId, "available");

assert.equal(
  await requestPersistentStorage({ persist: async () => true }),
  true,
);
assert.equal(
  await requestPersistentStorage({
    persist: async () => {
      throw new Error("Denied");
    },
  }),
  false,
);
assert.equal(await requestPersistentStorage(null), false);
assert.equal(LEGACY_STORAGE_KEY, "eurostat-lens-chats-v1");

console.log("chat store tests passed");
