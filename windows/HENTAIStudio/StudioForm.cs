using System.Diagnostics;
using System.Net.Sockets;
using System.Text.Json.Nodes;

namespace HENTAIStudio;

internal sealed class StudioForm : Form
{
    private readonly StudioApi api;
    private readonly bool connectOnly;
    private readonly CancellationTokenSource lifetime = new();
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 3000 };
    private readonly ListBox projectList = new() { Dock = DockStyle.Fill, IntegralHeight = false, DisplayMember = "Name", HorizontalScrollbar = true };
    private readonly ListView history = MakeList("Command", "State", "Project", "Created");
    private readonly TextBox jobFilter = new() { Dock = DockStyle.Fill, PlaceholderText = "Filter jobs by project, command, state, or ID" };
    private readonly ComboBox commands = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 160, AccessibleName = "Command" };
    private readonly CheckBox resume = new() { AutoSize = true, Text = "Resume selected run" };
    private readonly Button start = Button("Start run"), stop = Button("Stop active run"), edit = Button("Project settings…"), remove = Button("Unregister…");
    private readonly Label projectHeading = new() { Dock = DockStyle.Fill, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleLeft, Font = new Font("Segoe UI", 12, FontStyle.Bold) };
    private readonly Label jobHeading = new() { Dock = DockStyle.Fill, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleLeft };
    private readonly Label notice = new() { Dock = DockStyle.Top, AutoSize = true, ForeColor = Color.Firebrick, Padding = new Padding(8), MaximumSize = new Size(1500, 0) };
    private readonly ToolStripStatusLabel connection = new() { Text = "Connecting…", Spring = true, TextAlign = ContentAlignment.MiddleLeft };
    private readonly TabControl tabs = new() { Dock = DockStyle.Fill, Name = "RunDetails" };
    private readonly TabControl workspaceTabs = new() { Dock = DockStyle.Fill, Name = "WorkspaceViews", AccessibleName = "Workspace views" };
    private readonly ComboBox metric = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 220, AccessibleName = "Metric" };
    private readonly Label metricValue = new() { AutoSize = true, Font = new Font("Segoe UI", 14, FontStyle.Bold), Padding = new Padding(8) };
    private readonly MetricChart chart = new();
    private readonly TrackBar scrubber = new() { Dock = DockStyle.Fill, TickStyle = TickStyle.None, Minimum = 0, AccessibleName = "Inspect metric point" };
    private readonly Label pointLabel = new() { Dock = DockStyle.Fill, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleLeft };
    private readonly DataGridView signals = new() { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false, AllowUserToDeleteRows = false, RowHeadersVisible = false, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill };
    private readonly RichTextBox console = new() { Dock = DockStyle.Fill, ReadOnly = true, WordWrap = false, Font = new Font("Consolas", 10), DetectUrls = false, AccessibleName = "Job console" };
    private readonly TextBox logFilter = new() { Width = 210, PlaceholderText = "Filter console" };
    private readonly CheckBox follow = new() { Text = "Follow output", Checked = true, AutoSize = true };
    private readonly ListView fileList = MakeList("Output file", "Size");
    private readonly TextBox fileFilter = new() { Dock = DockStyle.Fill, PlaceholderText = "Filter files" };
    private readonly Button download = Button("Download selected file…");
    private readonly SplitContainer projectsSplit = new() { Dock = DockStyle.Fill, FixedPanel = FixedPanel.Panel1 };
    private readonly SplitContainer jobsSplit = new() { Dock = DockStyle.Fill, FixedPanel = FixedPanel.Panel1 };
    private readonly Dictionary<string, string> commandChoices = [];
    private readonly ImageList rowHeight = new() { ImageSize = new Size(1, 34) };
    private readonly NativeChat chat;
    private readonly NativeHardware hardware;
    private readonly TabPage chatTab;
    private List<JsonObject> projects = [], jobs = [], metricRows = [], files = [];
    private string? projectId, jobId;
    private string rawLog = "";
    private bool refreshing, updating, acting, connected, closing;
    private int revision;
    private bool settingChart;
    private readonly Dictionary<string, double> metricSelections = [];
    private Process? launchedBackend;

    public StudioForm(Uri origin, bool connectOnly)
    {
        api = new(origin); this.connectOnly = connectOnly;
        Text = $"HENTAI Studio — port {origin.Port} — Native";
        AutoScaleDimensions = new SizeF(96, 96); AutoScaleMode = AutoScaleMode.Dpi;
        Font = new Font("Segoe UI", 9.5f); MinimumSize = new Size(440, 380); Size = new Size(1120, 800); StartPosition = FormStartPosition.CenterScreen;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        chat = new NativeChat(api, lifetime.Token, () => RefreshAsync()); chatTab = new TabPage("Test model"); chatTab.Controls.Add(chat);
        hardware = new NativeHardware(api, lifetime.Token);
        var menu = new MenuStrip();
        menu.Items.Add("New window…", null, (_, _) => SafeNewWindow());
        menu.Items.Add("Refresh", null, async (_, _) => await RefreshAsync());
        menu.Items.Add("About", null, (_, _) => MessageBox.Show(this, "HENTAI Studio Native Desktop\nWindows Forms controls and a locally rendered chart.\nConnects to the Studio API; no browser engine is used.", "HENTAI Studio"));
        MainMenuStrip = menu;
        var status = new StatusStrip(); status.Items.Add(connection);
        var content = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3, Padding = new Padding(8) };
        content.RowStyles.Add(new(SizeType.Absolute, 42)); content.RowStyles.Add(new(SizeType.AutoSize)); content.RowStyles.Add(new(SizeType.Percent, 100));
        var heading = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2 };
        heading.ColumnStyles.Add(new(SizeType.Percent, 100)); heading.ColumnStyles.Add(new(SizeType.AutoSize));
        var manage = Flow(edit, remove); heading.Controls.Add(projectHeading); heading.Controls.Add(manage);
        content.Controls.Add(heading, 0, 0);
        var controls = Flow(new Label { AutoSize = true, Text = "Command", Padding = new Padding(0, 7, 4, 0) }, commands, resume, start, stop);
        var runs = new TabPage("Runs");
        var runLayout = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, ColumnCount = 1, Padding = new Padding(6) };
        runLayout.RowStyles.Add(new(SizeType.AutoSize)); runLayout.RowStyles.Add(new(SizeType.Percent, 100));
        var launch = new GroupBox { Text = "Start or resume a run", Dock = DockStyle.Fill, AutoSize = true, Padding = new Padding(6, 18, 6, 6) };
        launch.Controls.Add(controls); runLayout.Controls.Add(launch, 0, 0); runLayout.Controls.Add(jobsSplit, 0, 1); runs.Controls.Add(runLayout);
        workspaceTabs.TabPages.Add(runs); workspaceTabs.TabPages.Add(chatTab);
        var hardwarePage = new TabPage("Hardware"); hardwarePage.Controls.Add(hardware); workspaceTabs.TabPages.Add(hardwarePage);
        content.Controls.Add(new Label { Text = "Choose a project, then use Runs to train, Test model to chat, or Hardware to inspect the backend.", AutoSize = true, Dock = DockStyle.Fill, Padding = new Padding(0, 4, 0, 8), ForeColor = SystemColors.GrayText }, 0, 1);
        content.Controls.Add(workspaceTabs, 0, 2);
        var projectPanel = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 3, ColumnCount = 1, Padding = new Padding(8) };
        projectPanel.RowStyles.Add(new(SizeType.Absolute, 30)); projectPanel.RowStyles.Add(new(SizeType.Percent, 100)); projectPanel.RowStyles.Add(new(SizeType.Absolute, 38));
        projectPanel.Controls.Add(new Label { Text = "Projects", Font = new Font(Font, FontStyle.Bold), Dock = DockStyle.Fill });
        projectPanel.Controls.Add(projectList, 0, 1);
        var add = Button("Register project…"); add.Dock = DockStyle.Fill; projectPanel.Controls.Add(add, 0, 2);
        projectsSplit.Panel1.Controls.Add(projectPanel); projectsSplit.Panel2.Controls.Add(content);
        var historyPanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
        historyPanel.RowStyles.Add(new(SizeType.Absolute, 26)); historyPanel.RowStyles.Add(new(SizeType.Absolute, 36)); historyPanel.RowStyles.Add(new(SizeType.Percent, 100));
        historyPanel.Controls.Add(new Label { Text = "Recent runs · select a row to inspect", Dock = DockStyle.Fill, Font = new Font(Font, FontStyle.Bold) }); historyPanel.Controls.Add(jobFilter, 0, 1); historyPanel.Controls.Add(history, 0, 2);
        history.SmallImageList = rowHeight;
        jobsSplit.Panel1.Controls.Add(historyPanel);
        var details = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2, Padding = new Padding(6) };
        details.RowStyles.Add(new(SizeType.Absolute, 54)); details.RowStyles.Add(new(SizeType.Percent, 100)); details.Controls.Add(jobHeading); details.Controls.Add(tabs, 0, 1);
        jobsSplit.Panel2.Controls.Add(details);
        BuildTabs();
        Controls.Add(projectsSplit); Controls.Add(notice); Controls.Add(status); Controls.Add(menu);
        menu.BringToFront(); notice.BringToFront(); status.BringToFront();
        add.Click += async (_, _) => await EditProject(null);
        edit.Click += async (_, _) => { if (Project is { } project) await EditProject(project); };
        remove.Click += async (_, _) =>
        {
            var id = projectId;
            if (id is not null && MessageBox.Show(this, "Unregister this project? Source files and job history will be retained.", "Unregister project", MessageBoxButtons.YesNo) == DialogResult.Yes)
                await Mutate(async () => { await api.Request(StudioApi.ProjectPath(id), lifetime.Token, HttpMethod.Delete); SelectProject(null); });
        };
        projectList.SelectedIndexChanged += (_, _) => { if (!updating && projectList.SelectedItem is Choice item) SelectProject(item.Id.Length == 0 ? null : item.Id); };
        history.SelectedIndexChanged += async (_, _) =>
        {
            if (updating || history.SelectedItems.Count == 0) return;
            var selected = history.SelectedItems[0].Tag?.ToString();
            if (selected == jobId) return;
            jobId = selected; revision++; resume.Checked = false; ClearOutputs(); ApplyControls(); await RefreshAsync();
        };
        commands.SelectedIndexChanged += (_, _) => { if (!updating && projectId is not null && commands.SelectedItem is string cmd) commandChoices[projectId] = cmd; };
        jobFilter.TextChanged += (_, _) => RenderJobs();
        metric.SelectedIndexChanged += (_, _) => RenderChart();
        chart.PointSelected += (_, _) => { RememberPoint(); ShowPoint(); };
        scrubber.ValueChanged += (_, _) => { chart.SelectedIndex = scrubber.Value; chart.Invalidate(); if (!settingChart) RememberPoint(); ShowPoint(); };
        logFilter.TextChanged += (_, _) => RenderConsole();
        fileFilter.TextChanged += (_, _) => RenderFiles();
        fileList.SelectedIndexChanged += (_, _) => download.Enabled = fileList.SelectedItems.Count > 0;
        download.Click += async (_, _) => await DownloadFile();
        fileList.DoubleClick += async (_, _) => await DownloadFile();
        start.Click += async (_, _) => await StartJob();
        stop.Click += async (_, _) => { var target = StopTarget; if (target is not null) await Mutate(async () => { await api.Request(StudioApi.JobPath(target.Text("id")) + "/stop", lifetime.Token, HttpMethod.Post); }); };
        timer.Tick += async (_, _) => await RefreshAsync();
        Shown += async (_, _) => { FitLayout(); await InitializeAsync(); if (!closing) timer.Start(); };
        Resize += (_, _) => { if (IsHandleCreated) FitLayout(); };
        FormClosing += (_, _) => { closing = true; timer.Stop(); lifetime.Cancel(); };
        FormClosed += (_, _) => { timer.Dispose(); api.Dispose(); lifetime.Dispose(); rowHeight.Dispose(); launchedBackend?.Dispose(); };
        ApplyControls();
    }

    private JsonObject? Project => projects.Find(p => p.Text("id") == projectId);
    private JsonObject? Job => jobs.Find(p => p.Text("id") == jobId);
    private JsonObject? StopTarget => (projectId is null ? Job : jobs.Find(j => j.Busy()) ?? Job);
    private static Button Button(string text) => new() { Text = text, AutoSize = true, MinimumSize = new Size(75, 30), Margin = new Padding(3) };
    private static FlowLayoutPanel Flow(params Control[] controls)
    {
        var panel = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true, Padding = new Padding(0, 3, 0, 3) };
        panel.Controls.AddRange(controls); return panel;
    }
    private static ListView MakeList(params string[] names)
    {
        var list = new ListView { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, HideSelection = false, MultiSelect = false, ShowItemToolTips = true };
        foreach (var name in names) list.Columns.Add(name, name == "Project" || name == "Output file" ? 230 : 110);
        return list;
    }
    private void BuildTabs()
    {
        var overview = new TabPage("Metrics"); var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5 };
        layout.RowStyles.Add(new(SizeType.AutoSize)); layout.RowStyles.Add(new(SizeType.Percent, 65)); layout.RowStyles.Add(new(SizeType.Absolute, 36)); layout.RowStyles.Add(new(SizeType.Absolute, 28)); layout.RowStyles.Add(new(SizeType.Percent, 35));
        layout.Controls.Add(Flow(metric, metricValue), 0, 0); layout.Controls.Add(chart, 0, 1); layout.Controls.Add(scrubber, 0, 2); layout.Controls.Add(pointLabel, 0, 3);
        signals.Columns.Add("Signal", "Measurement"); signals.Columns.Add("Value", "Latest value"); layout.Controls.Add(signals, 0, 4); overview.Controls.Add(layout); tabs.TabPages.Add(overview);
        var logs = new TabPage("Console"); var logPanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        logPanel.RowStyles.Add(new(SizeType.AutoSize)); logPanel.RowStyles.Add(new(SizeType.Percent, 100));
        var saveLogs = Button("Save console…"); saveLogs.Click += (_, _) => SaveText(console.Text, "console.txt");
        logPanel.Controls.Add(Flow(logFilter, follow, saveLogs), 0, 0); logPanel.Controls.Add(console, 0, 1); logs.Controls.Add(logPanel); tabs.TabPages.Add(logs);
        var artifacts = new TabPage("Output files"); var filePanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
        filePanel.RowStyles.Add(new(SizeType.Absolute, 36)); filePanel.RowStyles.Add(new(SizeType.Percent, 100)); filePanel.RowStyles.Add(new(SizeType.AutoSize));
        filePanel.Controls.Add(fileFilter, 0, 0); filePanel.Controls.Add(fileList, 0, 1); filePanel.Controls.Add(Flow(download), 0, 2); artifacts.Controls.Add(filePanel); tabs.TabPages.Add(artifacts);

    }
    private void FitLayout()
    {
        if (ClientSize.Width < 1 || ClientSize.Height < 1) return;
        notice.MaximumSize = new Size(Math.Max(1, ClientSize.Width), 0);
        var compact = ClientSize.Width < 760;
        SetSplit(projectsSplit, compact ? Orientation.Horizontal : Orientation.Vertical, compact ? 125 : 195);
        var narrow = ClientSize.Width < 1150;
        SetSplit(jobsSplit, narrow ? Orientation.Horizontal : Orientation.Vertical, narrow ? Math.Min(170, jobsSplit.Height / 3) : 340);
    }
    private static void SetSplit(SplitContainer split, Orientation orientation, int preferred)
    {
        // Docked tabs may still be zero-sized while handles/layout are being created.
        if (split.Width <= split.SplitterWidth + 2 || split.Height <= split.SplitterWidth + 2) return;
        split.Panel1MinSize = split.Panel2MinSize = 0;
        if (split.Orientation != orientation)
        {
            split.SplitterDistance = 0;
            split.Orientation = orientation;
        }
        var extent = orientation == Orientation.Horizontal ? split.ClientSize.Height : split.ClientSize.Width;
        split.SplitterDistance = Math.Clamp(preferred, 0, Math.Max(0, extent - split.SplitterWidth));
    }
    private void SelectProject(string? id)
    {
        if (projectId == id) return;
        projectId = id; jobId = null; jobs = []; revision++; resume.Checked = false; ClearOutputs(); RenderJobs(); ApplyControls();
        _ = RefreshAsync();
    }
    private async Task InitializeAsync()
    {
        await RefreshAsync();
        if (connected || connectOnly || closing) return;
        try
        {
            using var port = new TcpClient();
            try { await port.ConnectAsync(api.Origin.Host.Trim('[', ']'), api.Origin.Port, lifetime.Token).AsTask().WaitAsync(TimeSpan.FromSeconds(2)); notice.Text = "A service occupies this port but is not responding as Studio. Use Refresh after starting the correct backend."; return; }
            catch (Exception error) when (error is SocketException or TimeoutException) { }
            var bundled = Path.Combine(AppContext.BaseDirectory, "backend", "Scripts", "hentai-studio.exe");
            var executable = Environment.GetEnvironmentVariable("STUDIO_EXECUTABLE") ?? (File.Exists(bundled) ? bundled : "hentai-studio");
            var workspace = Environment.GetEnvironmentVariable("STUDIO_WORKSPACE") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".hentai-studio");
            var log = Path.Combine(workspace, "logs", "server.log"); Directory.CreateDirectory(Path.GetDirectoryName(log)!);
            var info = new ProcessStartInfo(executable) { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden };
            foreach (var argument in new[] { "serve", "--workspace", workspace, "--host", api.Origin.Host, "--port", api.Origin.Port.ToString(), "--log-file", log }) info.ArgumentList.Add(argument);
            launchedBackend = Process.Start(info);
            for (var i = 0; i < 30 && !connected && !closing; i++) { await Task.Delay(500, lifetime.Token); await RefreshAsync(); }
        }
        catch (OperationCanceledException) { }
        catch (Exception error) { if (!closing) notice.Text = "Could not start Studio: " + error.Message; }
    }
    public async Task RefreshAsync()
    {
        _ = hardware.RefreshAsync();
        if (refreshing || closing) return;
        refreshing = true; var version = revision;
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token); timeout.CancelAfter(TimeSpan.FromSeconds(12));
        try
        {
            var health = await api.Request("/api/health", timeout.Token);
            if (health.Text("application") != "hentai-studio") throw new InvalidOperationException("The selected port is not a Studio backend.");
            var projectTask = api.Collection("/api/projects?limit=200", timeout.Token);
            var jobTask = api.Collection("/api/jobs?limit=200" + (projectId is null ? "" : "&project_id=" + Uri.EscapeDataString(projectId)), timeout.Token);
            await Task.WhenAll(projectTask, jobTask);
            if (version != revision || closing) return;
            projects = await projectTask; jobs = await jobTask; connected = true;
            Text = $"HENTAI Studio — port {api.Origin.Port} - {(health.Text("location") == "cloud" ? "Cloud" : "Local")} — Native";
            connection.Text = $"Connected · v{health.Text("version")} · {health.Text("workspace")}";
            if (projectId is not null && Project is null) { SelectProject(null); return; }
            updating = true;
            try
            {
                var choices = new[] { new Choice("", "All jobs") }.Concat(projects.Select(p => new Choice(p.Text("id"), p.Text("name")))).ToArray();
                if (!projectList.Items.Cast<Choice>().SequenceEqual(choices)) { projectList.Items.Clear(); projectList.Items.AddRange(choices); }
                projectList.SelectedIndex = Array.FindIndex(choices, p => p.Id == (projectId ?? ""));
                var names = (Project?["commands"] as JsonObject)?.Select(p => p.Key).ToArray() ?? [];
                if (!commands.Items.Cast<string>().SequenceEqual(names)) { commands.Items.Clear(); commands.Items.AddRange(names); }
                if (projectId is not null && commandChoices.TryGetValue(projectId, out var saved) && names.Contains(saved)) commands.SelectedItem = saved;
                else if (commands.SelectedIndex < 0 && names.Length > 0) commands.SelectedIndex = 0;
                if (jobId is null || Job is null) jobId = jobs.FirstOrDefault()?.Text("id");
            }
            finally { updating = false; }
            projectHeading.Text = Project is { } p ? $"{p.Text("name")}\n{p.Text("root")}" : "All jobs · " + projects.Count + " registered projects";
            jobHeading.Text = Job is { } j ? $"{j.Text("command")} · {j.Text("state")} · {j.Text("id")}\nCreated {j.Date("created_at")}" : "Select a run from the list to inspect its metrics, console, and output files.";
            RenderJobs(); ApplyControls();
            var llm = Project?["llm"] is JsonObject;

            chat.Bind(llm ? projectId : null, jobId, connected);
            if (health["issues"] is JsonArray issues && issues.Count > 0) notice.Text = string.Join(Environment.NewLine, issues.Select(i => i.Text("message")));
            if (Job is not { } current) return;
            var selected = current.Text("id"); var path = StudioApi.JobPath(selected);
            await Task.WhenAll(
                ReadPanel(path + "/metrics", node => SetMetrics((node["items"] as JsonArray)?.OfType<JsonObject>().ToList() ?? []), error => { chart.SetSeries(new("", "Step", [])); metricValue.Text = error; }, timeout.Token, version, selected),
                ReadPanel(path + "/logs?tail=65536", node => { rawLog = node.Text("text"); RenderConsole(); }, error => console.Text = error, timeout.Token, version, selected),
                ReadPanel(path + "/artifacts", node => { files = (node["items"] as JsonArray)?.OfType<JsonObject>().ToList() ?? []; RenderFiles(); }, error => { files = []; RenderFiles(); notice.Text = error; }, timeout.Token, version, selected));
        }
        catch (OperationCanceledException) { if (!closing && version == revision) { connected = false; connection.Text = "Studio did not respond. Start your backend or SSH tunnel, then use Refresh."; } }
        catch (Exception error) { if (!closing && version == revision) { connected = false; connection.Text = "Disconnected: " + error.Message; } }
        finally
        {
            refreshing = false;
            if (!closing) { ApplyControls(); if (version != revision) _ = RefreshAsync(); }
        }
    }
    private async Task ReadPanel(string path, Action<JsonNode> render, Action<string> error, CancellationToken token, int version, string selected)
    {
        try { var result = await api.Request(path, token); if (!closing && revision == version && jobId == selected) render(result); }
        catch (Exception exception) { if (!closing && revision == version && jobId == selected) error("Unavailable: " + exception.Message); }
    }
    private void RenderJobs()
    {
        var query = jobFilter.Text;
        var items = jobs.Where(j => ($"{j.Text("command")} {j.Text("state")} {j.Text("project_name")} {j.Text("id")}").Contains(query, StringComparison.OrdinalIgnoreCase)).Select(j =>
        {
            var item = new ListViewItem([j.Text("command"), j.Text("state"), j.Text("project_name"), j.Date("created_at")]) { Tag = j.Text("id"), ToolTipText = j.Text("project_name") + "\n" + j.Text("id") };
            if (j.Busy()) item.ForeColor = Color.DarkGreen;
            return item;
        }).ToArray();
        updating = true; history.BeginUpdate();
        try
        {
            var top = history.Items.Count > 0 ? history.TopItem?.Tag?.ToString() : null;
            history.Items.Clear(); history.Items.AddRange(items);
            foreach (var item in items) if (item.Tag?.ToString() == jobId) item.Selected = true;
            var previous = items.FirstOrDefault(i => i.Tag?.ToString() == top); if (previous is not null) history.TopItem = previous;
        }
        finally { history.EndUpdate(); updating = false; }
    }
    private void ApplyControls()
    {
        if (closing) return;
        var healthy = connected && !acting;
        start.Enabled = healthy && Project is not null && commands.SelectedItem is not null && !jobs.Any(j => j.Busy());
        resume.Enabled = start.Enabled && Job is not null && !Job.Busy(); if (!resume.Enabled) resume.Checked = false;
        stop.Enabled = healthy && StopTarget is { } target && target.Busy() && target.Text("state") != "stopping";
        edit.Enabled = remove.Enabled = healthy && Project is not null && !jobs.Any(j => j.Busy());
        download.Enabled = connected && fileList.SelectedItems.Count > 0;
    }
    private async Task StartJob()
    {
        var id = projectId; var command = commands.SelectedItem?.ToString(); var source = resume.Checked ? jobId : null;
        if (id is null || command is null) return;
        await Mutate(async () =>
        {
            var result = await api.Request(source is null ? "/api/jobs" : StudioApi.JobPath(source) + "/resume", lifetime.Token, HttpMethod.Post,
                source is null ? new JsonObject { ["project_id"] = id, ["command"] = command } : new JsonObject { ["command"] = command });
            if (projectId == id) { jobId = result.Text("id"); jobs.Insert(0, result.AsObject()); resume.Checked = false; }
        });
    }
    private async Task Mutate(Func<Task> action)
    {
        if (acting || !connected) return; acting = true; notice.Text = ""; ApplyControls();
        try { await action(); revision++; }
        catch (Exception error) { if (!closing) notice.Text = error.Message; }
        finally { acting = false; if (!closing) { ApplyControls(); await RefreshAsync(); } }
    }
    private async Task EditProject(JsonObject? project)
    {
        using var editor = new ProjectEditor(project);
        if (editor.ShowDialog(this) != DialogResult.OK) return;
        await Mutate(async () =>
        {
            var body = editor.Definition; var id = body.Text("id");
            if (project is not null) body.Remove("id");
            var saved = await api.Request(project is null ? "/api/projects" : StudioApi.ProjectPath(id), lifetime.Token, project is null ? HttpMethod.Post : HttpMethod.Patch, body);
            if (projectId != saved.Text("id")) SelectProject(saved.Text("id"));
        });
    }
    private void ClearOutputs() { metricRows = []; files = []; rawLog = ""; console.Clear(); chart.SetSeries(new("", "Step", [])); metricValue.Text = ""; pointLabel.Text = ""; signals.Rows.Clear(); fileList.Items.Clear(); }
    private void SetMetrics(List<JsonObject> rows)
    {
        metricRows = rows;
        var keys = rows.SelectMany(row => row.Select(p => p.Key)).Distinct().Where(k => k != "step" && rows.Any(r => r.Number(k).HasValue)).ToArray();
        var old = metric.SelectedItem?.ToString();
        if (!metric.Items.Cast<string>().SequenceEqual(keys)) { metric.Items.Clear(); metric.Items.AddRange(keys); }
        var next = old is not null && keys.Contains(old) ? old : new[] { "loss", "train_loss", "validation_loss", "accuracy" }.FirstOrDefault(keys.Contains) ?? keys.FirstOrDefault();
        if (next is not null) metric.SelectedItem = next;
        RenderChart();
        signals.Rows.Clear();
        foreach (var (key, label) in new[] { ("step", "Step"), ("total_steps", "Total steps"), ("steps_per_second", "Steps / second"), ("seconds_per_step", "Seconds / step"), ("progress_percent", "Progress %"), ("gpu_usage_pct", "Recorded GPU usage %"), ("gpu_vram_mb", "Recorded VRAM MB"), ("process_ram_mb", "Recorded trainer RAM MB") })
        { var value = rows.LastOrDefault(row => row.Number(key).HasValue)?.Number(key); signals.Rows.Add(label, value?.ToString("G6") ?? "—"); }
    }
    private void RenderChart()
    {
        var series = MetricSeries.Create(metricRows, metric.SelectedItem?.ToString() ?? ""); chart.SetSeries(series);
        var index = series.Points.Count - 1;
        if (index >= 0 && metricSelections.TryGetValue($"{jobId}:{series.Name}", out var x))
            index = Enumerable.Range(0, series.Points.Count).MinBy(i => Math.Abs(series.Points[i].X - x));
        settingChart = true;
        try { scrubber.Maximum = Math.Max(0, series.Points.Count - 1); scrubber.Enabled = series.Points.Count > 0; scrubber.Value = Math.Max(0, index); chart.SelectedIndex = index; }
        finally { settingChart = false; }
        metricValue.Text = series.Points.Count > 0 ? $"{series.Points[^1].Y:G6} · {series.Name}" : "No metrics yet"; ShowPoint();
    }
    private void RememberPoint()
    {
        if (chart.SelectedIndex >= 0 && chart.SelectedIndex < chart.Series.Points.Count)
            metricSelections[$"{jobId}:{chart.Series.Name}"] = chart.Series.Points[chart.SelectedIndex].X;
    }
    private void ShowPoint()
    {
        var series = chart.Series; if (chart.SelectedIndex < 0 || chart.SelectedIndex >= series.Points.Count) { pointLabel.Text = ""; return; }
        var p = series.Points[chart.SelectedIndex];
        pointLabel.Text = $"{series.Axis} {p.X:G6}" + (series.Axis == "Sample" && p.Step.HasValue ? $" (step {p.Step:G6})" : "") + $" · {series.Name}: {p.Y:G6} · {series.Points.Count} points";
    }
    private void RenderConsole()
    {
        var clean = System.Text.RegularExpressions.Regex.Replace(rawLog, "\u001b\\[[0-?]*[ -/]*[@-~]", "").Replace("\r\n", "\n");
        var text = string.Join(Environment.NewLine, clean.Split('\n').Select(line => line.Split('\r').LastOrDefault(part => part.Length > 0) ?? "").Where(line => logFilter.Text.Length == 0 || line.Contains(logFilter.Text, StringComparison.OrdinalIgnoreCase)));
        if (console.Text == text) return;
        var selected = console.SelectionStart; console.Text = text;
        if (follow.Checked) { console.SelectionStart = console.TextLength; console.ScrollToCaret(); }
        else console.SelectionStart = Math.Min(selected, console.TextLength);
    }
    private void RenderFiles()
    {
        var selected = fileList.SelectedItems.Count > 0 ? fileList.SelectedItems[0].Tag?.ToString() : null;
        fileList.BeginUpdate();
        try
        {
            fileList.Items.Clear();
            foreach (var file in files.Where(f => f.Text("path").Contains(fileFilter.Text, StringComparison.OrdinalIgnoreCase)))
            {
                var item = new ListViewItem([file.Text("path"), $"{file.Number("size"):N0} bytes"]) { Tag = file.Text("path") };
                fileList.Items.Add(item); item.Selected = item.Tag?.ToString() == selected;
            }
        }
        finally { fileList.EndUpdate(); }
        download.Enabled = connected && fileList.SelectedItems.Count > 0;
    }

    private async Task DownloadFile()
    {
        if (jobId is not { } job || fileList.SelectedItems.Count == 0) return;
        var path = fileList.SelectedItems[0].Tag!.ToString()!;
        using var dialog = new SaveFileDialog { FileName = path.Split('/').Last(), OverwritePrompt = true };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try { await api.Download(job, path, dialog.FileName, lifetime.Token); notice.Text = "Saved " + dialog.FileName; }
        catch (Exception error) { if (!closing) notice.Text = "Download failed: " + error.Message; }
    }
    private void SaveText(string text, string name) { using var dialog = new SaveFileDialog { FileName = name }; if (dialog.ShowDialog(this) == DialogResult.OK) { try { File.WriteAllText(dialog.FileName, text); } catch (Exception error) { notice.Text = error.Message; } } }
    private void SafeNewWindow() { try { Program.NewWindow(api.Origin.Port); } catch (Exception error) { notice.Text = error.Message; } }
    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (keyData == (Keys.Control | Keys.N)) { SafeNewWindow(); return true; }
        if (keyData == Keys.F5) { _ = RefreshAsync(); return true; }
        return base.ProcessCmdKey(ref msg, keyData);
    }
    private sealed record Choice(string Id, string Name) { public override string ToString() => Name; }
}
