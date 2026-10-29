const $ = id => document.getElementById(id);
const fields = {
  python: ["llmPython", "python"],
  model: ["llmModel", ""],
  tokenizer: ["llmTokenizer", ""],
  dataset: ["llmDataset", ""],
  max_length: ["llmLength", 1024],
  batch_size: ["llmBatch", 1],
  gradient_accumulation: ["llmAccumulation", 8],
  learning_rate: ["llmRate", 0.0003],
  epochs: ["llmEpochs", 1],
  max_steps: ["llmSteps", -1],
  save_steps: ["llmSave", 100],
  precision: ["llmPrecision", "fp32"],
  seed: ["llmSeed", 42],
};
export function toggleLLMFields() {
  const llm = $("fieldType").value === "llm";
  $("llmFields").hidden = !llm;
  $("llmFields").disabled = !llm;
  $("commandsField").hidden = llm;
  $("commandsHelp").hidden = llm;
  $("fieldCommands").disabled = llm;
  $("fieldMetrics").readOnly = llm;
  if (llm) $("fieldMetrics").value = "metrics.jsonl";
}
export function openLLMProfile(profile) {
  $("fieldType").value = profile ? "llm" : "generic";
  for (const [key, [id, fallback]] of Object.entries(fields)) $(id).value = profile?.[key] ?? fallback;
  $("llmGradientCheckpointing").checked = profile?.gradient_checkpointing ?? true;
  toggleLLMFields();
}
export function readLLMProfile() {
  if ($("fieldType").value !== "llm") return null;
  const profile = {
    gradient_checkpointing: $("llmGradientCheckpointing").checked
  };
  for (const [key, [id, fallback]] of Object.entries(fields)) profile[key] = typeof fallback === "number" ? Number($(id).value) : $(id).value.trim();
  return profile;
}
