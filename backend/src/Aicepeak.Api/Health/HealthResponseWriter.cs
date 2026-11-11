using Microsoft.Extensions.Diagnostics.HealthChecks;

namespace Aicepeak.Api.Health;

/// <summary>
/// Writes nothing when healthy (204). Otherwise writes problem details naming the failing components;
/// descriptions and exception traces are added only in Development.
/// </summary>
public static class HealthResponseWriter
{
    public static Task WriteAsync(HttpContext context, HealthReport report)
    {
        if (report.Status == HealthStatus.Healthy)
        {
            return Task.CompletedTask;
        }

        var failing = report.Entries.Where(entry => entry.Value.Status != HealthStatus.Healthy).ToList();
        var extensions = new Dictionary<string, object?>
        {
            ["components"] = report.Entries.ToDictionary(entry => entry.Key, entry => entry.Value.Status.ToString()),
        };

        if (context.RequestServices.GetRequiredService<IHostEnvironment>().IsDevelopment())
        {
            extensions["errors"] = failing.ToDictionary(
                entry => entry.Key,
                entry => new { description = entry.Value.Description, exception = entry.Value.Exception?.ToString() });
        }

        return Results.Problem(
                title: "Service Unavailable",
                detail: $"Failing components: {string.Join(", ", failing.Select(entry => entry.Key))}.",
                statusCode: context.Response.StatusCode,
                extensions: extensions)
            .ExecuteAsync(context);
    }
}
