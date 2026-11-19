using Aicepeak.Api.Configuration;
using Aicepeak.Api.Storage;
using Aicepeak.Api.Storage.Azure;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Tests.Storage;

/// <summary>
/// AC-9: <see cref="StorageServiceCollectionExtensions.AddBlobStorage"/> validates <c>BLOB_PROVIDER</c> and
/// <c>BLOB_CON_STR</c> lazily, naming the key, never its value.
/// </summary>
public sealed class BlobStorageRegistrationTests {
    [Theory]
    [InlineData("azure")]
    [InlineData(" Azure ")]
    public void AC09_Azure_WithASharedKeyConnectionString_IsValid_AndSelectsTheAzureAdapter(string provider) {
        using var services = Services(provider, "UseDevelopmentStorage=true");

        Assert.NotNull(services.GetRequiredService<IOptions<BlobStorageOptions>>().Value);
        Assert.IsType<AzureBlobStorage>(services.GetRequiredService<IBlobStorage>());
    }

    [Theory]
    [InlineData(null, "BLOB_PROVIDER is missing.")]
    [InlineData(" ", "BLOB_PROVIDER is missing.")]
    [InlineData("secret-aws", "BLOB_PROVIDER is not a supported provider (supported: azure).")]
    public void AC09_MissingOrUnknownProvider_FailsValidation(string? provider, string failure) {
        using var services = Services(provider, "UseDevelopmentStorage=true");

        var failures = ValidationFailures(services);

        Assert.Equal(failure, failures);
        Assert.DoesNotContain("secret", failures);
    }

    [Theory]
    [InlineData(null, "BLOB_CON_STR is missing.")]
    [InlineData("", "BLOB_CON_STR is missing.")]
    [InlineData("secret-garbage", "BLOB_CON_STR is not an Azure Storage connection string with a shared key, which upload URLs need.")]
    [InlineData(
        "BlobEndpoint=https://secret.example/;SharedAccessSignature=sv=2025-01-05&sig=secret",
        "BLOB_CON_STR is not an Azure Storage connection string with a shared key, which upload URLs need.")]
    public void AC09_MissingOrUnusableConnectionString_FailsValidationWithoutEchoingIt(string? connectionString, string failure) {
        using var services = Services("azure", connectionString);

        var failures = ValidationFailures(services);

        Assert.Equal(failure, failures);
        Assert.DoesNotContain("secret", failures);
    }

    [Fact]
    public void AC09_InvalidSettings_StorageCanStillBeCreated_AndFailsOnlyWhenUsed() {
        using var services = Services("", "");

        var storage = services.GetRequiredService<IBlobStorage>();

        Assert.Throws<OptionsValidationException>(() => storage.GetUrl("space", "name"));
    }

    private static ServiceProvider Services(string? provider, string? connectionString) {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> {
                ["BLOB_PROVIDER"] = provider,
                ["BLOB_CON_STR"] = connectionString,
            })
            .Build();

        return new ServiceCollection().AddLogging().AddBlobStorage(configuration).BuildServiceProvider();
    }

    private static string ValidationFailures(ServiceProvider services) {
        var exception = Assert.Throws<OptionsValidationException>(
            () => services.GetRequiredService<IOptions<BlobStorageOptions>>().Value);
        return string.Join(" ", exception.Failures);
    }
}
