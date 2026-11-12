namespace Aicepeak.Api.Configuration;

/// <summary>
/// Database settings under the configuration keys <c>DB_CON_STR</c>, <c>DB_USR</c> and <c>DB_PWD</c>: environment variables,
/// in Development also <c>.env</c>. Validated in <c>AddDatabase</c>.
/// </summary>
public sealed class DatabaseOptions {
    public const string ConnectionStringKey = "DB_CON_STR";
    public const string UsernameKey = "DB_USR";
    public const string PasswordKey = "DB_PWD";

    /// <summary>Npgsql connection string without credentials, e.g. <c>Host=localhost;Port=5432;Database=aicepeak</c>.</summary>
    [ConfigurationKeyName(ConnectionStringKey)]
    public string? ConnectionString { get; set; }

    [ConfigurationKeyName(UsernameKey)]
    public string? Username { get; set; }

    [ConfigurationKeyName(PasswordKey)]
    public string? Password { get; set; }
}
