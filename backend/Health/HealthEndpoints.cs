using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.Extensions.Diagnostics.HealthChecks;

namespace Aicepeak.Api.Health;

public static class HealthEndpoints
{
    public const string AlivePath = "/api/v1/health/alive";

    public static IServiceCollection AddHealth(this IServiceCollection services)
    {
        services.AddHealthChecks()
            .AddCheck<ConfigurationHealthCheck>("configuration")
            .AddCheck<DatabaseHealthCheck>("database", timeout: TimeSpan.FromSeconds(5));

        return services;
    }

    /// <summary>204 when all checks pass, 503 with problem details otherwise. Always anonymous.</summary>
    public static IEndpointConventionBuilder MapHealth(this IEndpointRouteBuilder endpoints) =>
        endpoints.MapHealthChecks(AlivePath, new HealthCheckOptions
        {
            ResultStatusCodes =
            {
                [HealthStatus.Healthy] = StatusCodes.Status204NoContent,
                [HealthStatus.Degraded] = StatusCodes.Status503ServiceUnavailable,
                [HealthStatus.Unhealthy] = StatusCodes.Status503ServiceUnavailable,
            },
            ResponseWriter = HealthResponseWriter.WriteAsync,
        }).AllowAnonymous();
}
