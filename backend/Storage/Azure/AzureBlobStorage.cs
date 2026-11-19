using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using Aicepeak.Api.Configuration;
using Azure;
using Azure.Storage.Blobs;
using Azure.Storage.Blobs.Models;
using Azure.Storage.Sas;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Storage.Azure;

/// <summary>
/// The Azure Blob Storage adapter of <see cref="IBlobStorage"/> and the only code that uses the Azure SDK. A space is a
/// private container. Upload URLs are service SAS URLs for one blob with only the create permission (<c>sp=c</c>,
/// <c>sr=b</c>) and no start time, HTTPS only unless the endpoint itself is HTTP (Azurite). The client is created on
/// first use, so invalid <see cref="BlobStorageOptions"/> fail requests, never the start.
/// </summary>
public sealed class AzureBlobStorage(IOptions<BlobStorageOptions> options) : IBlobStorage {
    private readonly Lazy<BlobServiceClient> _client = new(
        () => new BlobServiceClient(options.Value.ConnectionString!.Trim()), LazyThreadSafetyMode.PublicationOnly);

    private readonly ConcurrentDictionary<string, bool> _createdSpaces = new(StringComparer.Ordinal);

    /// <summary>True if the connection string can be parsed and signs SAS URLs (it carries a shared key).</summary>
    public static bool CanSignUploadUrls(string connectionString) {
        try {
            return new BlobServiceClient(connectionString.Trim()).CanGenerateAccountSasUri;
        } catch (Exception exception) when (exception is FormatException or ArgumentException or InvalidOperationException) {
            return false;
        }
    }

    public async Task<Uri> CreateUploadUrlAsync(string space, string name, DateTimeOffset expiresOn, CancellationToken cancellationToken) {
        if (!_createdSpaces.ContainsKey(space)) {
            await Container(space).CreateIfNotExistsAsync(PublicAccessType.None, null, null, cancellationToken);
            _createdSpaces[space] = true;
        }

        return CreateUploadSasUri(space, name, expiresOn);
    }

    /// <summary>The signed upload URL, computed locally without contacting the service.</summary>
    internal Uri CreateUploadSasUri(string space, string name, DateTimeOffset expiresOn) {
        var blob = Container(space).GetBlobClient(name);
        var sas = new BlobSasBuilder(BlobSasPermissions.Create, expiresOn) {
            BlobContainerName = space,
            BlobName = name,
            Resource = "b",
            Protocol = blob.Uri.Scheme == Uri.UriSchemeHttps ? SasProtocol.Https : SasProtocol.HttpsAndHttp,
        };

        return blob.GenerateSasUri(sas);
    }

    public Uri GetUrl(string space, string name) => Container(space).GetBlobClient(name).Uri;

    public bool TryParseUrl(Uri url, out string space, out string name) {
        space = "";
        name = "";
        var endpoint = _client.Value.Uri;
        if (!url.IsAbsoluteUri
            || url.Query.Length > 0
            || url.Fragment.Length > 0
            || url.UserInfo.Length > 0
            || !string.Equals(url.Scheme, endpoint.Scheme, StringComparison.OrdinalIgnoreCase)
            || !string.Equals(url.Host, endpoint.Host, StringComparison.OrdinalIgnoreCase)
            || url.Port != endpoint.Port) {
            return false;
        }

        var prefix = endpoint.AbsolutePath.TrimEnd('/') + "/";
        var path = url.AbsolutePath;
        if (!path.StartsWith(prefix, StringComparison.Ordinal) || path.Contains('%')) {
            return false;
        }

        var rest = path[prefix.Length..];
        var slash = rest.IndexOf('/');
        if (slash <= 0 || slash == rest.Length - 1) {
            return false;
        }

        (space, name) = (rest[..slash], rest[(slash + 1)..]);
        return GetUrl(space, name).AbsoluteUri == url.AbsoluteUri;
    }

    public async Task<BlobInfo?> GetInfoAsync(string space, string name, CancellationToken cancellationToken) {
        try {
            var properties = (await Container(space).GetBlobClient(name).GetPropertiesAsync(cancellationToken: cancellationToken)).Value;
            return new BlobInfo(properties.ContentLength, properties.ContentType ?? "", properties.LastModified);
        } catch (RequestFailedException exception) when (exception.Status == StatusCodes.Status404NotFound) {
            return null;
        }
    }

    public async Task<Stream> OpenReadAsync(string space, string name, CancellationToken cancellationToken) {
        var download = await Container(space).GetBlobClient(name).DownloadStreamingAsync(new BlobDownloadOptions(), cancellationToken);
        return download.Value.Content;
    }

    public async Task<bool> DeleteAsync(string space, string name, CancellationToken cancellationToken) {
        var deleted = await Container(space).GetBlobClient(name)
            .DeleteIfExistsAsync(DeleteSnapshotsOption.IncludeSnapshots, conditions: null, cancellationToken);
        return deleted.Value;
    }

    public async IAsyncEnumerable<BlobListItem> ListAsync(string space, [EnumeratorCancellation] CancellationToken cancellationToken) {
        await foreach (var blob in Container(space).GetBlobsAsync(new GetBlobsOptions(), cancellationToken)) {
            // Without a modification time a blob never counts as old.
            yield return new BlobListItem(blob.Name, blob.Properties.LastModified ?? DateTimeOffset.MaxValue);
        }
    }

    public async Task<bool> SpaceExistsAsync(string space, CancellationToken cancellationToken) =>
        (await Container(space).ExistsAsync(cancellationToken)).Value;

    private BlobContainerClient Container(string space) => _client.Value.GetBlobContainerClient(space);
}
