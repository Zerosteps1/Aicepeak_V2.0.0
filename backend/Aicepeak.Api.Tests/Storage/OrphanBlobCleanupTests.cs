using System.Text;
using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Storage;
using Aicepeak.Api.Tests.Infrastructure;
using Azure.Storage.Blobs;
using Azure.Storage.Blobs.Models;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using BlobInfo = Aicepeak.Api.Storage.BlobInfo;

namespace Aicepeak.Api.Tests.Storage;

/// <summary>
/// <see cref="OrphanBlobCleanupService"/> against PostgreSQL and Azurite (Docker): blobs without a document row are
/// deleted once they are older than an hour; referenced and recent blobs, and tenants without a database, are kept. A
/// tenant that fails, even with a cancellation the caller did not ask for, is counted and the others are still cleaned.
/// Each test has its own main database, so only its own tenants are cleaned.
/// </summary>
[Collection(StorageCollection.Name)]
[Trait("Category", "Database")]
public sealed class OrphanBlobCleanupTests(PostgresFixture postgres, AzuriteFixture azurite) {
    [Fact]
    public async Task UnreferencedBlobs_OlderThanAnHour_AreDeleted_ReferencedAndRecentOnesAreKept() {
        var ct = TestContext.Current.CancellationToken;
        await using var api = await TenantApi.CreateAsync(postgres, azurite, mainDatabase: MainDatabase());
        var projectId = await api.CreateProjectAsync();
        var referenced = await api.AddDocumentAsync(projectId, TenantApi.File("kept"), "Bilanz.pdf");
        var orphan = TenantApi.WithoutQuery(await api.UploadAsync(projectId, TenantApi.File("orphan"), "Nie hinzugefügt.pdf"));
        var clock = new ShiftedTimeProvider(TimeSpan.Zero);
        var cleanup = Cleanup(api, clock);

        var recent = await cleanup.CleanupAsync(ct);

        Assert.Equal(new OrphanBlobCleanupService.Result(1, 0, 0), recent);
        Assert.Equal(2, (await BlobNamesAsync(api.Container)).Count);

        clock.Offset = OrphanBlobCleanupService.MinimumAge + TimeSpan.FromMinutes(5);
        var old = await cleanup.CleanupAsync(ct);

        Assert.Equal(new OrphanBlobCleanupService.Result(1, 1, 0), old);
        Assert.Equal([$"{projectId}/{TenantApi.DocumentId(referenced.Url)}"], await BlobNamesAsync(api.Container));
        Assert.DoesNotContain($"{projectId}/{TenantApi.DocumentId(orphan)}", await BlobNamesAsync(api.Container));
        Assert.Equal([referenced], Documents(await api.GetProjectAsync(projectId)));
    }

    [Fact]
    public async Task AllowedTenantWithoutDatabase_IsSkipped_AndItsBlobsAreKept() {
        var ct = TestContext.Current.CancellationToken;
        var mainDatabase = MainDatabase();
        await using var api = await TenantApi.CreateAsync(postgres, azurite, mainDatabase: mainDatabase);
        var tenantWithoutDatabase = Guid.NewGuid();
        await using (var db = new AppDbContext(new DbContextOptionsBuilder<AppDbContext>().UseNpgsql(postgres.ConnectionString(mainDatabase)).Options)) {
            db.AllowedTenants.Add(new AllowedTenant { Tid = tenantWithoutDatabase });
            await db.SaveChangesAsync(ct);
        }

        var container = new BlobServiceClient(azurite.ConnectionString).GetBlobContainerClient(tenantWithoutDatabase.ToString());
        await container.CreateIfNotExistsAsync(cancellationToken: ct);
        await container.UploadBlobAsync("stray", new BinaryData(Encoding.UTF8.GetBytes("x")), ct);

        var result = await Cleanup(api, new ShiftedTimeProvider(TimeSpan.FromDays(1))).CleanupAsync(ct);

        Assert.Equal(new OrphanBlobCleanupService.Result(0, 0, 0), result);
        Assert.Equal(["stray"], await BlobNamesAsync(container));
    }

