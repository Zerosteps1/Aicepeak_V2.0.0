namespace Aicepeak.Api.Configuration;

/// <summary>
/// Database settings, read from the environment variables <c>DB_CON_STR</c>, <c>DB_USR</c> and <c>DB_PWD</c>.
/// </summary>
public sealed class DatabaseOptions
{
    [ConfigurationKeyName("DB_CON_STR")]
    public string? ConnectionString { get; set; }

    [ConfigurationKeyName("DB_USR")]
    public string? Username { get; set; }

    [ConfigurationKeyName("DB_PWD")]
    public string? Password { get; set; }
}
