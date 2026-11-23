using System.Drawing.Drawing2D;
using System.Globalization;
using System.Text.Json.Nodes;

namespace HENTAIStudio;

internal sealed record MetricPoint(double X, double Y, double? Step);
internal sealed record MetricSeries(string Name, string Axis, List<MetricPoint> Points)
{
    public static MetricSeries Create(IEnumerable<JsonObject> rows, string key)
    {
        var values = rows.Where(row => row.Number(key).HasValue).Select(row => (Y: row.Number(key)!.Value, Step: row.Number("step"))).ToList();
        var steps = values.All(p => p.Step.HasValue) && values.Skip(1).Select((p, i) => p.Step >= values[i].Step).All(v => v);
        return new(key, steps ? "Step" : "Sample", values.Select((p, i) => new MetricPoint(steps ? p.Step!.Value : i + 1, p.Y, p.Step)).ToList());
    }
}

internal sealed class MetricChart : Control
{
    public MetricSeries Series { get; private set; } = new("", "Step", []);
    public int SelectedIndex { get; set; } = -1;
    public event EventHandler? PointSelected;
    public MetricChart()
    {
        DoubleBuffered = true; Dock = DockStyle.Fill; BackColor = Color.FromArgb(24, 26, 31); ForeColor = Color.Gainsboro;
        AccessibleName = "Training metric chart";
        MouseMove += (_, e) =>
        {
            if (Series.Points.Count == 0) return;
            var ratio = Math.Clamp((e.X - 65.0) / Math.Max(1, Width - 85), 0, 1);
            var x = Series.Points.Min(p => p.X) + ratio * (Series.Points.Max(p => p.X) - Series.Points.Min(p => p.X));
            SelectedIndex = Enumerable.Range(0, Series.Points.Count).MinBy(i => Math.Abs(Series.Points[i].X - x));
            Invalidate(); PointSelected?.Invoke(this, EventArgs.Empty);
        };
    }
    public void SetSeries(MetricSeries series) { Series = series; SelectedIndex = series.Points.Count - 1; Invalidate(); }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
        using var text = new SolidBrush(ForeColor); using var grid = new Pen(Color.FromArgb(48, 51, 59));
        var area = new RectangleF(65, 20, Math.Max(1, Width - 85), Math.Max(1, Height - 55));
        if (Series.Points.Count == 0) { g.DrawString("No numeric metrics recorded yet.", Font, text, 20, 30); return; }
        var points = Series.Points; var minX = points.Min(p => p.X); var maxX = points.Max(p => p.X); var minY = points.Min(p => p.Y); var maxY = points.Max(p => p.Y);
        string Label(double n) => n.ToString("G5", CultureInfo.InvariantCulture);
        for (var i = 0; i <= 4; i++)
        {
            var y = area.Top + area.Height * i / 4;
            g.DrawLine(grid, area.Left, y, area.Right, y);
            g.DrawString(Label(maxY - (maxY - minY) * i / 4), Font, text, 2, y - Font.Height / 2);
        }
        g.DrawString($"{Series.Axis} {Label(minX)}", Font, text, area.Left, area.Bottom + 8);
        var end = $"{Series.Axis} {Label(maxX)}";
        g.DrawString(end, Font, text, Math.Max(area.Left, area.Right - g.MeasureString(end, Font).Width), area.Bottom + 8);
        PointF Position(MetricPoint point) => new(area.Left + (float)((point.X-minX) / Math.Max(1, maxX-minX)) * area.Width,
            minY == maxY ? area.Top + area.Height / 2 : area.Bottom - (float)((point.Y-minY)/(maxY-minY))*area.Height);
        using var line = new Pen(Color.FromArgb(233, 161, 123), 2);
        if (points.Count > 1) g.DrawLines(line, points.Select(Position).ToArray());
        else { var p = Position(points[0]); g.FillEllipse(text, p.X-3, p.Y-3, 6, 6); }
        if (SelectedIndex >= 0 && SelectedIndex < points.Count)
        {
            var p = Position(points[SelectedIndex]); using var marker = new SolidBrush(Color.FromArgb(233, 161, 123));
            g.FillEllipse(marker, p.X-4, p.Y-4, 8, 8);
        }
    }
}
