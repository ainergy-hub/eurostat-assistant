const chat = document.querySelector("#chat");
const composer = document.querySelector("#composer");
const promptInput = document.querySelector("#prompt");
const sendButton = document.querySelector("#send");
const statusBadge = document.querySelector("#status");

const history = [];

function addMessage(role, content, pending = false) {
  const article = document.createElement("article");
  article.className = `message ${role}${pending ? " pending" : ""}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;
  article.appendChild(bubble);
  chat.appendChild(article);
  chat.scrollTop = chat.scrollHeight;
  return article;
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    if (data.has_e2b_api_key && data.has_openrouter_api_key) {
      statusBadge.textContent = "Ready";
      statusBadge.className = "status ready";
      return;
    }
    statusBadge.textContent = "Missing API key";
    statusBadge.className = "status error";
  } catch {
    statusBadge.textContent = "Backend offline";
    statusBadge.className = "status error";
  }
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = promptInput.value.trim();
  if (!message) return;

  addMessage("user", message);
  history.push({ role: "user", content: message });
  promptInput.value = "";
  sendButton.disabled = true;
  const pending = addMessage("assistant", "Running Eurostat agent in E2B", true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: history.slice(-10, -1) }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "The agent request failed.");
    }
    pending.classList.remove("pending");
    pending.querySelector(".bubble").textContent = data.answer;
    history.push({ role: "assistant", content: data.answer });
  } catch (error) {
    pending.classList.remove("pending");
    pending.querySelector(".bubble").textContent = `Error: ${error.message}`;
  } finally {
    sendButton.disabled = false;
    promptInput.focus();
  }
});

promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    composer.requestSubmit();
  }
});

checkHealth();
