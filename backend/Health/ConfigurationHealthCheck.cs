using Aicepeak.Api.Configuration;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Health;

/// <summary>Checks that the database settings are present and form a valid connection string.</summary>
public sealed class ConfigurationHealthCheck(IOptions<DatabaseOptions> options) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        var database = DatabaseConnectionString.Create(options.Value);

        return Task.FromResult(database.IsValid
            ? HealthCheckResult.Healthy()
            : new HealthCheckResult(context.Registration.FailureStatus, database.Problem, database.Error));
    }
}
