using Aicepeak.Api.Configuration;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Aicepeak.Api.Data;

public static class DataServiceCollectionExtensions {
    /// <summary>
    /// Registers <see cref="AppDbContext"/> and the per-tenant <see cref="TenantDbContext"/> on PostgreSQL. The connection
    /// string is <c>DB_CON_STR</c> with the credentials from <c>DB_USR</c> and <c>DB_PWD</c>; a tenant's database is the
    /// same server with the tenant ID as database name. Invalid settings fail the <see cref="DatabaseOptions"/>
    /// validation, which the health endpoint reports; they never prevent the app from starting.
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

        services.AddHttpContextAccessor();
        services.AddSingleton<TenantDbContextFactory>();
        services.AddSingleton<TenantDatabaseMigrator>();
        // The database of the calling user's tenant; requests reach it only through TenantEndpointFilter.
        services.AddScoped(serviceProvider => serviceProvider.GetRequiredService<TenantDbContextFactory>()
            .CreateForCaller(serviceProvider.GetRequiredService<IHttpContextAccessor>().HttpContext?.User));

        return services;
    }

    private static string? TryGetConnectionString(IServiceProvider serviceProvider) {
        try {
            return BuildConnectionString(serviceProvider.GetRequiredService<IOptions<DatabaseOptions>>().Value);
        } catch (OptionsValidationException) {
            return null;
        }
    }

    /// <summary>
    /// DB_CON_STR with DB_USR and DB_PWD as credentials, and <paramref name="database"/> as database if given, or
    /// <c>null</c> if it cannot be parsed or has no Host.
    /// </summary>
    internal static string? BuildConnectionString(DatabaseOptions options, string? database = null) {
        try {
            var builder = new NpgsqlConnectionStringBuilder(options.ConnectionString) {
                Username = options.Username,
                Password = options.Password,
            };
            if (database is not null) {
                builder.Database = database;
            }

            return string.IsNullOrWhiteSpace(builder.Host) ? null : builder.ConnectionString;
        } catch (Exception exception) when (exception is ArgumentException or FormatException or InvalidCastException) {
            return null;
        }
    }
}
