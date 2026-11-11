using System.Net;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.Health;

/// <summary>AC-3 and AC-4 against a real PostgreSQL (Docker).</summary>
[Collection(PostgresCollection.Name)]
[Trait("Category", "Database")]
public sealed class HealthAliveDatabaseTests(PostgresFixture postgres)
{
    private const string Endpoint = "/api/v1/health/alive";

    [Theory]
    [InlineData(TestSettings.Development)]
    [InlineData(TestSettings.Production)]
    public async Task ReachableDatabase_Returns204WithEmptyBody(string environment)
    {
        await using var factory = new ApiFactory(environment, postgres.Settings());

        var response = await factory.CreateClient().GetAsync(Endpoint, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        Assert.Empty(await response.Content.ReadAsByteArrayAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task WrongPassword_Returns503NamingDatabase_WithoutPasswordInProduction()
    {
        const string wrongPassword = "wrong-pwd-marker-5d1e";
        await using var factory = new ApiFactory(TestSettings.Production, postgres.Settings(password: wrongPassword));

        var response = await factory.CreateClient().GetAsync(Endpoint, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        var health = new HealthResponse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Equal("Healthy", health.ComponentStatus("configuration"));
        Assert.Equal("Unhealthy", health.ComponentStatus("database"));
        Assert.DoesNotContain(wrongPassword, health.Body);
        Assert.DoesNotContain(postgres.Password, health.Body);
    }
}
