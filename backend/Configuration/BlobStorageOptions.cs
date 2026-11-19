namespace Aicepeak.Api.Configuration;

/// <summary>
/// Blob storage settings under the configuration keys <c>BLOB_PROVIDER</c> and <c>BLOB_CON_STR</c>: environment
/// variables, in Development also <c>.env</c>. Validated in <c>AddBlobStorage</c>; invalid settings never stop the app.
/// </summary>
public sealed class BlobStorageOptions {
    public const string ProviderKey = "BLOB_PROVIDER";
    public const string ConnectionStringKey = "BLOB_CON_STR";

    /// <summary>The only provider today.</summary>
    public const string AzureProvider = "azure";

    /// <summary>The storage provider; <see cref="AzureProvider"/> is the only one today.</summary>
    [ConfigurationKeyName(ProviderKey)]
    public string? Provider { get; set; }

    /// <summary>The provider's connection string; for Azure one that can sign SAS URLs (a shared key credential).</summary>
    [ConfigurationKeyName(ConnectionStringKey)]
    public string? ConnectionString { get; set; }

    public bool IsAzure => string.Equals(Provider?.Trim(), AzureProvider, StringComparison.OrdinalIgnoreCase);
}
