using Testcontainers.Azurite;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>
/// A throwaway Azurite (Azure Storage emulator) container, in memory. <c>--skipApiVersionCheck</c> lets the current
/// Azure SDK talk to it. Its connection string is used as is, never parsed. Requires Docker.
/// </summary>
public sealed class AzuriteFixture : IAsyncLifetime {
    private readonly AzuriteContainer _container = new AzuriteBuilder("mcr.microsoft.com/azure-storage/azurite:3.38.0")
        .WithInMemoryPersistence()
        .WithCommand("--skipApiVersionCheck")
        .Build();

    public string ConnectionString => _container.GetConnectionString();

    public ValueTask InitializeAsync() => new(_container.StartAsync());

    public ValueTask DisposeAsync() => _container.DisposeAsync();
}

/// <summary>Tests that need PostgreSQL and blob storage; this collection has its own containers.</summary>
[CollectionDefinition(Name)]
public sealed class StorageCollection : ICollectionFixture<PostgresFixture>, ICollectionFixture<AzuriteFixture> {
    public const string Name = "Storage";
}
