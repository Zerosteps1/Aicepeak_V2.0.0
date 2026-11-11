using Npgsql;

namespace Aicepeak.Api.Configuration;

/// <summary>Result of composing the connection string. <see cref="Problem"/> never contains configuration values.</summary>
public sealed record DatabaseConnectionStringResult(string? ConnectionString, string? Problem, Exception? Error)
{
    public bool IsValid => ConnectionString is not null;
}

public static class DatabaseConnectionString
{
    /// <summary>
    /// Builds the Npgsql connection string from <see cref="DatabaseOptions"/>.
    /// <c>DB_USR</c> and <c>DB_PWD</c> override credentials inside <c>DB_CON_STR</c>. Never throws.
    /// </summary>
    public static DatabaseConnectionStringResult Create(DatabaseOptions options)
    {
        var missing = new List<string>();
        if (string.IsNullOrWhiteSpace(options.ConnectionString))
        {
            missing.Add(DatabaseOptions.ConnectionStringKey);
        }

        if (string.IsNullOrWhiteSpace(options.Username))
        {
            missing.Add(DatabaseOptions.UsernameKey);
        }

        if (string.IsNullOrWhiteSpace(options.Password))
        {
            missing.Add(DatabaseOptions.PasswordKey);
        }

        if (missing.Count > 0)
        {
            return Invalid($"Missing setting: {string.Join(", ", missing)}.");
        }

        try
        {
            var builder = new NpgsqlConnectionStringBuilder(options.ConnectionString)
            {
                Username = options.Username,
                Password = options.Password,
            };

            return string.IsNullOrWhiteSpace(builder.Host)
                ? Invalid($"{DatabaseOptions.ConnectionStringKey} has no Host.")
                : new DatabaseConnectionStringResult(builder.ConnectionString, null, null);
        }
        catch (Exception exception) when (exception is ArgumentException or FormatException or InvalidCastException)
        {
            // The exception message may echo parts of the input, so it is only attached, never used as the problem text.
            return Invalid($"{DatabaseOptions.ConnectionStringKey} is not a valid PostgreSQL connection string.", exception);
        }
    }

    private static DatabaseConnectionStringResult Invalid(string problem, Exception? error = null) => new(null, problem, error);
}
