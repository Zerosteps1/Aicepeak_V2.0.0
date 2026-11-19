using Aicepeak.Api.Data.Configurations;
using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;

namespace Aicepeak.Api.Data;

/// <summary>
/// A tenant's own database, named exactly like its tenant ID (<see cref="TenantDbContextFactory.DatabaseName"/>):
/// projects, documents and their links. Created and migrated lazily by <see cref="TenantDatabaseMigrator"/>.
/// </summary>
public sealed class TenantDbContext(DbContextOptions<TenantDbContext> options) : DbContext(options) {
    public DbSet<Project> Projects => Set<Project>();

    public DbSet<Document> Documents => Set<Document>();

    public DbSet<ProjectDocument> ProjectDocuments => Set<ProjectDocument>();

    /// <summary>The documents linked to a project, oldest first.</summary>
    public IQueryable<Document> DocumentsOf(Guid projectId) =>
        Documents
            .Where(document => ProjectDocuments.Any(link => link.ProjectId == projectId && link.DocumentId == document.Id))
            .OrderBy(document => document.CreatedAt)
            .ThenBy(document => document.Id);

    protected override void OnModelCreating(ModelBuilder modelBuilder) {
        modelBuilder.ApplyConfiguration(new ProjectConfiguration());
        modelBuilder.ApplyConfiguration(new DocumentConfiguration());
        modelBuilder.ApplyConfiguration(new ProjectDocumentConfiguration());
    }
}
