using System.Text.Json.Nodes;

namespace HENTAIStudio;

internal sealed class ProjectEditor : Form
{
    private readonly TextBox id = new(), name = new(), root = new(), commands = JsonBox(), environment = JsonBox(), metrics = new() { Text = "metrics.jsonl" };
    private readonly ComboBox kind = new() { DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly Dictionary<string, Control> llmFields = [];
    private readonly Label error = new() { AutoSize = true, ForeColor = Color.Firebrick, MaximumSize = new Size(650, 0) };
    private readonly JsonObject? originalProfile;
    public JsonObject Definition { get; private set; } = new();

    public ProjectEditor(JsonObject? project)
    {
        Text = project is null ? "Register project" : "Edit project"; StartPosition = FormStartPosition.CenterParent;
        AutoScaleDimensions = new SizeF(96, 96); AutoScaleMode = AutoScaleMode.Dpi; Font = new Font("Segoe UI", 9.5f);
        Size = new Size(720, 700); MinimumSize = new Size(420, 400);
        id.Text = project.Text("id"); id.ReadOnly = project is not null; name.Text = project.Text("name"); root.Text = project.Text("root");
        commands.Text = JsonData.Pretty(project?["commands"] ?? new JsonObject { ["train"] = new JsonArray("python", "train.py") });
        environment.Text = JsonData.Pretty(project?["environment"]); metrics.Text = project.Text("metrics_file", "metrics.jsonl");
        originalProfile = project?["llm"] as JsonObject;
        kind.Items.AddRange(["External commands", "Scratch LLM"]); kind.SelectedIndex = originalProfile is null ? 0 : 1;
        var tabs = new TabControl { Dock = DockStyle.Fill };
        var general = FormGrid();
        Add(general, "Display name", name); Add(general, "Project ID", id); Add(general, "Backend project directory", root); Add(general, "Project type", kind); Add(general, "Metrics filename", metrics);
        Add(general, "Paths refer to the backend machine, including when connected to AWS.", new Label { AutoSize = true, Text = "Unregistering retains source files and job history." });
        var generalTab = new TabPage("Project"); generalTab.Controls.Add(general); tabs.TabPages.Add(generalTab);
        var commandTab = new TabPage("Commands & environment"); var commandPanel = FormGrid();
        commands.Height = 180; environment.Height = 100;
        Add(commandPanel, "Commands (JSON argument arrays)", commands); Add(commandPanel, "Environment (JSON string map)", environment);
        Add(commandPanel, "Commands run directly, without a shell.", new Label { Text = "Use {output_dir} and {project_root}. Scratch profiles generate the train command.", AutoSize = true });
        commandTab.Controls.Add(commandPanel); tabs.TabPages.Add(commandTab);
        var llmTab = new TabPage("Scratch LLM"); var profile = FormGrid();
        foreach (var (key, label, fallback) in new[] { ("python", "Training Python executable", "python"), ("model", "Local model configuration directory", ""), ("tokenizer", "Local tokenizer directory", ""), ("dataset", "JSONL dataset", "") })
        { var field = new TextBox { Text = originalProfile.Text(key, fallback) }; llmFields[key] = field; Add(profile, label, field); }
        foreach (var (key, label, value, min, max, decimals) in new[] {
            ("max_length", "Sequence length", 1024m, 16m, 131072m, 0), ("batch_size", "Batch size", 1m, 1m, 1024m, 0),
            ("gradient_accumulation", "Gradient accumulation", 8m, 1m, 65536m, 0), ("learning_rate", "Learning rate", .0003m, .000000001m, 1m, 9),
            ("epochs", "Epochs", 1m, .001m, 10000m, 3), ("max_steps", "Optimizer steps (-1 uses epochs)", -1m, -1m, 100000000m, 0),
            ("save_steps", "Checkpoint interval", 100m, 1m, 100000000m, 0), ("seed", "Random seed", 42m, 0m, 4294967295m, 0) })
        {
            var field = new NumericUpDown { Minimum = min, Maximum = max, DecimalPlaces = decimals, Value = Math.Clamp((decimal)(originalProfile.Number(key) ?? (double)value), min, max), Increment = decimals == 9 ? .0001m : 1m };
            llmFields[key] = field; Add(profile, label, field);
        }
        var precision = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList }; precision.Items.AddRange(["fp32", "bf16", "fp16"]); precision.SelectedItem = originalProfile.Text("precision", "fp32"); llmFields["precision"] = precision; Add(profile, "Precision", precision);
        var checkpointing = new CheckBox { Text = "Enable gradient checkpointing", Checked = originalProfile?["gradient_checkpointing"] is null || originalProfile.Flag("gradient_checkpointing"), AutoSize = true };
        llmFields["gradient_checkpointing"] = checkpointing; Add(profile, "Memory", checkpointing);
        llmTab.Controls.Add(profile); tabs.TabPages.Add(llmTab);
        kind.SelectedIndexChanged += (_, _) => ApplyKind();
        void ApplyKind() { profile.Enabled = kind.SelectedIndex == 1; metrics.ReadOnly = kind.SelectedIndex == 1; if (kind.SelectedIndex == 1) metrics.Text = "metrics.jsonl"; }
        ApplyKind();
        var save = new Button { Text = "Save project", AutoSize = true, MinimumSize = new Size(100, 32) };
        var cancel = new Button { Text = "Cancel", AutoSize = true, DialogResult = DialogResult.Cancel, MinimumSize = new Size(75, 32) };
        var footer = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Bottom, Padding = new Padding(10), FlowDirection = FlowDirection.RightToLeft }; footer.Controls.AddRange([save, cancel, error]);
        Controls.Add(tabs); Controls.Add(footer); AcceptButton = save; CancelButton = cancel;
        save.Click += (_, _) =>
        {
            try
            {
                if (id.Text.Trim().Length == 0 || name.Text.Trim().Length == 0 || root.Text.Trim().Length == 0) throw new InvalidOperationException("Supply a project ID, display name, and backend directory.");
                var commandMap = JsonNode.Parse(commands.Text) as JsonObject ?? throw new InvalidOperationException("Commands must be a JSON object.");
                var variables = JsonNode.Parse(environment.Text) as JsonObject ?? throw new InvalidOperationException("Environment must be a JSON object.");
                JsonObject? llm = null;
                if (kind.SelectedIndex == 1)
                {
                    llm = originalProfile?.DeepClone().AsObject() ?? new();
                    foreach (var (key, field) in llmFields)
                        llm[key] = field switch { TextBox t => JsonValue.Create(t.Text.Trim()), NumericUpDown n => JsonValue.Create(n.Value), CheckBox c => JsonValue.Create(c.Checked), ComboBox c => JsonValue.Create(c.SelectedItem?.ToString()), _ => null };
                }
                Definition = new JsonObject { ["id"] = id.Text.Trim(), ["name"] = name.Text.Trim(), ["root"] = root.Text.Trim(), ["commands"] = commandMap, ["environment"] = variables, ["metrics_file"] = metrics.Text.Trim(), ["llm"] = llm };
                DialogResult = DialogResult.OK; Close();
            }
            catch (Exception exception) { error.Text = exception.Message; }
        };
    }
    private static TextBox JsonBox() => new() { Multiline = true, ScrollBars = ScrollBars.Both, WordWrap = false, AcceptsReturn = true, AcceptsTab = true, Font = new Font("Consolas", 10) };
    private static TableLayoutPanel FormGrid() => new() { Dock = DockStyle.Fill, AutoScroll = true, ColumnCount = 1, Padding = new Padding(16) };
    private static void Add(TableLayoutPanel panel, string label, Control field)
    {
        var row = panel.RowCount++; panel.RowStyles.Add(new(SizeType.AutoSize));
        panel.Controls.Add(new Label { Text = label, AutoSize = true, Margin = new Padding(0, 10, 0, 4) }, 0, row);
        row = panel.RowCount++; panel.RowStyles.Add(new(SizeType.AutoSize)); field.Dock = DockStyle.Top; panel.Controls.Add(field, 0, row);
    }
}
