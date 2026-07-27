export const CHAT_DB_NAME = "eurostat-lens-history";
export const CHAT_DB_VERSION = 1;
export const LEGACY_STORAGE_KEY = "eurostat-lens-chats-v1";

const CHATS_STORE = "chats";
const MESSAGES_STORE = "messages";
const EVENTS_STORE = "events";
const SETTINGS_STORE = "settings";
const ACTIVE_CHAT_KEY = "activeChatId";

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("IndexedDB request failed."));
  });
}

function transactionComplete(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () =>
      reject(transaction.error || new Error("IndexedDB transaction was aborted."));
    transaction.onerror = () =>
      reject(transaction.error || new Error("IndexedDB transaction failed."));
  });
}

function chatMetadata(record) {
  const messages = Array.isArray(record?.messages) ? record.messages : [];
  const events = Array.isArray(record?.events) ? record.events : [];
  return {
    id: record.id,
    title: record.title || "Untitled investigation",
    createdAt: record.createdAt || new Date().toISOString(),
    updatedAt: record.updatedAt || record.createdAt || new Date().toISOString(),
    messageCount:
      Number.isInteger(record.messageCount) && record.messageCount >= 0
        ? record.messageCount
        : messages.length,
    turnCount:
      Number.isInteger(record.turnCount) && record.turnCount >= 0
        ? record.turnCount
        : messages.filter((message) => message?.role === "user").length,
    eventCount:
      Number.isInteger(record.eventCount) && record.eventCount >= 0
        ? record.eventCount
        : events.length,
  };
}

function hydratedChat(metadata, messages = [], events = []) {
  return {
    ...metadata,
    messages,
    events,
    loaded: true,
  };
}

function storedEntry(chatId, sequence, value) {
  return { chatId, sequence, value };
}

function valuesFromEntries(entries) {
  return entries.map((entry) => entry.value);
}

export function normalizeLegacyState(value) {
  if (!value || !Array.isArray(value.chats)) return null;
  const chats = value.chats
    .filter(
      (record) =>
        record &&
        typeof record.id === "string" &&
        record.id &&
        Array.isArray(record.messages),
    )
    .map((record) => ({
      ...chatMetadata(record),
      messages: record.messages,
      events: Array.isArray(record.events) ? record.events : [],
    }));
  if (!chats.length) return null;
  const activeChatId = chats.some((record) => record.id === value.activeChatId)
    ? value.activeChatId
    : chats[0].id;
  return { chats, activeChatId };
}

export class ChatHistoryStore {
  constructor({
    indexedDB = globalThis.indexedDB,
    keyRange = globalThis.IDBKeyRange,
    legacyStorage = globalThis.localStorage,
  } = {}) {
    if (!indexedDB || !keyRange) {
      throw new Error("This browser does not support IndexedDB.");
    }
    this.indexedDB = indexedDB;
    this.keyRange = keyRange;
    this.legacyStorage = legacyStorage;
    this.database = null;
  }

