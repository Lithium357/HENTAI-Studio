import {
  openLLMProfile,
  readLLMProfile,
  toggleLLMFields
} from "./llm-editor.js";
import {
  $
} from "./views.js";

export function bindProjectEditor(save) {
  $("fieldType").onchange = toggleLLMFields;
  let editing = false;
  let saving = false;
  $("closeEditor").onclick = () => {
    if (!saving) $("editor").close();
  };
  $("editor").addEventListener("cancel", event => {
    if (saving) event.preventDefault();
  });
  $("projectForm").onsubmit = async event => {
    event.preventDefault();
    if (saving) return;
    saving = true;
    $("saveProject").disabled = true;
    $("closeEditor").disabled = true;
    try {
      const definition = {
        id: $("fieldId").value.trim(),
        name: $("fieldName").value.trim(),
        root: $("fieldRoot").value.trim(),
        commands: $("fieldType").value === "llm" ? {} : JSON.parse($("fieldCommands").value),
        llm: readLLMProfile(),
        environment: JSON.parse($("fieldEnv").value),
        metrics_file: $("fieldMetrics").value.trim(),
      };
      await save(definition, editing);
      $("editor").close();
    } catch (error) {
      $("formError").textContent = error.message;
    } finally {
      saving = false;
      $("saveProject").disabled = false;
      $("closeEditor").disabled = false;
    }
  };
  return {
    open(project) {
      if (saving) return;
      editing = !!project;
      const definition = project || {
        id: "",
        name: "",
        root: "",
        commands: {
          train: ["python", "train.py"]
        },
        environment: {},
        metrics_file: "metrics.jsonl"
      };
      $("editorTitle").textContent = editing ? "Edit project" : "Register project";
      $("fieldId").disabled = editing;
      for (const [element, key] of [
          ["fieldId", "id"],
          ["fieldName", "name"],
          ["fieldRoot", "root"],
          ["fieldMetrics", "metrics_file"]
        ]) $(element).value = definition[key];
      $("fieldCommands").value = JSON.stringify(definition.commands, null, 2);
      $("fieldEnv").value = JSON.stringify(definition.environment, null, 2);
      openLLMProfile(definition.llm);
      $("formError").textContent = "";
      $("editor").showModal();
    },
  };
}
