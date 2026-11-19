using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Documents.Analysis.Mock;

/// <summary>
/// MOCK – AIC-02: waits like a real analysis step would: <c>MOCK_PROCESSING_STEP_MS</c> times a random factor from 0.5
/// to 1.5, drawn from the <see cref="Random"/> registered under <see cref="RandomKey"/>. The delay never changes what
/// the mocks report.
/// </summary>
public sealed class MockProcessingDelay(
    IOptions<MockProcessingOptions> options, [FromKeyedServices(MockProcessingDelay.RandomKey)] Random random, TimeProvider time) {
    public const string RandomKey = "mock-processing";

    private readonly Lock _randomLock = new();

    /// <summary>The duration of the next step; zero when <c>MOCK_PROCESSING_STEP_MS</c> is 0.</summary>
    public TimeSpan Next() {
        var step = options.Value.StepMilliseconds;
        if (step <= 0) {
            return TimeSpan.Zero;
        }

        double factor;
        lock (_randomLock) {
            factor = 0.5 + random.NextDouble();
        }

        return TimeSpan.FromMilliseconds(step * factor);
    }

    public Task WaitAsync(CancellationToken cancellationToken) {
        var delay = Next();
        return delay == TimeSpan.Zero ? Task.CompletedTask : Task.Delay(delay, time, cancellationToken);
    }
}
