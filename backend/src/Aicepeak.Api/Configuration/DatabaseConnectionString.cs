namespace Aicepeak.Api.Configuration;

/// <summary>Result of composing the connection string. <see cref="Problem"/> never contains configuration values.</summary>
public sealed record DatabaseConnectionStringResult(string? ConnectionString, string? Problem, Exception? Error)
{
    public bool IsValid => ConnectionString is not null;
}

public static class DatabaseConnectionString
{
    public static DatabaseConnectionStringResult Create(DatabaseOptions options) =>
        throw new NotImplementedException();
}
