using Aicepeak.Api.Configuration;
using Aicepeak.Api.Storage;
using Aicepeak.Api.Storage.Azure;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Tests.Storage;

/// <summary>
/// AC-1/AC-15/AC-17 offline: <see cref="DocumentBlobs"/> maps a tenant's document to space <c>&lt;tid&gt;</c> and blob
/// <c>&lt;projectId&gt;/&lt;documentId&gt;</c>, accepts only such URLs of the tenant, and dates upload URLs 15 minutes
/// ahead on its own clock.
/// </summary>
public sealed class DocumentBlobsTests {
    private static readonly Guid Tid = new("1b4e28ba-2fa1-41d2-883f-0016d3cca427");
    private static readonly Guid ProjectId = new("0193a5b2-0000-7000-8000-000000000001");
    private static readonly Guid DocumentId = new("0193a5b2-0000-7000-8000-000000000002");

    private readonly DocumentBlobs _blobs = new(
        new AzureBlobStorage(Options.Create(new BlobStorageOptions { Provider = "azure", ConnectionString = TestSettings.DevelopmentStorage })),
        TimeProvider.System);

    [Fact]
    public void AC01_SpaceIsTheTid_AndBlobNameIsProjectAndDocument() {
        Assert.Equal("1b4e28ba-2fa1-41d2-883f-0016d3cca427", DocumentBlobs.Space(Tid));
        Assert.Equal(
            "0193a5b2-0000-7000-8000-000000000001/0193a5b2-0000-7000-8000-000000000002",
            DocumentBlobs.BlobName(ProjectId, DocumentId));
        Assert.Equal(
            $"http://127.0.0.1:10000/devstoreaccount1/{Tid}/{ProjectId}/{DocumentId}",
            _blobs.GetUrl(Tid, DocumentBlobs.BlobName(ProjectId, DocumentId)).AbsoluteUri);
    }

    [Fact]
    public void AC15_TryParseUrl_ReturnsProjectAndDocument() {
        var url = _blobs.GetUrl(Tid, DocumentBlobs.BlobName(ProjectId, DocumentId));

        Assert.True(_blobs.TryParseUrl(url, Tid, out var projectId, out var documentId));
        Assert.Equal((ProjectId, DocumentId), (projectId, documentId));
    }

    [Theory]
    [InlineData("http://127.0.0.1:10000/devstoreaccount1/5b0f7c3e-2d4a-4e61-9f8b-7c6d5e4f3a2b/0193a5b2-0000-7000-8000-000000000001/0193a5b2-0000-7000-8000-000000000002")]
    [InlineData("http://127.0.0.1:10000/devstoreaccount1/1b4e28ba-2fa1-41d2-883f-0016d3cca427/0193A5B2-0000-7000-8000-000000000001/0193a5b2-0000-7000-8000-000000000002")]
    [InlineData("http://127.0.0.1:10000/devstoreaccount1/1b4e28ba-2fa1-41d2-883f-0016d3cca427/0193a5b2000070008000000000000001/0193a5b2-0000-7000-8000-000000000002")]
    [InlineData("http://127.0.0.1:10000/devstoreaccount1/1b4e28ba-2fa1-41d2-883f-0016d3cca427/0193a5b2-0000-7000-8000-000000000002")]
    [InlineData("http://127.0.0.1:10000/devstoreaccount1/1b4e28ba-2fa1-41d2-883f-0016d3cca427/0193a5b2-0000-7000-8000-000000000001/0193a5b2-0000-7000-8000-000000000002/x")]
    [InlineData("http://127.0.0.1:10000/devstoreaccount1/1b4e28ba-2fa1-41d2-883f-0016d3cca427/0193a5b2-0000-7000-8000-000000000001/report.pdf")]
    [InlineData("https://evil.example/devstoreaccount1/1b4e28ba-2fa1-41d2-883f-0016d3cca427/0193a5b2-0000-7000-8000-000000000001/0193a5b2-0000-7000-8000-000000000002")]
    public void AC15_TryParseUrl_RejectsOtherTenantsHostsAndShapes(string url) {
        Assert.False(_blobs.TryParseUrl(new Uri(url), Tid, out _, out _));
    }

    [Fact]
    public async Task AC17_UploadUrl_ExpiresAfter15Minutes_OnTheBlobSasClock_InWholeSeconds() {
        var storage = new RecordingStorage();
        var clock = new ShiftedTimeProvider(TimeSpan.FromDays(-3));
        var blobs = new DocumentBlobs(storage, clock);
        var before = clock.GetUtcNow();

        var (url, expires) = await blobs.CreateUploadUrlAsync(Tid, ProjectId, DocumentId, TestContext.Current.CancellationToken);

        Assert.Equal((Tid.ToString(), DocumentBlobs.BlobName(ProjectId, DocumentId), expires), storage.Requested);
        Assert.Equal(RecordingStorage.Url, url);
        Assert.Equal(0, expires.UtcTicks % TimeSpan.TicksPerSecond);
        Assert.InRange(expires - before, TimeSpan.FromMinutes(15) - TimeSpan.FromSeconds(1), TimeSpan.FromMinutes(15));
    }

    [Fact]
    public void AC19_MaxSize_Is50MB() {
        Assert.Equal(52_428_800, DocumentBlobs.MaxSize);
    }

    /// <summary>Records the upload URL request; nothing else is used here.</summary>
    private sealed class RecordingStorage : IBlobStorage {
        public static readonly Uri Url = new("https://storage.test/signed");

        public (string Space, string Name, DateTimeOffset Expires)? Requested { get; private set; }

        public Task<Uri> CreateUploadUrlAsync(string space, string name, DateTimeOffset expiresOn, CancellationToken cancellationToken) {
            Requested = (space, name, expiresOn);
            return Task.FromResult(Url);
        }

        public Uri GetUrl(string space, string name) => throw new NotSupportedException();

        public bool TryParseUrl(Uri url, out string space, out string name) => throw new NotSupportedException();

        public Task<BlobInfo?> GetInfoAsync(string space, string name, CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task<Stream> OpenReadAsync(string space, string name, CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task<bool> DeleteAsync(string space, string name, CancellationToken cancellationToken) => throw new NotSupportedException();

        public IAsyncEnumerable<BlobListItem> ListAsync(string space, CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task<bool> SpaceExistsAsync(string space, CancellationToken cancellationToken) => throw new NotSupportedException();
    }
}
