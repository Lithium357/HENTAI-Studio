using System.Text.Json.Nodes;

namespace HENTAIStudio;

internal sealed class NativeChat : UserControl
{
    private readonly StudioApi api;
    private readonly CancellationToken lifetime;
    private readonly Func<Task> refresh;
    private readonly ComboBox source = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 180 };
    private readonly ComboBox device = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 110 };
    private readonly TextBox checkpoint = new() { Text = "model", Width = 260, PlaceholderText = "Model directory or checkpoint-N" };
    private readonly TextBox system = new() { Dock = DockStyle.Fill, PlaceholderText = "Optional system prompt", MaxLength = 8192 };
    private readonly TextBox prompt = new() { Dock = DockStyle.Fill, Multiline = true, ScrollBars = ScrollBars.Vertical, MaxLength = 8192, AccessibleName = "Chat prompt" };
    private readonly RichTextBox transcript = new() { Dock = DockStyle.Fill, ReadOnly = true, DetectUrls = false, AccessibleName = "Local model conversation" };
    private readonly NumericUpDown temperature = new() { Minimum = 0, Maximum = 2, DecimalPlaces = 2, Increment = .05m, Value = .7m, Width = 70 };
    private readonly NumericUpDown tokens = new() { Minimum = 1, Maximum = 2048, Value = 128, Width = 80 };
    private readonly Button load = new() { Text = "Load checkpoint", AutoSize = true }, unload = new() { Text = "Unload model", AutoSize = true }, send = new() { Text = "Send prompt", AutoSize = true }, clear = new() { Text = "Clear conversation", AutoSize = true };
    private readonly Button latest = new() { Text = "Load latest checkpoint", AutoSize = true, MinimumSize = new Size(160, 32) };
    private readonly CheckBox autoLoad = new() { Text = "Auto-load latest when opening this tester", AutoSize = true };
    private readonly CheckBox advanced = new() { Text = "Advanced options ▸", Appearance = Appearance.Button, AutoSize = true };
    private readonly Label status = new() { Text = "No model loaded. CPU is the default.", Dock = DockStyle.Fill, AutoEllipsis = true };
    private readonly Dictionary<string, Conversation> conversations = [];
    private string? project, job;
    private bool busy, loaded, connected, checking;
    private string lastError = "";
    private int revision;
    private string loadedCheckpoint = "";
    private Conversation Current => conversations.TryGetValue(project ?? "", out var value) ? value : conversations[project ?? ""] = new();

    public NativeChat(StudioApi api, CancellationToken lifetime, Func<Task> refresh)
    {
        this.api = api; this.lifetime = lifetime; this.refresh = refresh; Dock = DockStyle.Fill;
        source.Items.AddRange(["Selected job output", "Local directory"]); source.SelectedIndex = 0;
        device.Items.AddRange(["cpu", "cuda"]); device.SelectedIndex = 0;
        var grid = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 8, Padding = new Padding(10) };
        grid.RowStyles.Add(new(SizeType.AutoSize)); grid.RowStyles.Add(new(SizeType.AutoSize)); grid.RowStyles.Add(new(SizeType.Absolute, 48)); grid.RowStyles.Add(new(SizeType.AutoSize)); grid.RowStyles.Add(new(SizeType.AutoSize)); grid.RowStyles.Add(new(SizeType.Percent, 100)); grid.RowStyles.Add(new(SizeType.Absolute, 75)); grid.RowStyles.Add(new(SizeType.AutoSize));
        grid.Controls.Add(new Label { Text = "1. Load the latest saved weights.  2. Type a prompt below.  3. Send it to your model.\nCPU testing can run alongside training. Checkpoints and inference live on the backend machine.", AutoSize = true, Dock = DockStyle.Fill, Padding = new Padding(0, 0, 0, 8) }, 0, 0);
        grid.Controls.Add(Flow(latest, new Label { Text = "Run on", AutoSize = true, Padding = new Padding(4, 5, 0, 0) }, device, unload, autoLoad), 0, 1);
        grid.Controls.Add(status, 0, 2); grid.Controls.Add(Flow(advanced), 0, 3);
        var options = new TableLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, ColumnCount = 1, Visible = false };
        options.Controls.Add(Flow(new Label { Text = "Manual source", AutoSize = true }, source, checkpoint, load));
        options.Controls.Add(Flow(new Label { Text = "Temperature", AutoSize = true }, temperature, new Label { Text = "Response token limit", AutoSize = true }, tokens));
        options.Controls.Add(system); grid.Controls.Add(options, 0, 4);
        advanced.CheckedChanged += (_, _) => { options.Visible = advanced.Checked; advanced.Text = advanced.Checked ? "Advanced options ▾" : "Advanced options ▸"; };
        grid.Controls.Add(transcript, 0, 5); grid.Controls.Add(prompt, 0, 6); grid.Controls.Add(Flow(send, clear), 0, 7); Controls.Add(grid);
        latest.Click += async (_, _) => await LoadLatest();
        autoLoad.CheckedChanged += async (_, _) => { if (autoLoad.Checked) await AutoLoadLatest(); };
        VisibleChanged += async (_, _) => await AutoLoadLatest();
        source.SelectedIndexChanged += (_, _) => checkpoint.Text = source.SelectedIndex == 0 ? "model" : "";
        load.Click += async (_, _) => await Operation(async (id, conversation) =>
        {
            if (string.IsNullOrWhiteSpace(checkpoint.Text) || source.SelectedIndex == 0 && job is null) throw new InvalidOperationException("Choose a job checkpoint or a saved local model directory.");
            var result = await api.Request(Path(id) + "/load", lifetime, HttpMethod.Post, new JsonObject { ["checkpoint"] = checkpoint.Text.Trim(), ["job_id"] = source.SelectedIndex == 0 ? job : null, ["device"] = device.SelectedItem?.ToString() });
            if (id == project) { loaded = result.Flag("loaded"); loadedCheckpoint = result.Text("checkpoint"); conversation.Messages.Clear(); RenderConversation(); }
            await refresh();
        }, "Loading local checkpoint…");
        unload.Click += async (_, _) => await Operation(async (id, _) => { await api.Request(Path(id) + "/unload", lifetime, HttpMethod.Post); if (id == project) loaded = false; await refresh(); }, "Unloading model…");
        clear.Click += (_, _) => { Current.Messages.Clear(); RenderConversation(); };
        send.Click += async (_, _) =>
        {
            if (busy || !loaded || string.IsNullOrWhiteSpace(prompt.Text)) return;
            var text = prompt.Text.Trim(); var systemPrompt = system.Text.Trim(); var budget = (int)tokens.Value; var heat = temperature.Value;
            await Operation(async (id, conversation) =>
            {
                var messages = new JsonArray();
                if (systemPrompt.Length > 0) messages.Add(new JsonObject { ["role"] = "system", ["content"] = systemPrompt });
                foreach (var message in conversation.Messages) messages.Add(message.DeepClone());
                messages.Add(new JsonObject { ["role"] = "user", ["content"] = text });
                var result = await api.Request(Path(id) + "/completions", lifetime, HttpMethod.Post, new JsonObject { ["messages"] = messages, ["temperature"] = heat, ["max_tokens"] = budget });
                conversation.Messages.Add(new JsonObject { ["role"] = "user", ["content"] = text });
                conversation.Messages.Add(new JsonObject { ["role"] = "assistant", ["content"] = result.Text("content") });
                conversation.Draft = "";
                if (id == project) { prompt.Clear(); RenderConversation(); }
            }, "Generating locally…");
        };
        ApplyControls();
    }
    private static FlowLayoutPanel Flow(params Control[] controls) { var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = true }; panel.Controls.AddRange(controls); return panel; }
    private static string Path(string id) => StudioApi.ProjectPath(id) + "/chat";
    private Task AutoLoadLatest() => autoLoad.Checked && Visible && project is not null && connected && !busy ? LoadLatest() : Task.CompletedTask;
    private async Task LoadLatest()
    {
        await Operation(async (id, conversation) =>
        {
            var result = await api.Request(Path(id) + "/load-latest", lifetime, HttpMethod.Post, new JsonObject { ["device"] = device.SelectedItem?.ToString(), ["replace"] = true });
            if (id == project)
            {
                if (loadedCheckpoint != result.Text("checkpoint")) { conversation.Messages.Clear(); RenderConversation(); }
                loaded = result.Flag("loaded"); loadedCheckpoint = result.Text("checkpoint");
            }
            await refresh();
        }, "Finding and loading the latest complete checkpoint…");
    }
    public void Bind(string? id, string? selectedJob, bool isConnected)
    {
        connected = isConnected; job = selectedJob;
        if (id is null && !busy) status.Text = "Choose a scratch LLM project in the project list to test a model.";
        if (id != project)
        {
            revision++;
            if (project is not null) { Current.Draft = prompt.Text; Current.System = system.Text; }
            project = id; loaded = false; loadedCheckpoint = ""; lastError = ""; prompt.Text = Current.Draft; system.Text = Current.System; RenderConversation();
            status.Text = id is null ? "Choose a scratch LLM project in the project list to test a model." : "Ready to test. Click Load latest checkpoint; no directory typing is needed.";
            _ = AutoLoadLatest();
        }
        ApplyControls();
        _ = RefreshStatus();
    }
    private async Task RefreshStatus()
    {
        if (project is not { } id || checking || busy || !connected) return;
        checking = true; var version = revision;
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(lifetime); timeout.CancelAfter(TimeSpan.FromSeconds(5));
        try
        {
            var state = await api.Request(Path(id), timeout.Token);
            if (!IsDisposed && project == id && version == revision && !busy)
            {
                loaded = state.Flag("loaded");
                loadedCheckpoint = state.Text("checkpoint");
                if (lastError.Length == 0) status.Text = loaded ? "Loaded · " + state.Text("device") + " · " + state.Text("checkpoint") : "No model loaded. CPU is the default.";
                ApplyControls();
            }
        }
        catch (Exception error) { if (!IsDisposed && project == id && !busy) status.Text = "Chat unavailable: " + error.Message; }
        finally { checking = false; }
    }
    private async Task Operation(Func<string, Conversation, Task> action, string label)
    {
        if (busy || project is null || !connected) return;
        var id = project; var conversation = Current; revision++; busy = true; lastError = ""; status.Text = label; ApplyControls();
        try { await action(id, conversation); if (!IsDisposed && project == id) status.Text = loaded ? "Ready · " + loadedCheckpoint + " · type a prompt below" : "Model unloaded. Load the latest checkpoint to test again."; }
        catch (Exception error) { if (!IsDisposed && project == id) { lastError = error.Message; status.Text = lastError; } }
        finally { busy = false; if (!IsDisposed) ApplyControls(); }
    }
    private void ApplyControls()
    {
        var enabled = project is not null && connected && !busy;
        load.Enabled = enabled && !loaded; unload.Enabled = send.Enabled = enabled && loaded; clear.Enabled = !busy;
        latest.Enabled = enabled; autoLoad.Enabled = !busy && project is not null;
        source.Enabled = checkpoint.Enabled = device.Enabled = system.Enabled = prompt.Enabled = temperature.Enabled = tokens.Enabled = !busy;
    }
    private void RenderConversation()
    {
        transcript.Clear();
        foreach (var message in Current.Messages)
        {
            transcript.SelectionColor = message.Text("role") == "user" ? Color.DarkBlue : Color.DarkGreen;
            transcript.AppendText(message.Text("role") == "user" ? "You\n" : "Your model\n");
            transcript.SelectionColor = SystemColors.WindowText; transcript.AppendText(message.Text("content", "(No text generated)") + "\n\n");
        }
        transcript.SelectionStart = transcript.TextLength; transcript.ScrollToCaret();
    }
    private sealed class Conversation { public List<JsonObject> Messages { get; } = []; public string Draft { get; set; } = ""; public string System { get; set; } = ""; }
}
