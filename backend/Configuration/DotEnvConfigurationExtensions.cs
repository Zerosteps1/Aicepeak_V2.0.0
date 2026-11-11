using DotNetEnv;
using DotNetEnv.Extensions;
using Microsoft.Extensions.Configuration.Memory;

namespace Aicepeak.Api.Configuration;

public static class DotEnvConfigurationExtensions {
    private const string FileName = ".env";

    /// <summary>
    /// In Development, adds the values of <c>.env</c> in the content root with the lowest precedence,
    /// so real environment variables always win. The process environment is not changed.
    /// </summary>
    public static IConfigurationBuilder AddDotEnvInDevelopment(this IConfigurationBuilder configuration, IHostEnvironment environment) {
        var path = Path.Combine(environment.ContentRootPath, FileName);
        if (!environment.IsDevelopment() || !File.Exists(path)) {
            return configuration;
        }

        var values = Env.NoEnvVars().Load(path)
            .ToDotEnvDictionary()
            .Select(entry => new KeyValuePair<string, string?>(entry.Key, entry.Value));
        configuration.Sources.Insert(0, new MemoryConfigurationSource { InitialData = values });

        return configuration;
    }
}
