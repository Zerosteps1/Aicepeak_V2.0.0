using Aicepeak.Api.Configuration;
using Aicepeak.Api.Data;
using Aicepeak.Api.Storage;
using Aicepeak.Api.Storage.Azure;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Tests.Storage;

/// <summary>
/// The weekly orphan cleanup runs on Sunday at 03:00 UTC, and a failed run never ends the service (which would stop the
/// API), not even with a cancellation the host did not ask for.
/// </summary>
public sealed class OrphanCleanupScheduleTests {
    [Theory]
    [InlineData("2026-11-19T10:00:00+00:00", "2026-11-22T03:00:00+00:00")] // Thursday
    [InlineData("2026-11-22T02:59:59+00:00", "2026-11-22T03:00:00+00:00")] // Sunday, just before
    [InlineData("2026-11-22T03:00:00+00:00", "2026-11-29T03:00:00+00:00")] // Sunday, exactly at the run
    [InlineData("2026-11-22T03:00:01+00:00", "2026-11-29T03:00:00+00:00")] // Sunday, just after
    [InlineData("2026-11-21T23:59:59+00:00", "2026-11-22T03:00:00+00:00")] // Saturday night
    [InlineData("2026-11-22T04:30:00+02:00", "2026-11-22T03:00:00+00:00")] // Sunday 02:30 UTC in another offset
    [InlineData("2026-11-21T23:30:00-05:00", "2026-11-29T03:00:00+00:00")] // Sunday 04:30 UTC in another offset
    public void NextRun_IsTheNextSundayAt0300Utc(string now, string expected) {
        var next = OrphanBlobCleanupService.NextRun(DateTimeOffset.Parse(now));

        Assert.Equal(DateTimeOffset.Parse(expected), next);
        Assert.Equal(DayOfWeek.Sunday, next.UtcDateTime.DayOfWeek);
    }

    [Fact]
    public async Task RunFailingWithAnUnrequestedCancellation_IsLogged_AndTheServiceWaitsForTheNextRun() {
        var ct = TestContext.Current.CancellationToken;
        using var logs = new CapturingLoggerProvider();
        using var loggers = new LoggerFactory([logs]);
        // E.g. a provider timeout: an OperationCanceledException that does not come from the stopping token.
        await using var services = new ServiceCollection()
            .AddScoped<AppDbContext>(_ => throw new TaskCanceledException("A timeout, not a stop of the host."))
            .BuildServiceProvider();
        // The clock is a second before the next run, so the service runs right after the start.
        var now = TimeProvider.System.GetUtcNow();
        var clock = new ShiftedTimeProvider(OrphanBlobCleanupService.NextRun(now) - now - TimeSpan.FromSeconds(1));
        using var service = new OrphanBlobCleanupService(
            services.GetRequiredService<IServiceScopeFactory>(),
            new TenantDbContextFactory(Options.Create(new DatabaseOptions())),
            new AzureBlobStorage(Options.Create(new BlobStorageOptions())),
            clock,
            loggers.CreateLogger<OrphanBlobCleanupService>());

        await service.StartAsync(ct);
        using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct)) {
            timeout.CancelAfter(TimeSpan.FromSeconds(10));
            while (!logs.Entries.Any(entry => entry.Level == LogLevel.Error) && !service.ExecuteTask!.IsCompleted) {
                await Task.Delay(10, timeout.Token);
            }
        }

        Assert.False(service.ExecuteTask!.IsCompleted, $"The service ended: {service.ExecuteTask.Status}.");
        Assert.Contains(logs.Entries, entry => entry.Level == LogLevel.Error && entry.Message == "Orphan blob cleanup failed: TaskCanceledException.");
        await service.StopAsync(ct);
        Assert.True(service.ExecuteTask.IsCanceled);
    }
}
