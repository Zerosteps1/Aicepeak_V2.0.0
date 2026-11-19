using Aicepeak.Api.Data.Configurations;
using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;

namespace Aicepeak.Api.Data;

/// <summary>The main database: users and the tenant allowlist. Tenant data lives in <see cref="TenantDbContext"/>.</summary>
public sealed class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options) {
    public DbSet<User> Users => Set<User>();

    public DbSet<AllowedTenant> AllowedTenants => Set<AllowedTenant>();

    // Explicit, so the tenant entities of the same assembly stay out of this model.
    protected override void OnModelCreating(ModelBuilder modelBuilder) {
        modelBuilder.ApplyConfiguration(new UserConfiguration());
        modelBuilder.ApplyConfiguration(new AllowedTenantConfiguration());
    }
}
