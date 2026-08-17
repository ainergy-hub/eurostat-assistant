export async function streamChat(payload, onEvent, { onUnauthorized } = {}) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) {
      onUnauthorized?.("Your app session expired. Enter the password again.");
    }
    throw new Error(data.detail || "The agent request failed.");
  }
  if (!response.body) throw new Error("The browser could not read the live agent response.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      onEvent(event);
      if (event.type === "error") throw new Error(event.message || "The agent request failed.");
      if (event.type === "result") result = event.data;
    }
    if (done) break;
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer);
    onEvent(event);
    if (event.type === "error") throw new Error(event.message || "The agent request failed.");
    if (event.type === "result") result = event.data;
  }
  if (!result) throw new Error("The agent stream ended before returning an answer.");
  return result;
}

export async function generateChatTitle(message, { onUnauthorized } = {}) {
  const response = await fetch("/api/chat/title", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      onUnauthorized?.("Your app session expired. Enter the password again.");
    }
    throw new Error(data.detail || "The title model request failed.");
  }
  if (typeof data.title !== "string" || !data.title.trim()) {
    throw new Error("The title model did not return a usable title.");
  }
  return data;
}