    [Fact]
    public async Task TenantFailingWithAnUnrequestedCancellation_IsCountedAsFailed_AndTheOthersAreCleaned() {
        var ct = TestContext.Current.CancellationToken;
        var mainDatabase = MainDatabase();
        await using var failing = await TenantApi.CreateAsync(postgres, azurite, mainDatabase: mainDatabase);
        await using var cleaned = await TenantApi.CreateAsync(postgres, azurite, mainDatabase: mainDatabase);
        var failingOrphan = await UploadOrphanAsync(failing);
        await UploadOrphanAsync(cleaned);
        var storage = new ListTimingOutStorage(cleaned.Factory.Services.GetRequiredService<IBlobStorage>(), DocumentBlobs.Space(failing.Tid));
        var clock = new ShiftedTimeProvider(OrphanBlobCleanupService.MinimumAge + TimeSpan.FromMinutes(5));

        var result = await Cleanup(cleaned, clock, storage).CleanupAsync(ct);

        Assert.Equal(new OrphanBlobCleanupService.Result(1, 1, 1), result);
        Assert.Equal([failingOrphan], await BlobNamesAsync(failing.Container));
        Assert.Empty(await BlobNamesAsync(cleaned.Container));
    }

    private static string MainDatabase() => $"orphan_{Guid.NewGuid():N}";

    /// <summary>Uploads a file that is never added to the project; returns its blob name.</summary>
    private static async Task<string> UploadOrphanAsync(TenantApi api) {
        var projectId = await api.CreateProjectAsync();
        var blobUrl = await api.UploadAsync(projectId, TenantApi.File($"orphan {api.Tid}"), "Nie hinzugefügt.pdf");
        return $"{projectId}/{TenantApi.DocumentId(blobUrl)}";
    }

    /// <summary>The service with the app's settings (main database, Azurite) and a test clock; not started.</summary>
    private static OrphanBlobCleanupService Cleanup(TenantApi api, TimeProvider clock, IBlobStorage? storage = null) => new(
        api.Factory.Services.GetRequiredService<IServiceScopeFactory>(),
        api.Factory.Services.GetRequiredService<TenantDbContextFactory>(),
        storage ?? api.Factory.Services.GetRequiredService<IBlobStorage>(),
        clock,
        NullLogger<OrphanBlobCleanupService>.Instance);

    private static async Task<List<string>> BlobNamesAsync(BlobContainerClient container) {
        var names = new List<string>();
        await foreach (var blob in container.GetBlobsAsync(new GetBlobsOptions(), TestContext.Current.CancellationToken)) {
            names.Add(blob.Name);
        }

        return names;
    }

    private static List<DocumentRefBody> Documents(System.Text.Json.JsonElement project) =>
        System.Text.Json.JsonSerializer.Deserialize<List<DocumentRefBody>>(
            project.GetProperty("documents"), System.Text.Json.JsonSerializerOptions.Web)!;

    /// <summary>
    /// The real storage, except that listing <paramref name="failingSpace"/> fails like a provider timeout: with an
    /// <see cref="OperationCanceledException"/> that does not come from the caller's token.
    /// </summary>
    private sealed class ListTimingOutStorage(IBlobStorage inner, string failingSpace) : IBlobStorage {
        public IAsyncEnumerable<BlobListItem> ListAsync(string space, CancellationToken cancellationToken) =>
            space == failingSpace
                ? throw new TaskCanceledException("A timeout, not a cancellation by the caller.")
                : inner.ListAsync(space, cancellationToken);

        public Task<Uri> CreateUploadUrlAsync(string space, string name, DateTimeOffset expiresOn, CancellationToken cancellationToken) =>
            inner.CreateUploadUrlAsync(space, name, expiresOn, cancellationToken);

        public Uri GetUrl(string space, string name) => inner.GetUrl(space, name);

        public bool TryParseUrl(Uri url, out string space, out string name) => inner.TryParseUrl(url, out space, out name);

        public Task<BlobInfo?> GetInfoAsync(string space, string name, CancellationToken cancellationToken) =>
            inner.GetInfoAsync(space, name, cancellationToken);

        public Task<Stream> OpenReadAsync(string space, string name, CancellationToken cancellationToken) =>
            inner.OpenReadAsync(space, name, cancellationToken);

        public Task<bool> DeleteAsync(string space, string name, CancellationToken cancellationToken) =>
            inner.DeleteAsync(space, name, cancellationToken);

        public Task<bool> SpaceExistsAsync(string space, CancellationToken cancellationToken) => inner.SpaceExistsAsync(space, cancellationToken);
    }
}
