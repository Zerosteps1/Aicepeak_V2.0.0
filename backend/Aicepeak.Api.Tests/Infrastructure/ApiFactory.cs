using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>
/// Hosts the API in memory with a given environment and configuration.
/// The settings take precedence over appsettings, .env and real environment variables.
/// </summary>
public sealed class ApiFactory(
    string environment,
    IReadOnlyDictionary<string, string?> settings,
    string? contentRoot = null) : WebApplicationFactory<Program> {
    protected override void ConfigureWebHost(IWebHostBuilder builder) {
        builder.UseEnvironment(environment);

        if (contentRoot is not null) {
            builder.UseContentRoot(contentRoot);
        }

        builder.ConfigureAppConfiguration((_, configuration) => configuration.AddInMemoryCollection(settings));

        // Test-only endpoints, e.g. ThrowingTestController.
        builder.ConfigureTestServices(services =>
            services.AddControllers().AddApplicationPart(typeof(ApiFactory).Assembly));
    }
}
