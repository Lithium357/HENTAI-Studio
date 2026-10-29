import {
  requestJSON
} from "./api.js";
const $ = id => document.getElementById(id);

export function bindChat(getState) {
  const conversations = new Map();
  let projectId, tab = "jobs",
    busy = false,
    controller;
  let loaded = false,
    loadedDevice = null;
  const selected = () => getState().projectId;
  const conversation = () => {
    const id = selected();
    if (!conversations.has(id)) conversations.set(id, {
      messages: [],
      system: "",
      prompt: "",
      temperature: "0.7",
      tokens: "128"
    });
    return conversations.get(id);
  };
  const path = suffix => `/api/projects/${encodeURIComponent(selected())}/chat${suffix}`;

  function saveDraft() {
    if (!projectId) return;
    const item = conversations.get(projectId);
    if (item) Object.assign(item, {
      system: $("chatSystem").value,
      prompt: $("chatPrompt").value,
      temperature: $("chatTemperature").value,
      tokens: $("chatTokens").value
    });
  }

  function controls() {
    const enabled = !!getState().project?.llm && getState().connected && !busy;
    $("loadChat").disabled = !enabled || loaded;
    $("unloadChat").disabled = !enabled || !loaded;
    $("sendChat").disabled = !enabled || !loaded;
    $("clearChat").disabled = busy;
    $("editProject").disabled = !getState().canEdit || loaded;
    $("removeProject").disabled = !getState().canEdit || loaded;
    if (loaded && loadedDevice === "cuda") $("start").disabled = true;
    for (const id of ["chatSource", "chatCheckpoint", "chatDevice", "chatSystem", "chatTemperature", "chatTokens", "chatPrompt"]) $(id).disabled = busy;
  }

  function showStatus(result) {
    loaded = result.loaded;
    loadedDevice = result.device;
    $("chatStatus").textContent = loaded ? `Loaded · ${result.device.toUpperCase()}` : "No model loaded";
    $("chatStatus").dataset.state = loaded ? "running" : "stopped";
    $("chatStatus").title = result.checkpoint || "";
    controls();
  }

  function messages() {
    const list = $("chatMessages");
    list.replaceChildren();
    for (const message of conversation().messages) {
      const bubble = document.createElement("div");
      bubble.className = `chat-message ${message.role}`;
      const role = document.createElement("strong");
      role.textContent = message.role === "user" ? "You" : "Your model";
      const content = document.createElement("p");
      content.textContent = message.content || "(No text generated)";
      bubble.append(role, content);
      list.append(bubble);
    }
    if (!list.children.length) {
      const empty = document.createElement("p");
      empty.className = "chat-empty";
      empty.textContent = "Load a saved local checkpoint, then send a prompt. Scratch models can produce rough responses early in training.";
      list.append(empty);
    }
    list.scrollTop = list.scrollHeight;
  }
  async function operation(suffix, body, label) {
    if (busy) return;
    const id = selected();
    controller = new AbortController();
    busy = true;
    $("chatError").textContent = "";
    $("chatStatus").textContent = label;
    controls();
    try {
      const result = await requestJSON(path(suffix), {
        method: "POST",
        body: JSON.stringify(body),
        signal: controller.signal,
        timeout: 130000
      });
      if (selected() === id) return result;
    } catch (error) {
      if (selected() === id && error.name !== "AbortError") $("chatError").textContent = error.message;
    } finally {
      if (selected() === id) {
        busy = false;
        controls();
      }
    }
  }
  async function status() {
    const id = selected();
    try {
      const result = await requestJSON(path(""));
      if (selected() === id && !busy) showStatus(result);
    } catch (error) {
      if (selected() === id) {
        loaded = false;
        $("chatError").textContent = error.message;
        controls();
      }
    }
  }

  function setTab(value) {
    tab = value;
    $("overviewSummary").hidden = tab === "chat";
    $("launchPanel").hidden = tab === "chat" || !getState().project;
    $("chatPanel").hidden = tab !== "chat" || !getState().project?.llm;
    $("jobWorkspace").hidden = tab === "chat" && !!getState().project?.llm;
    $("jobsTab").setAttribute("aria-selected", String(tab === "jobs"));
    $("chatTab").setAttribute("aria-selected", String(tab === "chat"));
    $("jobsTab").tabIndex = tab === "jobs" ? 0 : -1;
    $("chatTab").tabIndex = tab === "chat" ? 0 : -1;
    if (tab === "chat") void status();
  }
  for (const id of ["jobsTab", "chatTab"]) $(id).onkeydown = event => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const value = event.key === "Home" ? "jobs" : event.key === "End" ? "chat" : tab === "jobs" ? "chat" : "jobs";
      setTab(value);
      $(value === "jobs" ? "jobsTab" : "chatTab").focus();
    }
  };
  $("jobsTab").onclick = () => setTab("jobs");
  $("chatTab").onclick = () => setTab("chat");
  $("chatSource").onchange = () => {
    $("chatCheckpoint").value = $("chatSource").value === "job" ? "model" : "";
    renderSource();
  };

  function renderSource() {
    const job = getState().job;
    $("chatSourceHint").textContent = $("chatSource").value === "job" ? `Selected job: ${job?.id || "none"}. Use model for the final weights or checkpoint-N for an intermediate save.` : "Enter a local saved-model directory, absolute or relative to the project. Model files are never downloaded.";
  }
  $("loadChat").onclick = async () => {
    const checkpoint = $("chatCheckpoint").value.trim();
    const job = $("chatSource").value === "job" ? getState().jobId : null;
    if (!checkpoint || ($("chatSource").value === "job" && !job)) {
      $("chatError").textContent = "Select a job and checkpoint, or enter a local model directory.";
      return;
    }
    const result = await operation("/load", {
      checkpoint,
      job_id: job,
      device: $("chatDevice").value
    }, "Loading local checkpoint…");
    if (result) {
      conversation().messages = [];
      messages();
      showStatus(result);
    } else if (getState().project?.llm) void status();
  };
  $("unloadChat").onclick = async () => {
    const result = await operation("/unload", {}, "Unloading…");
    if (result) showStatus(result);
  };
  $("clearChat").onclick = () => {
    conversation().messages = [];
    messages();
    $("chatError").textContent = "";
  };
  $("chatForm").onsubmit = async event => {
    event.preventDefault();
    if (busy || !loaded) return;
    const submittingProject = selected();
    const item = conversation(),
      text = $("chatPrompt").value.trim();
    if (!text) return;
    const temperature = Number($("chatTemperature").value),
      max_tokens = Number($("chatTokens").value);
    const system = $("chatSystem").value.trim();
    const request = [...(system ? [{
      role: "system",
      content: system
    }] : []), ...item.messages, {
      role: "user",
      content: text
    }];
    item.messages.push({
      role: "user",
      content: text
    });
    messages();
    const result = await operation("/completions", {
      messages: request,
      temperature,
      max_tokens
    }, "Generating locally…");
    if (result) {
      item.messages.push({
        role: "assistant",
        content: result.content
      });
      $("chatPrompt").value = "";
    } else item.messages.pop();
    if (selected() === submittingProject) {
      messages();
      $("chatStatus").textContent = loaded ? "Model ready" : "No model loaded";
    }
  };
  return {
    render() {
      const state = getState();
      $("llmTabs").hidden = !state.project?.llm;
      if (projectId !== state.projectId) {
        saveDraft();
        controller?.abort();
        projectId = state.projectId;
        busy = false;
        loaded = false;
        tab = "jobs";
        const item = conversation();
        $("chatSystem").value = item.system;
        $("chatPrompt").value = item.prompt;
        $("chatTemperature").value = item.temperature;
        $("chatTokens").value = item.tokens;
        $("chatError").textContent = "";
        messages();
      }
      $("overviewSummary").hidden = tab === "chat" && !!state.project?.llm;
      $("launchPanel").hidden = !state.project || (tab === "chat" && !!state.project.llm);
      $("chatPanel").hidden = tab !== "chat" || !state.project?.llm;
      $("jobWorkspace").hidden = tab === "chat" && !!state.project?.llm;
      $("jobsTab").setAttribute("aria-selected", String(tab === "jobs"));
      $("chatTab").setAttribute("aria-selected", String(tab === "chat"));
      $("jobsTab").tabIndex = tab === "jobs" ? 0 : -1;
      $("chatTab").tabIndex = tab === "chat" ? 0 : -1;
      renderSource();
      controls();
    }
  };
}
