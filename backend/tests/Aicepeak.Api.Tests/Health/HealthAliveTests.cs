using System.Net;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.Health;

/// <summary>AC-4 and AC-5 for <c>GET /api/v1/health/alive</c> without a database.</summary>
public sealed class HealthAliveTests
{
    private const string Endpoint = "/api/v1/health/alive";
    private const string PasswordMarker = "pwd-marker-7f3a";

    [Theory]
    [InlineData(TestSettings.Development)]
    [InlineData(TestSettings.Production)]
    public async Task UnreachableDatabase_Returns503NamingDatabase(string environment)
    {
        var (status, health) = await GetHealth(environment, TestSettings.UnreachableDatabase());

        Assert.Equal(HttpStatusCode.ServiceUnavailable, status);
        Assert.Equal("Healthy", health.ComponentStatus("configuration"));
        Assert.Equal("Unhealthy", health.ComponentStatus("database"));
        Assert.Contains("database", health.Detail);
    }

    [Theory]
    [InlineData("DB_CON_STR")]
    [InlineData("DB_USR")]
    [InlineData("DB_PWD")]
    public async Task MissingConfiguration_AppStartsAndReturns503NamingConfiguration(string missingKey)
    {
        var settings = TestSettings.UnreachableDatabase();
        settings[missingKey] = "";

        var (status, health) = await GetHealth(TestSettings.Production, settings);

        Assert.Equal(HttpStatusCode.ServiceUnavailable, status);
        Assert.Equal("Unhealthy", health.ComponentStatus("configuration"));
        Assert.Contains("configuration", health.Detail);
    }

    [Theory]
    [InlineData("Unknown=value")]
    [InlineData("Host=127.0.0.1;Port=not-a-number")]
    [InlineData("Database=aicepeak")]
    public async Task InvalidConnectionString_Returns503NamingConfiguration(string conStr)
    {
        var (status, health) = await GetHealth(TestSettings.Production, TestSettings.Database(conStr, "postgres", "postgres"));

        Assert.Equal(HttpStatusCode.ServiceUnavailable, status);
        Assert.Equal("Unhealthy", health.ComponentStatus("configuration"));
    }

    [Fact]
    public async Task Production_UnhealthyBody_ContainsNoSecretsOrExceptionDetails()
    {
        var unreachable = TestSettings.UnreachableDatabase(PasswordMarker);
        var invalid = TestSettings.Database($"Host=127.0.0.1;Port={PasswordMarker}", "postgres", PasswordMarker);

        foreach (var settings in new[] { unreachable, invalid })
        {
            var (status, health) = await GetHealth(TestSettings.Production, settings);

            Assert.Equal(HttpStatusCode.ServiceUnavailable, status);
            Assert.DoesNotContain(PasswordMarker, health.Body);
            Assert.DoesNotContain("Exception", health.Body);
            Assert.DoesNotContain("   at ", health.Body);
            Assert.DoesNotContain("Npgsql", health.Body);
            Assert.DoesNotContain("127.0.0.1", health.Body);
            Assert.False(health.HasErrors);
        }
    }

    [Fact]
    public async Task Development_UnhealthyBody_ContainsExceptionTrace()
    {
        var (_, unreachable) = await GetHealth(TestSettings.Development, TestSettings.UnreachableDatabase());
        var (_, invalid) = await GetHealth(TestSettings.Development, TestSettings.Database("Unknown=value", "postgres", "postgres"));

        var databaseException = unreachable.ErrorException("database");
        Assert.NotNull(databaseException);
        Assert.Contains("Exception", databaseException);
        Assert.Contains("   at ", databaseException);
        Assert.Contains("Exception", invalid.ErrorException("configuration"));
    }

    [Fact]
    public async Task Unhealthy_RespondsWithProblemDetails()
    {
        await using var factory = new ApiFactory(TestSettings.Production, TestSettings.UnreachableDatabase());
        var response = await factory.CreateClient().GetAsync(Endpoint, TestContext.Current.CancellationToken);

        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
    }

    private static async Task<(HttpStatusCode Status, HealthResponse Health)> GetHealth(
        string environment, IReadOnlyDictionary<string, string?> settings)
    {
        await using var factory = new ApiFactory(environment, settings);
        var response = await factory.CreateClient().GetAsync(Endpoint, TestContext.Current.CancellationToken);
        var body = await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken);

        return (response.StatusCode, new HealthResponse(body));
    }
}
