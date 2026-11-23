using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json.Nodes;

namespace HENTAIStudio;

internal static class JsonData
{
    public static string Text(this JsonNode? node, string key, string fallback = "") => node?[key]?.ToString() ?? fallback;
    public static bool Flag(this JsonNode? node, string key) => node?[key] is JsonValue value && value.TryGetValue<bool>(out var flag) && flag;
    public static double? Number(this JsonNode? node, string key) => double.TryParse(node?[key]?.ToString(), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var value) && double.IsFinite(value) ? value : null;
    public static bool Busy(this JsonNode? node) => node.Text("state") is "starting" or "running" or "stopping" || node.Flag("has_live_processes");
    public static string Date(this JsonNode? node, string key) => DateTimeOffset.TryParse(node.Text(key), out var date) ? date.ToLocalTime().ToString("MMM d, HH:mm") : "—";
    public static string Pretty(JsonNode? node) => node?.ToJsonString(new() { WriteIndented = true }) ?? "{}";
}

internal sealed class StudioApi : IDisposable
{
    private readonly HttpClient http;
    public Uri Origin { get; }
    public StudioApi(Uri origin)
    {
        Origin = origin;
        http = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { BaseAddress = origin, Timeout = TimeSpan.FromSeconds(130) };
    }
    private static string Id(string id) => Uri.EscapeDataString(id);
    public static string ProjectPath(string id) => "/api/projects/" + Id(id);
    public static string JobPath(string id) => "/api/jobs/" + Id(id);
    public async Task<JsonNode> Request(string path, CancellationToken token, HttpMethod? method = null, JsonNode? body = null)
    {
        if (!path.StartsWith("/api/", StringComparison.Ordinal) || path.StartsWith("//")) throw new ArgumentException("Invalid API path.");
        using var request = new HttpRequestMessage(method ?? HttpMethod.Get, path);
        if (body is not null) request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
        using var response = await http.SendAsync(request, token);
        var text = await response.Content.ReadAsStringAsync(token);
        JsonNode? result = null;
        if (text.Length > 0) { try { result = JsonNode.Parse(text); } catch (System.Text.Json.JsonException) { } }
        if (!response.IsSuccessStatusCode) throw new InvalidOperationException(result?["error"].Text("message", $"Studio returned HTTP {(int)response.StatusCode}.") ?? $"Studio returned HTTP {(int)response.StatusCode}.");
        if (response.StatusCode == HttpStatusCode.NoContent) return new JsonObject();
        return result ?? throw new InvalidOperationException("Studio returned an invalid JSON response.");
    }
    public async Task<List<JsonObject>> Collection(string path, CancellationToken token)
    {
        var result = new List<JsonObject>(); string? cursor = null;
        var cursors = new HashSet<string>();
        do
        {
            var page = await Request(path + (cursor is null ? "" : (path.Contains('?') ? "&" : "?") + "cursor=" + Id(cursor)), token);
            if (page["items"] is not JsonArray items) throw new InvalidOperationException("Studio returned an invalid collection.");
            result.AddRange(items.OfType<JsonObject>());
            cursor = page.Text("next_cursor");
            if (cursor.Length == 0) cursor = null;
            else if (!cursors.Add(cursor)) throw new InvalidOperationException("Studio returned a repeated page cursor.");
        } while (cursor is not null);
        return result;
    }
    public async Task Download(string job, string path, string destination, CancellationToken token)
    {
        var encoded = string.Join("/", path.Split('/').Select(Id));
        using var response = await http.GetAsync(JobPath(job) + "/artifacts/" + encoded, HttpCompletionOption.ResponseHeadersRead, token);
        response.EnsureSuccessStatusCode();
        var temporary = destination + "." + Guid.NewGuid().ToString("N") + ".partial";
        try
        {
            await using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                await response.Content.CopyToAsync(stream, token);
            File.Move(temporary, destination, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
    public void Dispose() => http.Dispose();
}
