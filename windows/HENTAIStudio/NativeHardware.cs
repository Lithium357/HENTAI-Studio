using System.Text.Json.Nodes;

namespace HENTAIStudio;

internal sealed class NativeHardware : UserControl
{
    private readonly StudioApi api;
    private readonly CancellationToken lifetime;
    private readonly Label status = new() { Dock = DockStyle.Fill, AutoEllipsis = true, Text = "Connecting to backend hardware monitor…" };
    private readonly Label host = new() { Dock = DockStyle.Fill, AutoEllipsis = true };
    private readonly TextBox notes = new() { Dock = DockStyle.Fill, ReadOnly = true, Multiline = true, ScrollBars = ScrollBars.Vertical };
    private readonly DataGridView devices = new() { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false, AllowUserToDeleteRows = false, RowHeadersVisible = false, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.None, AccessibleName = "Live backend GPUs" };
    private bool refreshing;

    public NativeHardware(StudioApi api, CancellationToken lifetime)
    {
        this.api = api; this.lifetime = lifetime; Dock = DockStyle.Fill;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5, Padding = new Padding(8) };
        layout.RowStyles.Add(new(SizeType.Absolute, 36)); layout.RowStyles.Add(new(SizeType.Absolute, 34));
        layout.RowStyles.Add(new(SizeType.Percent, 100)); layout.RowStyles.Add(new(SizeType.Absolute, 70)); layout.RowStyles.Add(new(SizeType.Absolute, 38));
        layout.Controls.Add(status, 0, 0); layout.Controls.Add(host, 0, 1); layout.Controls.Add(devices, 0, 2); layout.Controls.Add(notes, 0, 3);
        layout.Controls.Add(new Label { Text = "Live usage of the whole backend machine, across all workloads. — = unavailable. GPU rows scroll horizontally.", Dock = DockStyle.Fill, AutoEllipsis = true }, 0, 4);
        foreach (var (name, width) in new[] { ("GPU", 240), ("Vendor", 80), ("Usage %", 85), ("Dedicated used MiB", 145), ("Dedicated total MiB", 145), ("Shared used MiB", 130), ("Temperature °C", 130), ("Power W", 90), ("Source", 180) })
            devices.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = name, Width = width, SortMode = DataGridViewColumnSortMode.NotSortable });
        Controls.Add(layout);
    }

    private static string Value(JsonNode? node, string key) => node.Number(key)?.ToString("N1") ?? "—";
    public async Task RefreshAsync()
    {
        if (refreshing || IsDisposed || lifetime.IsCancellationRequested) return;
        refreshing = true;
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(lifetime); timeout.CancelAfter(TimeSpan.FromSeconds(5));
        try
        {
            var snapshot = await api.Request("/api/hardware", timeout.Token);
            if (IsDisposed || lifetime.IsCancellationRequested) return;
            if (snapshot.Text("scope") != "backend_host") throw new InvalidOperationException("Invalid hardware response.");
            var timestamp = DateTimeOffset.TryParse(snapshot.Text("sampled_at"), out var date) ? date.ToLocalTime().ToString("HH:mm:ss") : "waiting";
            status.Text = $"{snapshot.Text("hostname")} · {snapshot.Text("platform")} · " + (snapshot.Flag("collecting") ? "Collecting first sample…" : $"Sampled {timestamp} · age {Value(snapshot, "age_seconds")}s" + (snapshot.Flag("stale") ? " · STALE" : ""));
            host.Text = $"Backend CPU: {Value(snapshot, "cpu_pct")}% · RAM: {Value(snapshot, "ram_used_mb")} / {Value(snapshot, "ram_total_mb")} MiB";
            devices.Rows.Clear();
            foreach (var gpu in (snapshot["gpus"] as JsonArray ?? []))
            {
                var row = devices.Rows[devices.Rows.Add(gpu.Text("name"), gpu.Text("vendor"), Value(gpu, "utilization_pct"), Value(gpu, "memory_used_mb"), Value(gpu, "memory_total_mb"), Value(gpu, "shared_memory_mb"), Value(gpu, "temperature_c"), Value(gpu, "power_w"), gpu.Text("source"))];
                row.Cells[0].ToolTipText = gpu.Text("id");
            }
            notes.Text = string.Join(Environment.NewLine, (snapshot["issues"] as JsonArray ?? []).Select(issue => issue?.ToString()));
            if (devices.Rows.Count == 0 && !snapshot.Flag("collecting") && notes.Text.Length == 0) notes.Text = "No GPU was detected by the backend.";
        }
        catch (Exception error)
        {
            if (!IsDisposed && !lifetime.IsCancellationRequested)
            {
                status.Text = "Hardware unavailable: " + error.Message;
                host.Text = "Start or update the backend to expose /api/hardware.";
                devices.Rows.Clear(); notes.Clear();
            }
        }
        finally { refreshing = false; }
    }
}
