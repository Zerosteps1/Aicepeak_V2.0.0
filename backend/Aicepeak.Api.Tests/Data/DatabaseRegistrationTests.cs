using Aicepeak.Api.Configuration;
using Aicepeak.Api.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Aicepeak.Api.Tests.Data;

/// <summary>AC-2/AC-4: <see cref="DataServiceCollectionExtensions.AddDatabase"/> validates the settings and builds the connection.</summary>
public sealed class DatabaseRegistrationTests {
    private const string Password = "p;w=d'x\"$y";

    [Fact]
    public void AddDatabase_ComposesConnectionStringFromAllThreeValues() {
        using var services = Services("Host=db.example;Port=5433;Database=aicepeak", "app", Password);

        var builder = new NpgsqlConnectionStringBuilder(ConnectionString(services));

        Assert.Equal("db.example", builder.Host);
        Assert.Equal(5433, builder.Port);
        Assert.Equal("aicepeak", builder.Database);
        Assert.Equal("app", builder.Username);
        Assert.Equal(Password, builder.Password);
    }

    [Fact]
    public void AddDatabase_UserAndPasswordOverrideCredentialsInConnectionString() {
        using var services = Services("Host=db;Username=other;Password=other", "app", Password);

        var builder = new NpgsqlConnectionStringBuilder(ConnectionString(services));

        Assert.Equal("app", builder.Username);
        Assert.Equal(Password, builder.Password);
    }

    [Theory]
    [InlineData("DB_CON_STR")]
    [InlineData("DB_USR")]
    [InlineData("DB_PWD")]
    public void AddDatabase_MissingValue_FailsValidationNamingTheKeyWithoutValues(string missingKey) {
        using var services = Services(
            missingKey == "DB_CON_STR" ? " " : "Host=secret-host",
            missingKey == "DB_USR" ? "" : "secret-user",
            missingKey == "DB_PWD" ? null : "secret-password");

        var failures = ValidationFailures(services);

        Assert.Contains(missingKey, failures);
        Assert.DoesNotContain("secret", failures);
    }

    [Theory]
    [InlineData("Unknown=secret")]
    [InlineData("Host=x;Port=secret")]
    [InlineData("secret")]
    [InlineData("Database=secret")]
    public void AddDatabase_InvalidConnectionString_FailsValidationWithoutEchoingInput(string conStr) {
        using var services = Services(conStr, "app", "pwd");

        var failures = ValidationFailures(services);

        Assert.Contains("DB_CON_STR", failures);
        Assert.DoesNotContain("secret", failures);
    }

    [Fact]
    public void AddDatabase_InvalidSettings_DbContextCanStillBeCreated() {
        using var services = Services("", "", "");
        using var scope = services.CreateScope();

        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();

        Assert.Null(db.Database.GetConnectionString());
    }

    private static ServiceProvider Services(string? conStr, string? user, string? password) {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> {
                ["DB_CON_STR"] = conStr,
                ["DB_USR"] = user,
                ["DB_PWD"] = password,
            })
            .Build();

        return new ServiceCollection().AddDatabase(configuration).BuildServiceProvider();
    }

    private static string? ConnectionString(ServiceProvider services) {
        using var scope = services.CreateScope();
        return scope.ServiceProvider.GetRequiredService<AppDbContext>().Database.GetConnectionString();
    }

    private static string ValidationFailures(ServiceProvider services) {
        var exception = Assert.Throws<OptionsValidationException>(
            () => services.GetRequiredService<IOptions<DatabaseOptions>>().Value);
        return string.Join(" ", exception.Failures);
    }
}
