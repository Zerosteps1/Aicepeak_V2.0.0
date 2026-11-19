using System.Security.Claims;
using Aicepeak.Api.Auth;
using Aicepeak.Api.Configuration;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Data;

/// <summary>Creates the <see cref="TenantDbContext"/> of a tenant from the <c>DB_*</c> settings.</summary>
public sealed class TenantDbContextFactory(IOptions<DatabaseOptions> options) {
    /// <summary>The database name of a tenant: its tenant ID, lower case with hyphens.</summary>
    public static string DatabaseName(Guid tid) => tid.ToString("D");

    /// <summary>A context for the tenant's database. Throws <see cref="OptionsValidationException"/> for invalid settings.</summary>
    public TenantDbContext Create(Guid tid) =>
        new(new DbContextOptionsBuilder<TenantDbContext>().UseNpgsql(ConnectionString(DatabaseName(tid))).Options);

    /// <summary>The main database (<c>DB_CON_STR</c>), where tenant databases are created.</summary>
    internal string MainConnectionString() => ConnectionString(database: null);

    /// <summary>
    /// The context of the caller's tenant, or one without a connection string when the caller has no tenant or the
    /// settings are invalid; using that one fails, creating it never does.
    /// </summary>
    internal TenantDbContext CreateForCaller(ClaimsPrincipal? principal) {
        if (principal is not null && EntraAuthentication.TryGetTenantId(principal, out var tid)) {
            try {
                return Create(tid);
            } catch (OptionsValidationException) {
                // Reported by the health endpoint.
            }
        }

        return new TenantDbContext(new DbContextOptionsBuilder<TenantDbContext>().UseNpgsql().Options);
    }

    private string ConnectionString(string? database) =>
        DataServiceCollectionExtensions.BuildConnectionString(options.Value, database)
        ?? throw new InvalidOperationException($"{DatabaseOptions.ConnectionStringKey} is not a valid PostgreSQL connection string.");
}
