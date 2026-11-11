using Aicepeak.Api.Configuration;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Aicepeak.Api.Data;

public static class DataServiceCollectionExtensions {
    /// <summary>
    /// Registers <see cref="AppDbContext"/> on PostgreSQL. The connection string is <c>DB_CON_STR</c> with the credentials
    /// from <c>DB_USR</c> and <c>DB_PWD</c>. Invalid settings fail the <see cref="DatabaseOptions"/> validation, which the
    /// health endpoint reports; they never prevent the app from starting.
    /// </summary>
    public static IServiceCollection AddDatabase(this IServiceCollection services, IConfiguration configuration) {
        // Validation messages name the setting but never contain its value.
        services.AddOptions<DatabaseOptions>()
            .Bind(configuration)
            .Validate(options => !string.IsNullOrWhiteSpace(options.ConnectionString), $"{DatabaseOptions.ConnectionStringKey} is missing.")
            .Validate(options => !string.IsNullOrWhiteSpace(options.Username), $"{DatabaseOptions.UsernameKey} is missing.")
            .Validate(options => !string.IsNullOrWhiteSpace(options.Password), $"{DatabaseOptions.PasswordKey} is missing.")
            .Validate(
                options => string.IsNullOrWhiteSpace(options.ConnectionString) || BuildConnectionString(options) is not null,
                $"{DatabaseOptions.ConnectionStringKey} is not a valid PostgreSQL connection string with a Host.");

        services.AddDbContext<AppDbContext>((serviceProvider, options) => {
            var connectionString = TryGetConnectionString(serviceProvider);
            if (connectionString is null) {
                options.UseNpgsql();
            } else {
                options.UseNpgsql(connectionString);
            }
        });

        return services;
    }

    private static string? TryGetConnectionString(IServiceProvider serviceProvider) {
        try {
            return BuildConnectionString(serviceProvider.GetRequiredService<IOptions<DatabaseOptions>>().Value);
        } catch (OptionsValidationException) {
            return null;
        }
    }

    /// <summary>DB_CON_STR with DB_USR and DB_PWD as credentials, or <c>null</c> if it cannot be parsed or has no Host.</summary>
    private static string? BuildConnectionString(DatabaseOptions options) {
        try {
            var builder = new NpgsqlConnectionStringBuilder(options.ConnectionString) {
                Username = options.Username,
                Password = options.Password,
            };
            return string.IsNullOrWhiteSpace(builder.Host) ? null : builder.ConnectionString;
        } catch (Exception exception) when (exception is ArgumentException or FormatException or InvalidCastException) {
            return null;
        }
    }
}
