import { $ } from "./dom.js";
import { createDiffusionWorkspace } from "./diffusion.js";
import { createLLMWorkspace } from "./llm.js";
import { createPoller } from "./poller.js";

const workspaces = {diffusion: createDiffusionWorkspace(), llm: createLLMWorkspace()};
let active = "diffusion";
const poller = createPoller(() => workspaces[active].refresh(), 4000);

function selectWorkspace(name) {
  if (!workspaces[name]) return;
  workspaces[active].deactivate();
  active = name;
  $("diffusionWorkspace").hidden = name !== "diffusion";
  $("llmWorkspace").hidden = name !== "llm";
  document.querySelectorAll(".workspace-tab").forEach(button => {
    const selected = button.dataset.workspace === name;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
  });
  poller.start();
}

document.querySelectorAll(".workspace-tab").forEach(button => {
  button.addEventListener("click", () => selectWorkspace(button.dataset.workspace));
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    poller.stop();
    workspaces[active].deactivate();
  } else poller.start();
});
window.addEventListener("pagehide", () => {
  poller.stop();
  Object.values(workspaces).forEach(workspace => workspace.deactivate());
});
selectWorkspace(active);
