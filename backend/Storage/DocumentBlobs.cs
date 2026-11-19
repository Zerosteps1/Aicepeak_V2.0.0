namespace Aicepeak.Api.Storage;

/// <summary>
/// Where documents live in <see cref="IBlobStorage"/>, independent of the provider: the space is the tenant ID and the
/// blob name <c>&lt;projectId&gt;/&lt;documentId&gt;</c> (the uploading project). Also holds the upload rules: upload
/// URLs live <see cref="UploadUrlLifetime"/> on the clock registered as keyed <see cref="TimeProvider"/>
/// <see cref="TimeProviderKey"/>, and a document has at most <see cref="MaxSize"/> bytes.
/// </summary>
public sealed class DocumentBlobs(IBlobStorage storage, [FromKeyedServices(DocumentBlobs.TimeProviderKey)] TimeProvider clock) {
    public const string TimeProviderKey = "blob-sas";

    /// <summary>50 MB (52 428 800 bytes). An upload URL cannot cap the size, so the declared and the stored size are checked.</summary>
    public const long MaxSize = 50L * 1024 * 1024;

    public static readonly TimeSpan UploadUrlLifetime = TimeSpan.FromMinutes(15);

    public static string Space(Guid tid) => tid.ToString("D");

    public static string BlobName(Guid projectId, Guid documentId) => $"{projectId:D}/{documentId:D}";

    /// <summary>A URL to create the document's blob, valid for <see cref="UploadUrlLifetime"/> from now (whole seconds).</summary>
    public async Task<(Uri Url, DateTimeOffset Expires)> CreateUploadUrlAsync(
        Guid tid, Guid projectId, Guid documentId, CancellationToken cancellationToken) {
        var now = clock.GetUtcNow();
        var expires = new DateTimeOffset(now.UtcTicks - now.UtcTicks % TimeSpan.TicksPerSecond, TimeSpan.Zero) + UploadUrlLifetime;
        var url = await storage.CreateUploadUrlAsync(Space(tid), BlobName(projectId, documentId), expires, cancellationToken);

        return (url, expires);
    }

    /// <summary>The document's URL without a query, as clients see it.</summary>
    public Uri GetUrl(Guid tid, string blobName) => storage.GetUrl(Space(tid), blobName);

    /// <summary>
    /// Parses a document URL of the tenant: <c>&lt;endpoint&gt;/&lt;tid&gt;/&lt;projectId&gt;/&lt;documentId&gt;</c> with
    /// lower-case GUIDs and nothing else. URLs of another endpoint or tenant fail.
    /// </summary>
    public bool TryParseUrl(Uri url, Guid tid, out Guid projectId, out Guid documentId) {
        projectId = Guid.Empty;
        documentId = Guid.Empty;
        if (!storage.TryParseUrl(url, out var space, out var name) || space != Space(tid)) {
            return false;
        }

        var segments = name.Split('/');
        return segments.Length == 2
            && Guid.TryParseExact(segments[0], "D", out projectId)
            && Guid.TryParseExact(segments[1], "D", out documentId)
            && name == BlobName(projectId, documentId);
    }

    public Task<BlobInfo?> GetInfoAsync(Guid tid, string blobName, CancellationToken cancellationToken) =>
        storage.GetInfoAsync(Space(tid), blobName, cancellationToken);

    public Task<Stream> OpenReadAsync(Guid tid, string blobName, CancellationToken cancellationToken) =>
        storage.OpenReadAsync(Space(tid), blobName, cancellationToken);

    public Task<bool> DeleteAsync(Guid tid, string blobName, CancellationToken cancellationToken) =>
        storage.DeleteAsync(Space(tid), blobName, cancellationToken);
}
