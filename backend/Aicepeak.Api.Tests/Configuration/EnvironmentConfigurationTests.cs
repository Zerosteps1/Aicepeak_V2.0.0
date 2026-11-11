using System.Net;
using Aicepeak.Api.Configuration;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;

namespace Aicepeak.Api.Tests.Configuration;

/// <summary>These tests change process environment variables, so they never run in parallel with others.</summary>
[CollectionDefinition(Name, DisableParallelization = true)]
public sealed class ProcessEnvironmentCollection {
    public const string Name = "ProcessEnvironment";
}

[Collection(ProcessEnvironmentCollection.Name)]
public sealed class EnvironmentConfigurationTests : IDisposable {
    private readonly string _contentRoot = Directory.CreateTempSubdirectory("aicepeak-env-").FullName;

    public void Dispose() => Directory.Delete(_contentRoot, recursive: true);

    [Fact]
    public void DatabaseOptions_BindFromEnvironmentVariables() {
        using var _ = new EnvironmentVariables(("DB_CON_STR", "Host=env"), ("DB_USR", "env-user"), ("DB_PWD", "env-pwd"));

        var options = new ConfigurationBuilder().AddEnvironmentVariables().Build().Get<DatabaseOptions>();

        Assert.NotNull(options);
        Assert.Equal("Host=env", options.ConnectionString);
        Assert.Equal("env-user", options.Username);
        Assert.Equal("env-pwd", options.Password);
    }

    [Fact]
    public void DotEnv_IsReadInDevelopment_AndRealEnvironmentVariablesWin() {
        WriteDotEnv("DB_USR='dotenv-user'", "DB_PWD='dotenv-pwd'");
        using var _ = new EnvironmentVariables(("DB_USR", "env-user"), ("DB_PWD", null));

        var configuration = new ConfigurationManager();
        configuration.AddEnvironmentVariables();
        configuration.AddDotEnvInDevelopment(Environment(TestSettings.Development));

        Assert.Equal("env-user", configuration["DB_USR"]);
        Assert.Equal("dotenv-pwd", configuration["DB_PWD"]);
        Assert.Null(System.Environment.GetEnvironmentVariable("DB_PWD"));
    }

    [Fact]
    public void DotEnv_IsIgnoredOutsideDevelopment() {
        WriteDotEnv("DB_PWD='dotenv-pwd'");
        using var _ = new EnvironmentVariables(("DB_PWD", null));

        var configuration = new ConfigurationManager();
        configuration.AddDotEnvInDevelopment(Environment(TestSettings.Production));

        Assert.Null(configuration["DB_PWD"]);
    }

    [Fact]
    public void DotEnv_MissingFile_IsIgnored() {
        var configuration = new ConfigurationManager();

        configuration.AddDotEnvInDevelopment(Environment(TestSettings.Development));

        Assert.Empty(configuration.AsEnumerable());
    }

    [Theory]
    [InlineData(TestSettings.Development, "Healthy")]
    [InlineData(TestSettings.Production, "Unhealthy")]
    public async Task Api_ReadsDotEnvFromContentRoot_OnlyInDevelopment(string environment, string expectedConfigurationStatus) {
        var unreachable = TestSettings.UnreachableDatabase();
        WriteDotEnv(
            $"DB_CON_STR='{unreachable["DB_CON_STR"]}'",
            $"DB_USR='{unreachable["DB_USR"]}'",
            $"DB_PWD='{unreachable["DB_PWD"]}'");
        using var _ = new EnvironmentVariables(("DB_CON_STR", null), ("DB_USR", null), ("DB_PWD", null));
        await using var factory = new ApiFactory(environment, new Dictionary<string, string?>(), _contentRoot);
        var client = factory.CreateClient();

        var response = await client.GetAsync("/api/v1/health/alive", TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        var health = new HealthResponse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Equal(expectedConfigurationStatus, health.ComponentStatus("configuration"));
        Assert.Equal("Unhealthy", health.ComponentStatus("database"));
    }

    private void WriteDotEnv(params string[] lines) =>
        File.WriteAllLines(Path.Combine(_contentRoot, ".env"), lines);

    private TestHostEnvironment Environment(string name) => new() {
        EnvironmentName = name,
        ContentRootPath = _contentRoot,
        ContentRootFileProvider = new PhysicalFileProvider(_contentRoot),
    };

    private sealed class TestHostEnvironment : IHostEnvironment {
        public required string EnvironmentName { get; set; }
        public string ApplicationName { get; set; } = "Aicepeak.Api";
        public required string ContentRootPath { get; set; }
        public required IFileProvider ContentRootFileProvider { get; set; }
    }

    /// <summary>Sets process environment variables and restores the previous values on dispose.</summary>
    private sealed class EnvironmentVariables : IDisposable {
        private readonly Dictionary<string, string?> _previous = [];

        public EnvironmentVariables(params (string Name, string? Value)[] variables) {
            foreach (var (name, value) in variables) {
                _previous[name] = System.Environment.GetEnvironmentVariable(name);
                System.Environment.SetEnvironmentVariable(name, value);
            }
        }

        public void Dispose() {
            foreach (var (name, value) in _previous) {
                System.Environment.SetEnvironmentVariable(name, value);
            }
        }
    }
}
