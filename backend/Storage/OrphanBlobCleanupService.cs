using Aicepeak.Api.Data;
using Microsoft.EntityFrameworkCore;

namespace Aicepeak.Api.Storage;

/// <summary>
/// Once a week (Sunday 03:00 UTC) deletes orphaned blobs: blobs in a tenant's space without a <c>documents</c> row,
/// e.g. uploads never added by a PATCH or duplicates whose deletion failed. Blobs younger than
/// <see cref="MinimumAge"/> are kept, so uploads in progress survive. Runs for every allowed tenant whose database and
/// space exist; several instances running at once only try to delete the same blobs. Logs counts, never names.
/// A failed run or tenant is logged and skipped, including a cancellation the host did not ask for (e.g. a provider
/// timeout): only the stopping token ends the service, so a failure never stops the API.
/// </summary>
public sealed class OrphanBlobCleanupService(
    IServiceScopeFactory scopes,
    TenantDbContextFactory tenantDatabases,
    IBlobStorage storage,
    TimeProvider time,
    ILogger<OrphanBlobCleanupService> logger) : BackgroundService {
    public static readonly TimeSpan MinimumAge = TimeSpan.FromHours(1);

    public sealed record Result(int Tenants, int Deleted, int Failed);

    /// <summary>The first Sunday 03:00 UTC strictly after <paramref name="now"/>.</summary>
    public static DateTimeOffset NextRun(DateTimeOffset now) {
        var today = now.UtcDateTime.Date;
        var daysUntilSunday = ((int)DayOfWeek.Sunday - (int)today.DayOfWeek + 7) % 7;
        var run = new DateTimeOffset(today.AddDays(daysUntilSunday).AddHours(3), TimeSpan.Zero);
        return run > now ? run : run.AddDays(7);
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken) {
        while (true) {
            var now = time.GetUtcNow();
            await Task.Delay(NextRun(now) - now, time, stoppingToken);
            try {
                await CleanupAsync(stoppingToken);
            } catch (Exception exception) when (!stoppingToken.IsCancellationRequested) {
                logger.LogError("Orphan blob cleanup failed: {Failure}.", exception.GetType().Name);
            }
        }
    }

    /// <summary>One cleanup pass over all tenants.</summary>
    internal async Task<Result> CleanupAsync(CancellationToken cancellationToken) {
        var cutoff = time.GetUtcNow() - MinimumAge;
        List<Guid> tenants;
        HashSet<string> databases;
        await using (var scope = scopes.CreateAsyncScope()) {
            var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
            tenants = await db.AllowedTenants.Select(tenant => tenant.Tid).ToListAsync(cancellationToken);
            databases = (await db.Database.SqlQuery<string>($"SELECT datname AS \"Value\" FROM pg_database").ToListAsync(cancellationToken))
                .ToHashSet(StringComparer.Ordinal);
        }

        var (cleaned, deleted, failed) = (0, 0, 0);
        foreach (var tid in tenants.Where(tid => databases.Contains(TenantDbContextFactory.DatabaseName(tid)))) {
            try {
                if (!await storage.SpaceExistsAsync(DocumentBlobs.Space(tid), cancellationToken)) {
                    continue;
                }

                deleted += await CleanupTenantAsync(tid, cutoff, cancellationToken);
                cleaned++;
            } catch (Exception exception) when (!cancellationToken.IsCancellationRequested) {
                failed++;
                logger.LogWarning("Orphan blob cleanup of tenant {Tid} failed: {Failure}.", tid, exception.GetType().Name);
            }
        }

        logger.LogInformation(
            "Orphan blob cleanup deleted {Deleted} blobs in {Tenants} tenants; {Failed} tenants failed.", deleted, cleaned, failed);
        return new Result(cleaned, deleted, failed);
    }

    private async Task<int> CleanupTenantAsync(Guid tid, DateTimeOffset cutoff, CancellationToken cancellationToken) {
        var space = DocumentBlobs.Space(tid);
        await using var db = tenantDatabases.Create(tid);
        var referenced = (await db.Documents.Select(document => document.BlobName).ToListAsync(cancellationToken))
            .ToHashSet(StringComparer.Ordinal);

        var deleted = 0;
        await foreach (var blob in storage.ListAsync(space, cancellationToken)) {
            if (blob.LastModified >= cutoff || referenced.Contains(blob.Name)) {
                continue;
            }

            // Asked again right before deleting: a PATCH may have added the document since the list was read.
            if (!await db.Documents.AnyAsync(document => document.BlobName == blob.Name, cancellationToken)
                && await storage.DeleteAsync(space, blob.Name, cancellationToken)) {
                deleted++;
            }
        }

        return deleted;
    }
}
