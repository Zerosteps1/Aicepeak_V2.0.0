using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace Aicepeak.Api.Data;

/// <summary>
/// Lets <c>dotnet ef migrations add --context TenantDbContext</c> build the tenant model without a tenant. Tenant
/// databases are never updated with <c>dotnet ef</c>; <see cref="TenantDatabaseMigrator"/> migrates them at runtime.
/// </summary>
public sealed class TenantDbContextDesignTimeFactory : IDesignTimeDbContextFactory<TenantDbContext> {
    public TenantDbContext CreateDbContext(string[] args) =>
        new(new DbContextOptionsBuilder<TenantDbContext>().UseNpgsql().Options);
}
