using Aicepeak.Api.Configuration;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Health;

/// <summary>
/// Reports the validation result of the database and blob storage settings (see <c>AddDatabase</c> and
/// <c>AddBlobStorage</c>), naming every failing setting.
/// </summary>
public sealed class ConfigurationHealthCheck(IOptions<DatabaseOptions> database, IOptions<BlobStorageOptions> blobStorage) : IHealthCheck {
    public Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken cancellationToken = default) {
        var failures = new[] { Validate(() => database.Value), Validate(() => blobStorage.Value) }.OfType<OptionsValidationException>().ToList();
        if (failures.Count == 0) {
            return Task.FromResult(HealthCheckResult.Healthy());
        }

        return Task.FromResult(new HealthCheckResult(
            context.Registration.FailureStatus,
            string.Join(" ", failures.SelectMany(failure => failure.Failures)),
            failures.Count == 1 ? failures[0] : new AggregateException(failures)));
    }

    private static OptionsValidationException? Validate(Func<object> getOptions) {
        try {
            _ = getOptions();
            return null;
        } catch (OptionsValidationException exception) {
            return exception;
        }
    }
}
