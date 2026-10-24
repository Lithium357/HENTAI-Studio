using System.Diagnostics;
using System.Drawing;
using System.Net.Sockets;
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
    private const string DashboardUrl = "http://127.0.0.1:7860/";
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
            if (!await DashboardReadyAsync())
            {
                statusLabel.Text = "Starting the WSL training dashboard…";
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
            browser.Source = new Uri(DashboardUrl);
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

    private static void StartDashboard()
    {
        var distribution = Environment.GetEnvironmentVariable("HENTAI_WSL_DISTRO") ?? "Ubuntu";
        var project = Environment.GetEnvironmentVariable("HENTAI_WSL_PROJECT")
            ?? "/home/masonturlington/HENTAI";
        var studioProject = Environment.GetEnvironmentVariable("HENTAI_STUDIO_WSL_PROJECT")
            ?? "/home/masonturlington/HENTAI-Studio";
        var config = Environment.GetEnvironmentVariable("HENTAI_CONFIG")
            ?? "configs/rx7800xt-scratch-v3-x4-512.json";
        var start = new ProcessStartInfo
        {
            FileName = "wsl.exe",
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden
        };
        start.ArgumentList.Add("-d");
        start.ArgumentList.Add(distribution);
        start.ArgumentList.Add("--cd");
        start.ArgumentList.Add(studioProject);
        start.ArgumentList.Add("--");
        start.ArgumentList.Add(".venv/bin/hentai-studio");
        start.ArgumentList.Add("dashboard");
        start.ArgumentList.Add("--project");
        start.ArgumentList.Add(project);
        start.ArgumentList.Add("--config");
        start.ArgumentList.Add(config);
        start.ArgumentList.Add("--host");
        start.ArgumentList.Add("0.0.0.0");
        start.ArgumentList.Add("--port");
        start.ArgumentList.Add("7860");
        Process.Start(start);
    }

    private static async Task<bool> DashboardReadyAsync()
    {
        try
        {
            using var client = new TcpClient();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(1));
            await client.ConnectAsync("127.0.0.1", 7860, timeout.Token);
            return client.Connected;
        }
        catch
        {
            return false;
        }
    }

    private static async Task<bool> WaitForDashboardAsync(TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (await DashboardReadyAsync()) return true;
            await Task.Delay(500);
        }
        return false;
    }

    private void ShowStartupFailure() => ShowError(
        "HENTAI Studio could not start its WSL dashboard.\n\n" +
        "Confirm HENTAI_WSL_DISTRO, HENTAI_WSL_PROJECT, HENTAI_STUDIO_WSL_PROJECT, and HENTAI_CONFIG are correct, then check the project's logs directory.");

    private void ShowError(string message)
    {
        statusLabel.Text = message;
        statusLabel.ForeColor = Color.FromArgb(255, 150, 150);
        loadingPanel.Visible = true;
        loadingPanel.BringToFront();
    }
}
