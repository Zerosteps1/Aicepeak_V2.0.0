using System.Text.Json;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>Reads the 503 problem details body of the health endpoint.</summary>
public sealed class HealthResponse(string body) {
    private readonly JsonElement _root = JsonDocument.Parse(body).RootElement;

    public string Body { get; } = body;

    public string? Detail => _root.TryGetProperty("detail", out var detail) ? detail.GetString() : null;

    public string? ComponentStatus(string component) =>
        _root.TryGetProperty("components", out var components) && components.TryGetProperty(component, out var status)
            ? status.GetString()
            : null;

    public string? ErrorDescription(string component) => ErrorField(component, "description");

    public string? ErrorException(string component) => ErrorField(component, "exception");

    private string? ErrorField(string component, string field) =>
        _root.TryGetProperty("errors", out var errors)
        && errors.TryGetProperty(component, out var error)
        && error.TryGetProperty(field, out var value)
            ? value.GetString()
            : null;

    public bool HasErrors => _root.TryGetProperty("errors", out _);
}
