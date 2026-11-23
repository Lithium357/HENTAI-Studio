using HENTAIStudio;
using System.Text.Json.Nodes;

internal static class NativeTests
{
    private static int checks;
    private static void Check(bool valid, string label) { if (!valid) throw new Exception(label); checks++; }
    private static async Task Reject(Func<Task> operation, string contains)
    {
        try { await operation(); } catch (Exception error) { Check(error.Message.Contains(contains, StringComparison.OrdinalIgnoreCase), "Expected error: " + contains + "; got: " + error.Message); return; }
        throw new Exception("Expected an error: " + contains);
    }
    [STAThread]
    private static void Main(string[] args)
    {
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
        Application.EnableVisualStyles();
        var rows = new[] { new JsonObject { ["step"] = 1, ["loss"] = 4 }, new JsonObject { ["step"] = 2, ["loss"] = 3 }, new JsonObject { ["step"] = 1, ["loss"] = 2 }, new JsonObject { ["step"] = 2, ["loss"] = 1 } };
        var series = MetricSeries.Create(rows, "loss");
        Check(series.Axis == "Sample", "Reset steps must use recording order");
        Check(series.Points.Select(p => p.X).SequenceEqual(new double[] { 1, 2, 3, 4 }), "Chart cannot double back");
        Check(series.Points[2].Step == 1, "Original step remains inspectable");
        Check(MetricSeries.Create(rows.Take(2), "loss").Axis == "Step", "Monotonic step positions stay unchanged");
        Check(MetricSeries.Create([], "loss").Points.Count == 0, "Empty metrics are valid");
        using (var chart = new MetricChart { Size = new Size(600, 240) })
        using (var image = new Bitmap(600, 240))
        {
            chart.SetSeries(series); chart.DrawToBitmap(image, new Rectangle(0, 0, 600, 240));
            if (args.Length > 1) image.Save(args[1]);
            Check(chart.Series.Points.Count == 4, "Chart preserves all samples");
        }
        using (var form = new StudioForm(new Uri("http://127.0.0.1:1/"), true))
        {
            _ = form.Handle;
            foreach (var width in new[] { 440, 640, 960, 1400 })
            {
                form.Size = new Size(width, 720); form.PerformLayout();
                Check(form.Width <= width, "Native window permits split-screen sizing");
            }
            Check(Descendants(form).OfType<ListView>().Count() == 2, "Jobs and files use native ListView controls");
            Check(Descendants(form).OfType<RichTextBox>().Any(), "Console uses a native text control");
        }
        using (var editor = new ProjectEditor(null))
            Check(Descendants(editor).OfType<NumericUpDown>().Count() >= 8, "Scratch training uses native numeric controls");
        Check(!AppDomain.CurrentDomain.GetAssemblies().Any(a => (a.GetName().Name ?? "").Contains("WebView", StringComparison.OrdinalIgnoreCase)), "No browser assembly may load");
        if (args.Length > 0)
        {
            Task.Run(() => CheckApi(new Uri(args[0]))).GetAwaiter().GetResult();
            CheckWindow(new Uri(args[0]));
        }
        Console.WriteLine($"Native desktop checks passed: {checks}");
    }
    private static IEnumerable<Control> Descendants(Control parent) => parent.Controls.Cast<Control>().SelectMany(child => new[] { child }.Concat(Descendants(child)));
    private static async Task UntilAsync(Func<bool> ready)
    {
        var deadline = DateTime.UtcNow.AddSeconds(15);
        while (!ready()) { await Task.Delay(10); if (DateTime.UtcNow > deadline) throw new Exception("Native UI operation timed out"); }
    }
    private static void CheckWindow(Uri origin)
    {
        using var form = new StudioForm(origin, true);
        Exception? failure = null;
        form.Shown += async (_, _) =>
        {
            try { await CheckWindowControls(form); }
            catch (Exception error) { failure = error; }
            finally { form.Close(); }
        };
        Application.Run(form);
        if (failure is not null) throw new Exception("Native window check failed", failure);
    }
    private static async Task CheckWindowControls(StudioForm form)
    {
        await UntilAsync(() => form.Text.Contains("Cloud"));
        var history = Descendants(form).OfType<ListView>().First();
        Check(history.Items.Count == 13, "Native history renders all paginated jobs");
        foreach (var width in new[] { 440, 640, 960, 1400 })
        {
            form.Size = new Size(width, 800); await Task.Delay(20);
            Check(history.Items[1].Bounds.Top >= history.Items[0].Bounds.Bottom, $"Native history rows do not overlap at {width}px");
        }
        var list = Descendants(form).OfType<ListBox>().Single();
        var hardware = Descendants(form).OfType<NativeHardware>().Single();
        var gpuGrid = Descendants(hardware).OfType<DataGridView>().Single();
        await UntilAsync(() => gpuGrid.Rows.Count == 3);
        Check(gpuGrid.Rows.Cast<DataGridViewRow>().Select(row => row.Cells[1].Value?.ToString()).SequenceEqual(new[] { "NVIDIA", "AMD", "Intel" }), "Live hardware renders all GPU vendors separately");
        Check(gpuGrid.Rows[0].Cells[2].Value?.ToString() == 0.0.ToString("N1"), "Idle GPU utilization is zero");
        Check(gpuGrid.Rows[0].Cells[6].Value?.ToString() == "—", "Missing sensors remain unavailable");
        list.SelectedIndex = 2;
        var tabs = Descendants(form).OfType<TabControl>().Single(c => c.Name == "WorkspaceViews");
        await UntilAsync(() => tabs.TabPages.Cast<TabPage>().Any(p => p.Text == "Test model"));
        var chatPage = tabs.TabPages.Cast<TabPage>().Single(p => p.Text == "Test model");
        tabs.SelectedTab = chatPage;
        var chat = chatPage.Controls.OfType<NativeChat>().Single();
        await UntilAsync(() => chat.Visible);
        Button Find(string name) => Descendants(chat).OfType<Button>().Single(b => b.Text == name);
        await UntilAsync(() => Find("Load latest checkpoint").Enabled);
        Find("Load latest checkpoint").PerformClick();
        await UntilAsync(() => Find("Send prompt").Enabled);
        Check(Descendants(chat).OfType<Label>().Any(l => l.Text.Contains("latest/checkpoint-200")), "Latest checkpoint loads without typing a directory");
        await UntilAsync(() => Find("Unload model").Enabled); Find("Unload model").PerformClick();
        await UntilAsync(() => Find("Load checkpoint").Enabled);
        Descendants(chat).OfType<CheckBox>().Single(c => c.Text.StartsWith("Advanced options")).Checked = true;
        Descendants(chat).OfType<ComboBox>().Single(c => c.Items.Contains("Local directory")).SelectedIndex = 1;
        Descendants(chat).OfType<TextBox>().Single(t => t.PlaceholderText == "Model directory or checkpoint-N").Text = "/demo/model";
        await UntilAsync(() => Find("Load checkpoint").CanSelect && Find("Load checkpoint").Enabled);
        Find("Load checkpoint").Focus();
        Find("Load checkpoint").PerformClick();
        await UntilAsync(() => Find("Send prompt").Enabled);
        Check(Find("Unload model").Enabled, "Native chat enables generation after explicit model load");
        Descendants(chat).OfType<TextBox>().Single(t => t.AccessibleName == "Chat prompt").Text = "Hello native UI";
        Find("Send prompt").PerformClick();
        await UntilAsync(() => Descendants(chat).OfType<RichTextBox>().Single().Text.Contains("Local scratch reply: Hello native UI"));
        Check(true, "Native chat renders the backend response");
        await UntilAsync(() => Find("Unload model").Enabled); Find("Unload model").PerformClick();
        await UntilAsync(() => Find("Load checkpoint").Enabled);
        Check(!Find("Send prompt").Enabled, "Native chat disables generation after unload");
        var automatic = Descendants(chat).OfType<CheckBox>().Single(c => c.Text.StartsWith("Auto-load latest"));
        automatic.Checked = true;
        await UntilAsync(() => Find("Send prompt").Enabled);
        Check(true, "Opt-in automatic checkpoint loading enables the tester");
        automatic.Checked = false;
        var sampling = Descendants(chat).OfType<ComboBox>().Single(c => c.AccessibleName == "Sampling device");
        Check(sampling.SelectedIndex == 0, "CPU sampling is the default");
        sampling.SelectedIndex = 1;
        var sharedGpu = Descendants(chat).OfType<CheckBox>().Single(c => c.Text == "Allow GPU sampling alongside training");
        Check(sharedGpu.Visible, "GPU sampling exposes the training-sharing option");
        sharedGpu.Checked = true;
        Find("Load latest checkpoint").PerformClick();
        await UntilAsync(() => Descendants(chat).OfType<Label>().Any(l => l.Text.Contains("GPU (shared with training)")));
        Check(true, "GPU sampling preference and sharing flag reach the backend");
    }
    private static async Task CheckApi(Uri origin)
    {
        using var api = new StudioApi(origin); var token = CancellationToken.None;
        var health = await api.Request("/api/health", token);
        Check(health.Text("location") == "cloud", "Backend drives the window label");
        Check((await api.Collection("/api/projects?limit=200", token)).Count == 2, "Projects pagination");
        Check((await api.Collection("/api/jobs?limit=200", token)).Count == 11, "Jobs pagination");
        Check((await api.Request("/api/jobs/job-0/metrics", token))["items"] is JsonArray { Count: 64 }, "Metric recordings");
        Check((await api.Request("/api/jobs/job-0/logs?tail=65536", token)).Text("text").Contains("Checkpoint saved"), "Console output");
        var created = await api.Request("/api/projects", token, HttpMethod.Post, new JsonObject { ["id"] = "native-test", ["name"] = "Native test" });
        Check(created.Text("id") == "native-test", "Register project");
        Check((await api.Request("/api/projects/native-test", token, HttpMethod.Patch, new JsonObject { ["name"] = "Edited" })).Text("name") == "Edited", "Edit project");
        await api.Request("/api/projects/native-test", token, HttpMethod.Delete);
        Check((await api.Collection("/api/projects", token)).Count == 2, "Unregister project");
        Check((await api.Request("/api/jobs/job-0/stop", token, HttpMethod.Post)).Text("state") == "stopped", "Stop job");
        Check((await api.Request("/api/jobs", token, HttpMethod.Post, new JsonObject { ["project_id"] = "demo", ["command"] = "train" })).Text("id").StartsWith("new-job-"), "Launch command");
        Check((await api.Request("/api/jobs/job-1/resume", token, HttpMethod.Post, new JsonObject { ["command"] = "train" })).Text("command") == "train", "Resume command");
        Check((await api.Request("/api/projects/llm/chat/load", token, HttpMethod.Post, new JsonObject { ["checkpoint"] = "model", ["device"] = "cpu" })).Flag("loaded"), "Load scratch checkpoint");
        Check((await api.Request("/api/projects/llm/chat/completions", token, HttpMethod.Post, new JsonObject { ["messages"] = new JsonArray(new JsonObject { ["role"] = "user", ["content"] = "Hello" }) })).Text("content").Contains("Hello"), "Chat response");
        Check(!(await api.Request("/api/projects/llm/chat/unload", token, HttpMethod.Post)).Flag("loaded"), "Unload checkpoint");
        await Reject(async () => { await api.Request("/api/not-found", token); }, "No such resource");
        await Reject(async () => { await api.Request("/api/broken", token); }, "invalid JSON");
        await Reject(async () => { await api.Collection("/api/repeated", token); }, "repeated page cursor");
        await Reject(async () => { await api.Request("/api/redirect", token); }, "302");
        await Reject(async () => { await api.Request("/", token); }, "Invalid API path");
        var path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "studio-native-test-" + Guid.NewGuid().ToString("N") + ".json");
        try { await api.Download("job-0", "checkpoint.json", path, token); Check(File.ReadAllText(path).Contains("step"), "Native artifact download"); }
        finally { if (File.Exists(path)) File.Delete(path); }
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        try { await api.Request("/api/health", cancellation.Token); throw new Exception("Cancellation ignored"); } catch (OperationCanceledException) { checks++; }
    }
}
