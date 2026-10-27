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
    private const string MutexName = @"Local\HENTAIStudio.Native.App";

    [STAThread]
    private static void Main()
    {
        using var mutex = new Mutex(true, MutexName, out var firstInstance);
        if (!firstInstance)
        {
            MessageBox.Show("HENTAI Studio is already running.", "HENTAI Studio",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        ApplicationConfiguration.Initialize();
        Application.Run(new StudioForm());
    }
}

internal sealed class StudioForm : Form
{
    private readonly Uri dashboard = new(Environment.GetEnvironmentVariable("STUDIO_URL") ?? "http://127.0.0.1:7860/");
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

    public StudioForm()
    {
        Text = "HENTAI Studio";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(1000, 700);
        Size = new Size(1500, 960);
        BackColor = Color.FromArgb(9, 11, 14);
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

        loadingPanel.Controls.Add(statusLabel);
        Controls.Add(browser);
        Controls.Add(loadingPanel);
        Shown += async (_, _) => await InitializeAsync();
    }

    private async Task InitializeAsync()
    {
        try
        {
            if (!dashboard.IsLoopback || dashboard.Scheme != "http" || dashboard.AbsolutePath != "/" || dashboard.Query.Length != 0 || dashboard.UserInfo.Length != 0)
                throw new InvalidOperationException("STUDIO_URL must be an http:// loopback address.");
            if (!await DashboardReadyAsync())
            {
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
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
            using var response = await client.GetAsync(new Uri(dashboard, "/api/health"));
            if (!response.IsSuccessStatusCode) return false;
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            return document.RootElement.ValueKind == JsonValueKind.Object
                && document.RootElement.TryGetProperty("application", out var application)
                && application.ValueKind == JsonValueKind.String && application.GetString() == "hentai-studio";
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
