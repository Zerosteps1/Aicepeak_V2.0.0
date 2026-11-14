using Npgsql;
using Testcontainers.PostgreSql;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>A throwaway PostgreSQL container shared by the tests in <see cref="PostgresCollection"/>. Requires Docker.</summary>
public sealed class PostgresFixture : IAsyncLifetime {
    private readonly PostgreSqlContainer _container = new PostgreSqlBuilder("postgres:17").Build();

    public string ConnectionStringWithoutCredentials { get; private set; } = "";

    public string Username { get; private set; } = "";

    public string Password { get; private set; } = "";

    public async ValueTask InitializeAsync() {
        await _container.StartAsync();

        var builder = new NpgsqlConnectionStringBuilder(_container.GetConnectionString());
        Username = builder.Username!;
        Password = builder.Password!;
        builder.Username = null;
        builder.Password = null;
        ConnectionStringWithoutCredentials = builder.ConnectionString;
    }

    public ValueTask DisposeAsync() => _container.DisposeAsync();

    public Task StopAsync() => _container.StopAsync();

    /// <summary>A connection string with credentials for <paramref name="database"/> in this container.</summary>
    public string ConnectionString(string database) => new NpgsqlConnectionStringBuilder(ConnectionStringWithoutCredentials) {
        Database = database,
        Username = Username,
        Password = Password,
    }.ConnectionString;

    public Dictionary<string, string?> Settings(string? database = null, string? password = null) {
        var builder = new NpgsqlConnectionStringBuilder(ConnectionStringWithoutCredentials);
        if (database is not null) {
            builder.Database = database;
        }

        return TestSettings.Database(builder.ConnectionString, Username, password ?? Password);
    }
}

[CollectionDefinition(Name)]
public sealed class PostgresCollection : ICollectionFixture<PostgresFixture> {
    public const string Name = "Postgres";
}
