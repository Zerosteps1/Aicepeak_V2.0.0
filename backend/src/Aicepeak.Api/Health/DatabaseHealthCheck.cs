using Aicepeak.Api.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Diagnostics.HealthChecks;

namespace Aicepeak.Api.Health;

/// <summary>
/// Checks that EF Core can reach the database. A round trip is needed: opening a pooled
/// connection succeeds without contacting the server.
/// </summary>
public sealed class DatabaseHealthCheck(AppDbContext db) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        try
        {
            await db.Database.ExecuteSqlAsync($"SELECT 1", cancellationToken);

            return HealthCheckResult.Healthy();
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            return new HealthCheckResult(context.Registration.FailureStatus, "Could not open a connection to the database.", exception);
        }
    }
}
