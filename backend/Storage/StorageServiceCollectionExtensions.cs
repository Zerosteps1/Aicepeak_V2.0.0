using Aicepeak.Api.Configuration;
using Aicepeak.Api.Storage.Azure;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Aicepeak.Api.Storage;

public static class StorageServiceCollectionExtensions {
    /// <summary>
    /// Registers <see cref="IBlobStorage"/> for <c>BLOB_PROVIDER</c> (only <c>azure</c> today) with <c>BLOB_CON_STR</c>,
    /// <see cref="DocumentBlobs"/> and the weekly <see cref="OrphanBlobCleanupService"/>. Invalid settings fail the
    /// <see cref="BlobStorageOptions"/> validation, which the health endpoint reports; they never prevent the start.
    /// </summary>
    public static IServiceCollection AddBlobStorage(this IServiceCollection services, IConfiguration configuration) {
        // Validation messages name the setting but never contain its value.
        services.AddOptions<BlobStorageOptions>()
            .Bind(configuration)
            .Validate(options => !string.IsNullOrWhiteSpace(options.Provider), $"{BlobStorageOptions.ProviderKey} is missing.")
            .Validate(
                options => string.IsNullOrWhiteSpace(options.Provider) || options.IsAzure,
                $"{BlobStorageOptions.ProviderKey} is not a supported provider (supported: {BlobStorageOptions.AzureProvider}).")
            .Validate(options => !string.IsNullOrWhiteSpace(options.ConnectionString), $"{BlobStorageOptions.ConnectionStringKey} is missing.")
            .Validate(
                options => !options.IsAzure
                    || string.IsNullOrWhiteSpace(options.ConnectionString)
                    || AzureBlobStorage.CanSignUploadUrls(options.ConnectionString),
                $"{BlobStorageOptions.ConnectionStringKey} is not an Azure Storage connection string with a shared key, which upload URLs need.");

        // The adapter of BLOB_PROVIDER. Azure is the only one; any other value fails the validation above when used.
        services.AddSingleton<IBlobStorage, AzureBlobStorage>();
        services.AddSingleton<DocumentBlobs>();
        services.TryAddSingleton(TimeProvider.System);
        services.TryAddKeyedSingleton(DocumentBlobs.TimeProviderKey, TimeProvider.System);
        services.AddHostedService<OrphanBlobCleanupService>();

        return services;
    }
}
