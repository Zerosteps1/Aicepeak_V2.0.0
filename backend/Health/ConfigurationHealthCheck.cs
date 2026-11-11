using Aicepeak.Api.Configuration;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Health;

/// <summary>Reports the validation result of the database settings (see <c>AddDatabase</c>).</summary>
public sealed class ConfigurationHealthCheck(IOptions<DatabaseOptions> options) : IHealthCheck {
    public Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken cancellationToken = default) {
        try {
            _ = options.Value;
            return Task.FromResult(HealthCheckResult.Healthy());
        } catch (OptionsValidationException exception) {
            return Task.FromResult(new HealthCheckResult(
                context.Registration.FailureStatus, string.Join(" ", exception.Failures), exception));
        }
    }
}
