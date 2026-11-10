using System.Diagnostics;
using System.Drawing;
using System.Net.Sockets;
using System.Net.Http;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace HENTAIStudio;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var address = Environment.GetEnvironmentVariable("STUDIO_URL") ?? "http://127.0.0.1:7860/";
        var connectOnly = true;
        if (args is ["--connect", var endpoint])
        {
            address = endpoint;
        }
        else if (args.Length == 0 || args is ["--pick-port", _])
        {
            var defaultPort = Uri.TryCreate(address, UriKind.Absolute, out var configured)
                && configured.Port > 0 ? configured.Port : 7860;
            if (args.Length == 2 && (!int.TryParse(args[1], out defaultPort) || defaultPort is < 1 or > 65535))
            {
                MessageBox.Show("Choose a port from 1 to 65535.", "HENTAI Studio");
                return;
            }

            using var picker = new PortPicker(defaultPort);
            if (picker.ShowDialog() != DialogResult.OK) return;
            address = $"http://127.0.0.1:{picker.Port}/";
            connectOnly = !picker.StartLocalBackend;
        }
        else
        {
            MessageBox.Show("Usage: HENTAI Studio.exe [--pick-port PORT | --connect http://127.0.0.1:PORT/]",
                "HENTAI Studio", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        if (!Uri.TryCreate(address, UriKind.Absolute, out var dashboard) || !dashboard.IsLoopback
            || dashboard.Scheme != "http" || dashboard.AbsolutePath != "/" || dashboard.Query.Length != 0
            || dashboard.UserInfo.Length != 0 || dashboard.Fragment.Length != 0)
        {
            MessageBox.Show("Use an HTTP loopback address such as http://127.0.0.1:7860/.",
                "HENTAI Studio", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        Application.Run(new StudioForm(dashboard, connectOnly));
    }
}

internal sealed class StudioForm : Form
{
    private readonly Uri dashboard;
    private readonly bool connectOnly;
    private Process? backend;
    private string backendLog = "";
    private readonly WebView2 browser = new() { Dock = DockStyle.Fill };
    private readonly Panel loadingPanel = new() { Dock = DockStyle.Fill, BackColor = Color.FromArgb(9, 11, 14) };
    private readonly Label statusLabel = new()
    {
        AutoSize = false,
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleCenter,
        ForeColor = Color.FromArgb(132, 144, 158),
        Font = new Font("Segoe UI", 12F),
        Text = "Starting HENTAI Studio…"
    };

    public StudioForm(Uri dashboard, bool connectOnly)
    {
        this.dashboard = dashboard;
        this.connectOnly = connectOnly;
        Text = $"HENTAI Studio — port {dashboard.Port}";
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        MinimumSize = new Size(360, 340);
        Size = new Size(1100, 760);
        Load += (_, _) =>
        {
            var work = Screen.FromControl(this).WorkingArea;
            Size = new Size(Math.Min(Width, work.Width), Math.Min(Height, work.Height));
        };
        BackColor = Color.FromArgb(9, 11, 14);
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

        loadingPanel.Controls.Add(statusLabel);
        Controls.Add(browser);
        Controls.Add(loadingPanel);
        var menu = new MenuStrip();
        menu.Items.Add("New window…", null, (_, _) => OpenNewWindow());
        var zoom = new ToolStripMenuItem("Zoom");
        foreach (var percent in new[] { 70, 80, 90, 100, 110, 125 })
        {
            var item = new ToolStripMenuItem($"{percent}%") { Checked = percent == 100 };
            item.Click += (_, _) =>
            {
                if (browser.CoreWebView2 is not null)
                    browser.ZoomFactor = percent / 100.0;
            };
            zoom.DropDownItems.Add(item);
        }
        browser.ZoomFactorChanged += (_, _) =>
        {
            zoom.Text = $"Zoom ({browser.ZoomFactor:P0})";
            foreach (ToolStripMenuItem item in zoom.DropDownItems)
                item.Checked = item.Text == $"{browser.ZoomFactor * 100:0}%";
        };
        menu.Items.Add(zoom);
        MainMenuStrip = menu;
        Controls.Add(menu);
        menu.BringToFront();
        KeyPreview = true;
        KeyDown += (_, args) =>
        {
            if (args.Control && args.KeyCode == Keys.N)
            {
                args.SuppressKeyPress = true;
                OpenNewWindow();
            }
        };
        Shown += async (_, _) => await InitializeAsync();
    }

    private void OpenNewWindow()
    {
        try
        {
            var start = new ProcessStartInfo(Application.ExecutablePath);
            start.ArgumentList.Add("--pick-port");
            start.ArgumentList.Add(dashboard.Port.ToString());
            Process.Start(start)?.Dispose();
        }
        catch (Exception error)
        {
            MessageBox.Show(this, error.Message, "Could not open a new Studio window");
        }
    }

    private async Task InitializeAsync()
    {
        try
        {
            if (!dashboard.IsLoopback || dashboard.Scheme != "http" || dashboard.AbsolutePath != "/" || dashboard.Query.Length != 0 || dashboard.UserInfo.Length != 0)
                throw new InvalidOperationException("STUDIO_URL must be an http:// loopback address.");
            if (!await DashboardReadyAsync())
            {
                if (connectOnly)
                {
                    ShowError($"Studio is not responding at {dashboard.Authority}. Start the backend or SSH tunnel, then reopen this window.");
                    return;
                }
                using var portCheck = new TcpClient();
                try
                {
                    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(1));
                    await portCheck.ConnectAsync(dashboard.Host.Trim('[', ']'), dashboard.Port, timeout.Token);
                    ShowError($"Another service is using {dashboard.Authority}. Close it or set STUDIO_URL to a free local port.");
                    return;
                }
                catch (SocketException) { }
                catch (OperationCanceledException) { }
                statusLabel.Text = "Starting the local training workspace…";
                StartDashboard();
                if (!await WaitForDashboardAsync(TimeSpan.FromSeconds(45)))
                {
                    ShowStartupFailure();
                    return;
                }
            }

            statusLabel.Text = "Loading control room…";
            var dataDirectory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "HENTAI Studio", "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: dataDirectory);
            await browser.EnsureCoreWebView2Async(environment);
            ConfigureBrowser();
            browser.Source = dashboard;
        }
        catch (WebView2RuntimeNotFoundException)
        {
            ShowError("The Microsoft WebView2 Runtime is missing. Repair Microsoft Edge WebView2 Runtime, then reopen HENTAI Studio.");
        }
        catch (Exception error)
        {
            ShowError("HENTAI Studio could not initialize.\n\n" + error.Message);
        }
    }

    private void ConfigureBrowser()
    {
        var settings = browser.CoreWebView2.Settings;
        settings.AreDefaultContextMenusEnabled = false;
        settings.AreDevToolsEnabled = true;
        settings.IsStatusBarEnabled = false;
        settings.IsZoomControlEnabled = true;
        settings.AreBrowserAcceleratorKeysEnabled = true;

        browser.CoreWebView2.NavigationCompleted += (_, args) =>
        {
            if (args.IsSuccess)
            {
                loadingPanel.Visible = false;
                browser.Focus();
            }
            else
            {
                ShowError($"The local dashboard failed to load ({args.WebErrorStatus}).\n\nPress Ctrl+R to retry.");
            }
        };
        browser.CoreWebView2.NewWindowRequested += (_, args) =>
        {
            args.Handled = true;
            Process.Start(new ProcessStartInfo(args.Uri) { UseShellExecute = true });
        };
        browser.CoreWebView2.ProcessFailed += (_, _) => browser.Reload();
    }

    private void StartDashboard()
    {
        var bundled = Path.Combine(AppContext.BaseDirectory, "backend", "Scripts", "hentai-studio.exe");
        var executable = Environment.GetEnvironmentVariable("STUDIO_EXECUTABLE")
            ?? (File.Exists(bundled) ? bundled : "hentai-studio");
        var workspace = Environment.GetEnvironmentVariable("STUDIO_WORKSPACE")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".hentai-studio");
        var logDirectory = Path.Combine(workspace, "logs");
        Directory.CreateDirectory(logDirectory);
        backendLog = Path.Combine(logDirectory, "server.log");
        var start = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden
        };
        foreach (var argument in new[] { "serve", "--workspace", workspace, "--host", dashboard.Host.Trim('[', ']'), "--port", dashboard.Port.ToString(), "--log-file", backendLog })
            start.ArgumentList.Add(argument);
        backend = new Process { StartInfo = start };
        backend.Start();
    }

    private async Task<bool> DashboardReadyAsync()
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
            using var response = await client.GetAsync(new Uri(dashboard, "/api/health"));
            if (!response.IsSuccessStatusCode) return false;
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var health = document.RootElement;
            if (health.ValueKind != JsonValueKind.Object
                || !health.TryGetProperty("application", out var application)
                || application.ValueKind != JsonValueKind.String || application.GetString() != "hentai-studio")
                return false;

            var cloud = health.TryGetProperty("location", out var location)
                && location.ValueKind == JsonValueKind.String && location.GetString() == "cloud";
            Text = $"HENTAI Studio — port {dashboard.Port} - {(cloud ? "Cloud" : "Local")}";
            return true;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or JsonException)
        {
            return false;
        }
    }

    private async Task<bool> WaitForDashboardAsync(TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (await DashboardReadyAsync()) return true;
            if (backend?.HasExited == true) return false;
            await Task.Delay(500);
        }
        return false;
    }

    private void ShowStartupFailure() => ShowError(
        "HENTAI Studio could not start its local dashboard.\n\n" +
        "Install the backend or set STUDIO_EXECUTABLE to its full executable path. " +
        $"Check the startup log: {backendLog}. " +
        (backend?.HasExited == true ? $"Backend exited with code {backend.ExitCode}." : "Backend did not become ready within 45 seconds."));

    private void ShowError(string message)
    {
        statusLabel.Text = message;
        statusLabel.ForeColor = Color.FromArgb(255, 150, 150);
        loadingPanel.Visible = true;
        loadingPanel.BringToFront();
    }
}
