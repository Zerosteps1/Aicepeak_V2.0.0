namespace Aicepeak.Api.Storage;

/// <summary>
/// Provider-neutral blob storage. A space is a container of blobs (an Azure container; for S3 a bucket or prefix);
/// names may contain <c>/</c>. Adapters live in their own namespace (today only <c>Storage.Azure</c>), so callers
/// never depend on a provider SDK.
/// </summary>
public interface IBlobStorage {
    /// <summary>
    /// A URL that allows creating exactly this blob until <paramref name="expiresOn"/>, never overwriting or reading it.
    /// Creates the space (private) if needed. The URL carries a signature and must never be logged.
    /// </summary>
    Task<Uri> CreateUploadUrlAsync(string space, string name, DateTimeOffset expiresOn, CancellationToken cancellationToken);

    /// <summary>The blob's URL without any query: the identifier clients send back.</summary>
    Uri GetUrl(string space, string name);

    /// <summary>
    /// Parses a URL created by <see cref="GetUrl"/>. Strict: same scheme, host, port and endpoint path, a space and a
    /// name, no query, fragment, user info or escaped characters.
    /// </summary>
    bool TryParseUrl(Uri url, out string space, out string name);

    /// <summary>Size, content type and last modification, or <c>null</c> if the blob or its space does not exist.</summary>
    Task<BlobInfo?> GetInfoAsync(string space, string name, CancellationToken cancellationToken);

    Task<Stream> OpenReadAsync(string space, string name, CancellationToken cancellationToken);

    /// <summary>Deletes the blob; <c>false</c> if it did not exist.</summary>
    Task<bool> DeleteAsync(string space, string name, CancellationToken cancellationToken);

    IAsyncEnumerable<BlobListItem> ListAsync(string space, CancellationToken cancellationToken);

    Task<bool> SpaceExistsAsync(string space, CancellationToken cancellationToken);
}

public sealed record BlobInfo(long Size, string ContentType, DateTimeOffset LastModified);

public sealed record BlobListItem(string Name, DateTimeOffset LastModified);
