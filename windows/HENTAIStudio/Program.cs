using System.Diagnostics;

namespace HENTAIStudio;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var address = Environment.GetEnvironmentVariable("STUDIO_URL") ?? "http://127.0.0.1:7860/";
        var connectOnly = true;
        if (args is ["--connect", var endpoint]) address = endpoint;
        else if (args.Length == 0 || args is ["--pick-port", _])
        {
            var port = Uri.TryCreate(address, UriKind.Absolute, out var configured) ? configured.Port : 7860;
            if (args.Length == 2 && (!int.TryParse(args[1], out port) || port is < 1 or > 65535))
            { MessageBox.Show("Choose a port from 1 to 65535.", "HENTAI Studio"); return; }
            using var picker = new PortPicker(port);
            if (picker.ShowDialog() != DialogResult.OK) return;
            address = $"http://127.0.0.1:{picker.Port}/";
            connectOnly = !picker.StartLocalBackend;
        }
        else { MessageBox.Show("Usage: HENTAI Studio.exe [--pick-port PORT | --connect http://127.0.0.1:PORT/]", "HENTAI Studio"); return; }
        if (!Uri.TryCreate(address, UriKind.Absolute, out var origin) || !origin.IsLoopback || origin.Scheme != "http"
            || origin.AbsolutePath != "/" || origin.Query.Length != 0 || origin.UserInfo.Length != 0 || origin.Fragment.Length != 0)
        { MessageBox.Show("Use an HTTP loopback address, such as http://127.0.0.1:8786/.", "HENTAI Studio"); return; }
        Application.Run(new StudioForm(origin, connectOnly));
    }

    public static void NewWindow(int port)
    {
        var start = new ProcessStartInfo(Application.ExecutablePath);
        start.ArgumentList.Add("--pick-port"); start.ArgumentList.Add(port.ToString());
        Process.Start(start)?.Dispose();
    }
}
