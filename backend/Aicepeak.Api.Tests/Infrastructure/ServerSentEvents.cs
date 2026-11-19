using System.Text.Json;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>Reads a complete <c>text/event-stream</c> body.</summary>
public static class ServerSentEvents {
    /// <summary>The JSON payload of every event, in order. Fails on lines other than <c>data:</c> and blank lines.</summary>
    public static List<JsonElement> Parse(string body) {
        var events = new List<JsonElement>();
        foreach (var line in body.Split('\n')) {
            if (line.Length == 0) {
                continue;
            }

            Assert.StartsWith("data: ", line);
            events.Add(JsonDocument.Parse(line["data: ".Length..]).RootElement.Clone());
        }

        return events;
    }

    public static async Task<List<JsonElement>> ReadAsync(HttpResponseMessage response) {
        Assert.Equal("text/event-stream", response.Content.Headers.ContentType?.MediaType);
        return Parse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
    }

    public static int? Int(this JsonElement element, string property) =>
        element.TryGetProperty(property, out var value) ? value.GetInt32() : null;

    public static string? String(this JsonElement element, string property) =>
        element.TryGetProperty(property, out var value) ? value.GetString() : null;
}
