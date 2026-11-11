using System.Net;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.Health;

/// <summary>
/// AC-3/AC-4: a database that goes away after a successful check must be reported, even though
/// the connection pool still holds an idle connection to it. Uses its own container (Docker).
/// </summary>
[Trait("Category", "Database")]
public sealed class HealthAliveDatabaseLostTests
{
    private const string Endpoint = "/api/v1/health/alive";

    [Fact]
    public async Task DatabaseStoppedAfterHealthyCheck_Returns503NamingDatabase()
    {
        var ct = TestContext.Current.CancellationToken;
        var postgres = new PostgresFixture();
        await postgres.InitializeAsync();
        try
        {
            await using var factory = new ApiFactory(TestSettings.Production, postgres.Settings());
            var client = factory.CreateClient();
            Assert.Equal(HttpStatusCode.NoContent, (await client.GetAsync(Endpoint, ct)).StatusCode);

            await postgres.StopAsync();
            var response = await client.GetAsync(Endpoint, ct);

            Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
            var health = new HealthResponse(await response.Content.ReadAsStringAsync(ct));
            Assert.Equal("Unhealthy", health.ComponentStatus("database"));
        }
        finally
        {
            await postgres.DisposeAsync();
        }
    }
}
