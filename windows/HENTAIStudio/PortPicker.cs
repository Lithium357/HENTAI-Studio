namespace HENTAIStudio;

internal sealed class PortPicker : Form
{
    private readonly NumericUpDown port;
    private readonly CheckBox startLocal = new()
    {
        AutoSize = true,
        Text = "Start a local Studio backend if none is running"
    };

    public int Port => (int)port.Value;
    public bool StartLocalBackend => startLocal.Checked;

    public PortPicker(int defaultPort)
    {
        Text = "Connect to HENTAI Studio";
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        AutoSize = true;
        AutoSizeMode = AutoSizeMode.GrowAndShrink;
        port = new NumericUpDown { Minimum = 1, Maximum = 65535, Value = defaultPort, Width = 120, AccessibleName = "Studio port" };

        var connect = new Button { Text = "Connect", AutoSize = true, DialogResult = DialogResult.OK };
        var cancel = new Button { Text = "Cancel", AutoSize = true, DialogResult = DialogResult.Cancel };
        var buttons = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.LeftToRight };
        buttons.Controls.Add(connect);
        buttons.Controls.Add(cancel);

        var content = new FlowLayoutPanel
        {
            AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
            FlowDirection = FlowDirection.TopDown, WrapContents = false, Padding = new Padding(16)
        };
        content.Controls.Add(new Label
        {
            AutoSize = true, MaximumSize = new Size(360, 0),
            Text = "Enter the local port of a Studio backend or an SSH tunnel."
        });
        content.Controls.Add(new Label { AutoSize = true, Text = "Port" });
        content.Controls.Add(port);
        content.Controls.Add(startLocal);
        content.Controls.Add(buttons);
        Controls.Add(content);
        AcceptButton = connect;
        CancelButton = cancel;
        ActiveControl = port;
    }
}