  async open() {
    if (this.database) return this.database;
    const request = this.indexedDB.open(CHAT_DB_NAME, CHAT_DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(CHATS_STORE)) {
        const chats = database.createObjectStore(CHATS_STORE, { keyPath: "id" });
        chats.createIndex("updatedAt", "updatedAt");
      }
      if (!database.objectStoreNames.contains(MESSAGES_STORE)) {
        database.createObjectStore(MESSAGES_STORE, {
          keyPath: ["chatId", "sequence"],
        });
      }
      if (!database.objectStoreNames.contains(EVENTS_STORE)) {
        database.createObjectStore(EVENTS_STORE, {
          keyPath: ["chatId", "sequence"],
        });
      }
      if (!database.objectStoreNames.contains(SETTINGS_STORE)) {
        database.createObjectStore(SETTINGS_STORE, { keyPath: "key" });
      }
    };
    this.database = await requestResult(request);
    this.database.onversionchange = () => {
      this.database.close();
      this.database = null;
    };
    return this.database;
  }

  async initialize(fallbackChat) {
    await this.open();
    const migratedCount = await this.migrateLegacyHistory();
    let chats = await this.listChats();

    if (!chats.length) {
      await this.createChat(fallbackChat, true);
      chats = [chatMetadata(fallbackChat)];
    }

    let activeChatId = await this.getActiveChatId();
    if (!chats.some((record) => record.id === activeChatId)) {
      activeChatId = chats[0].id;
      await this.setActiveChat(activeChatId);
    }

    const active = await this.loadChat(activeChatId);
    return {
      chats: chats.map((record) =>
        record.id === activeChatId
          ? active
          : { ...record, messages: [], events: [], loaded: false },
      ),
      activeChatId,
      migratedCount,
    };
  }

  async listChats() {
    const database = await this.open();
    const transaction = database.transaction(CHATS_STORE, "readonly");
    const done = transactionComplete(transaction);
    const records = await requestResult(transaction.objectStore(CHATS_STORE).getAll());
    await done;
    return records.sort(
      (left, right) => (Date.parse(right.updatedAt) || 0) - (Date.parse(left.updatedAt) || 0),
    );
  }

  async loadChat(chatId) {
    const database = await this.open();
    const transaction = database.transaction(
      [CHATS_STORE, MESSAGES_STORE, EVENTS_STORE],
      "readonly",
    );
    const done = transactionComplete(transaction);
    const range = this.keyRange.bound(
      [chatId, 0],
      [chatId, Number.MAX_SAFE_INTEGER],
    );
    const [metadata, messageEntries, eventEntries] = await Promise.all([
      requestResult(transaction.objectStore(CHATS_STORE).get(chatId)),
      requestResult(transaction.objectStore(MESSAGES_STORE).getAll(range)),
      requestResult(transaction.objectStore(EVENTS_STORE).getAll(range)),
    ]);
    await done;
    if (!metadata) return null;
    return hydratedChat(
      metadata,
      valuesFromEntries(messageEntries),
      valuesFromEntries(eventEntries),
    );
  }

  async createChat(record, makeActive = false) {
    const database = await this.open();
    const stores = makeActive ? [CHATS_STORE, SETTINGS_STORE] : [CHATS_STORE];
    const transaction = database.transaction(stores, "readwrite");
    const done = transactionComplete(transaction);
    transaction.objectStore(CHATS_STORE).add(chatMetadata(record));
    if (makeActive) {
      transaction
        .objectStore(SETTINGS_STORE)
        .put({ key: ACTIVE_CHAT_KEY, value: record.id });
    }
    await done;
  }

  async appendMessage(chatId, message, patch = {}) {
    const database = await this.open();
    const transaction = database.transaction(
      [CHATS_STORE, MESSAGES_STORE],
      "readwrite",
    );
    const done = transactionComplete(transaction);
    const chats = transaction.objectStore(CHATS_STORE);
    const current = await requestResult(chats.get(chatId));
    if (!current) {
      transaction.abort();
      await done.catch(() => {});
      throw new Error("The investigation no longer exists.");
    }

    const sequence = current.messageCount || 0;
    transaction
      .objectStore(MESSAGES_STORE)
      .add(storedEntry(chatId, sequence, message));
    const updated = {
      ...current,
      ...patch,
      id: current.id,
      messageCount: sequence + 1,
      turnCount: (current.turnCount || 0) + (message.role === "user" ? 1 : 0),
    };
    chats.put(updated);
    await done;
    return updated;
  }

  async appendEvent(chatId, event, patch = {}) {
    const database = await this.open();
    const transaction = database.transaction(
      [CHATS_STORE, EVENTS_STORE],
      "readwrite",
    );
    const done = transactionComplete(transaction);
    const chats = transaction.objectStore(CHATS_STORE);
    const current = await requestResult(chats.get(chatId));
    if (!current) {
      transaction.abort();
      await done.catch(() => {});
      throw new Error("The investigation no longer exists.");
    }

    const sequence = current.eventCount || 0;
    transaction
      .objectStore(EVENTS_STORE)
      .add(storedEntry(chatId, sequence, event));
    const updated = {
      ...current,
      ...patch,
      id: current.id,
      eventCount: sequence + 1,
    };
    chats.put(updated);
    await done;
    return updated;
  }

  async setActiveChat(chatId) {
    const database = await this.open();
    const transaction = database.transaction(SETTINGS_STORE, "readwrite");
    const done = transactionComplete(transaction);
    transaction
      .objectStore(SETTINGS_STORE)
      .put({ key: ACTIVE_CHAT_KEY, value: chatId });
    await done;
  }

  async getActiveChatId() {
    const database = await this.open();
    const transaction = database.transaction(SETTINGS_STORE, "readonly");
    const done = transactionComplete(transaction);
    const setting = await requestResult(
      transaction.objectStore(SETTINGS_STORE).get(ACTIVE_CHAT_KEY),
    );
    await done;
    return setting?.value || null;
  }

  async deleteChat(chatId) {
    const database = await this.open();
    const transaction = database.transaction(
      [CHATS_STORE, MESSAGES_STORE, EVENTS_STORE],
      "readwrite",
    );
    const done = transactionComplete(transaction);
    const range = this.keyRange.bound(
      [chatId, 0],
      [chatId, Number.MAX_SAFE_INTEGER],
    );
    transaction.objectStore(CHATS_STORE).delete(chatId);
    transaction.objectStore(MESSAGES_STORE).delete(range);
    transaction.objectStore(EVENTS_STORE).delete(range);
    await done;
  }

  async migrateLegacyHistory() {
    let rawState;
    try {
      rawState = this.legacyStorage?.getItem(LEGACY_STORAGE_KEY);
    } catch {
      return 0;
    }
    if (!rawState) return 0;

    let legacy;
    try {
      legacy = normalizeLegacyState(JSON.parse(rawState));
    } catch {
      return 0;
    }
    if (!legacy) return 0;

    const database = await this.open();
    const countTransaction = database.transaction(CHATS_STORE, "readonly");
    const countDone = transactionComplete(countTransaction);
    const existingCount = await requestResult(
      countTransaction.objectStore(CHATS_STORE).count(),
    );
    await countDone;
    if (existingCount) return 0;

    const transaction = database.transaction(
      [CHATS_STORE, MESSAGES_STORE, EVENTS_STORE, SETTINGS_STORE],
      "readwrite",
    );
    const done = transactionComplete(transaction);
    const chats = transaction.objectStore(CHATS_STORE);
    const messages = transaction.objectStore(MESSAGES_STORE);
    const events = transaction.objectStore(EVENTS_STORE);
    for (const record of legacy.chats) {
      chats.add(chatMetadata(record));
      record.messages.forEach((message, sequence) => {
        messages.add(storedEntry(record.id, sequence, message));
      });
      record.events.forEach((event, sequence) => {
        events.add(storedEntry(record.id, sequence, event));
      });
    }
    transaction
      .objectStore(SETTINGS_STORE)
      .put({ key: ACTIVE_CHAT_KEY, value: legacy.activeChatId });
    await done;

    try {
      this.legacyStorage?.removeItem(LEGACY_STORAGE_KEY);
    } catch {
      // The history is safely migrated even if the old browser entry cannot be removed.
    }
    return legacy.chats.length;
  }
}

export async function requestPersistentStorage(
  storageManager = globalThis.navigator?.storage,
) {
  if (!storageManager?.persist) return false;
  try {
    return await storageManager.persist();
  } catch {
    return false;
  }
}
