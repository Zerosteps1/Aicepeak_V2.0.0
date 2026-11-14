using System.Collections.Concurrent;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>
/// Hosts the API in memory with a given environment and configuration.
/// The settings take precedence over appsettings, .env and real environment variables.
/// The JWT bearer metadata backchannel is always <see cref="Oidc"/>, so no test ever contacts Microsoft.
/// </summary>
public sealed class ApiFactory(
    string environment,
    IReadOnlyDictionary<string, string?> settings,
    string? contentRoot = null,
    Action<IServiceCollection>? configureServices = null) : WebApplicationFactory<Program> {
    public StubOidcHandler Oidc { get; } = new();

    /// <summary>
    /// Why the API rejected bearer tokens, one entry per rejected request: the token validation exception, or the
    /// <see cref="Microsoft.AspNetCore.Authentication.AuthenticationFailureException"/> of a failed claim check.
    /// </summary>
    public ConcurrentQueue<Exception> AuthenticationFailures { get; } = new();

    protected override void ConfigureWebHost(IWebHostBuilder builder) {
        builder.UseEnvironment(environment);

        if (contentRoot is not null) {
            builder.UseContentRoot(contentRoot);
        }

        builder.ConfigureAppConfiguration((_, configuration) => configuration.AddInMemoryCollection(settings));

        builder.ConfigureTestServices(services => {
            // Test-only endpoints, e.g. ThrowingTestController.
            services.AddControllers().AddApplicationPart(typeof(ApiFactory).Assembly);
            // Runs before JwtBearer's post-configuration, which creates the metadata client from this handler.
            services.Configure<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme, options => options.BackchannelHttpHandler = Oidc);
            services.PostConfigure<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme, RecordFailures);
            configureServices?.Invoke(services);
        });
    }

    private void RecordFailures(JwtBearerOptions options) {
        var onAuthenticationFailed = options.Events.OnAuthenticationFailed;
        options.Events.OnAuthenticationFailed = context => {
            AuthenticationFailures.Enqueue(context.Exception);
            return onAuthenticationFailed(context);
        };

        var onTokenValidated = options.Events.OnTokenValidated;
        options.Events.OnTokenValidated = async context => {
            await onTokenValidated(context);
            if (context.Result?.Failure is { } failure) {
                AuthenticationFailures.Enqueue(failure);
            }
        };
    }
}
