using Aicepeak.Api.Configuration;
using Npgsql;

namespace Aicepeak.Api.Tests.Configuration;

public sealed class DatabaseConnectionStringTests
{
    private const string Password = "p;w=d'x\"$y";

    [Fact]
    public void Create_ComposesConnectionStringFromAllThreeValues()
    {
        var result = DatabaseConnectionString.Create(Options("Host=db.example;Port=5433;Database=aicepeak", "app", Password));

        Assert.True(result.IsValid);
        Assert.Null(result.Problem);
        var builder = new NpgsqlConnectionStringBuilder(result.ConnectionString);
        Assert.Equal("db.example", builder.Host);
        Assert.Equal(5433, builder.Port);
        Assert.Equal("aicepeak", builder.Database);
        Assert.Equal("app", builder.Username);
        Assert.Equal(Password, builder.Password);
    }

    [Fact]
    public void Create_UserAndPasswordOverrideCredentialsInConnectionString()
    {
        var result = DatabaseConnectionString.Create(Options("Host=db;Username=other;Password=other", "app", Password));

        var builder = new NpgsqlConnectionStringBuilder(result.ConnectionString);
        Assert.Equal("app", builder.Username);
        Assert.Equal(Password, builder.Password);
    }

    [Theory]
    [InlineData("DB_CON_STR")]
    [InlineData("DB_USR")]
    [InlineData("DB_PWD")]
    public void Create_MissingValue_IsInvalidAndNamesTheKeyWithoutValues(string missingKey)
    {
        var options = Options(
            missingKey == "DB_CON_STR" ? " " : "Host=secret-host",
            missingKey == "DB_USR" ? "" : "secret-user",
            missingKey == "DB_PWD" ? null : "secret-password");

        var result = DatabaseConnectionString.Create(options);

        Assert.False(result.IsValid);
        Assert.Null(result.ConnectionString);
        Assert.Contains(missingKey, result.Problem);
        Assert.DoesNotContain("secret", result.Problem);
    }

    [Theory]
    [InlineData("Unknown=secret")]
    [InlineData("Host=x;Port=secret")]
    [InlineData("secret")]
    public void Create_InvalidConnectionString_DoesNotThrowAndDoesNotEchoInput(string conStr)
    {
        var result = DatabaseConnectionString.Create(Options(conStr, "app", "pwd"));

        Assert.False(result.IsValid);
        Assert.Contains("DB_CON_STR", result.Problem);
        Assert.DoesNotContain("secret", result.Problem);
        Assert.NotNull(result.Error);
    }

    [Fact]
    public void Create_ConnectionStringWithoutHost_IsInvalid()
    {
        var result = DatabaseConnectionString.Create(Options("Database=aicepeak", "app", "pwd"));

        Assert.False(result.IsValid);
        Assert.Contains("DB_CON_STR", result.Problem);
    }

    private static DatabaseOptions Options(string? conStr, string? user, string? password) =>
        new() { ConnectionString = conStr, Username = user, Password = password };
}
