using System.Text.Json;
using Microsoft.AspNetCore.Http.HttpResults;

namespace Aicepeak.Api.Projects;

/// <summary>
/// Collects every failure of a request with a short reason per field (e.g. <c>documents[2].size</c>), answered
/// together as one ValidationProblem. Reasons never contain stored values, internals or other tenants' data.
/// </summary>
internal sealed class ValidationErrors {
    /// <summary>The field of failures that concern the body as a whole.</summary>
    public const string BodyField = "body";

    private readonly Dictionary<string, List<string>> _errors = new(StringComparer.Ordinal);

    public bool Any => _errors.Count > 0;

    public bool Has(string field) => _errors.ContainsKey(field);

    public void Add(string field, string reason) {
        if (!_errors.TryGetValue(field, out var reasons)) {
            _errors[field] = reasons = [];
        }

        if (!reasons.Contains(reason)) {
            reasons.Add(reason);
        }
    }

    public ValidationProblem ToProblem() =>
        TypedResults.ValidationProblem(_errors.ToDictionary(error => error.Key, error => error.Value.ToArray()));

    /// <summary>The request body as a JSON object, or <c>null</c> with a failure added.</summary>
    public async Task<JsonDocument?> ReadObjectAsync(HttpRequest request, CancellationToken cancellationToken) {
        JsonDocument body;
        try {
            body = await JsonDocument.ParseAsync(request.Body, cancellationToken: cancellationToken);
        } catch (JsonException) {
            Add(BodyField, "is not valid JSON");
            return null;
        }

        if (body.RootElement.ValueKind != JsonValueKind.Object) {
            body.Dispose();
            Add(BodyField, "must be a JSON object");
            return null;
        }

        return body;
    }
}
