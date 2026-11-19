using System.Runtime.CompilerServices;
using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Metadata;

namespace Aicepeak.Api.Tests.Data;

/// <summary>
/// AC-11 and AC-12: the tenant model (projects, immutable documents, their m-n links), its own migrations, and its
/// separation from the main model, without a database.
/// </summary>
public sealed class TenantModelTests : IDisposable {
    private readonly TenantDbContext _tenant = new(new DbContextOptionsBuilder<TenantDbContext>().UseNpgsql("Host=localhost").Options);
    private readonly AppDbContext _main = new(new DbContextOptionsBuilder<AppDbContext>().UseNpgsql("Host=localhost").Options);

    public void Dispose() {
        _tenant.Dispose();
        _main.Dispose();
    }

    [Fact]
    public void AC12_TenantModel_HasNoChangesMissingFromMigrations() {
        Assert.False(_tenant.Database.HasPendingModelChanges());
    }

    [Fact]
    public void AC12_TenantMigrations_AreSeparateFromTheMainMigrations() {
        var tenantMigrations = _tenant.Database.GetMigrations().ToList();

        Assert.Single(tenantMigrations, migration => migration.EndsWith("_CreateProjectsAndDocuments", StringComparison.Ordinal));
        Assert.Empty(tenantMigrations.Intersect(_main.Database.GetMigrations()));
    }

    [Fact]
    public void AC12_MainModel_HasNoTenantEntities() {
        Assert.Equal(
            [nameof(AllowedTenant), nameof(User)],
            Model(_main).GetEntityTypes().Select(entity => entity.ClrType.Name).Order());
        Assert.Equal(
            [nameof(Document), nameof(Project), nameof(ProjectDocument)],
            Model(_tenant).GetEntityTypes().Select(entity => entity.ClrType.Name).Order());
    }

    [Fact]
    public void AC11_Projects_HaveAGuidKey_AndAUniqueName() {
        var project = Entity<Project>();

        Assert.Equal("projects", project.GetTableName());
        Assert.Equal(ValueGenerated.Never, Assert.Single(project.FindPrimaryKey()!.Properties).ValueGenerated);
        Assert.Equal(
            ["description:character varying(4000)", "end_date:date?", "id:uuid", "name:character varying(200)", "start_date:date"],
            Columns(project));
        Assert.True(Assert.Single(project.GetIndexes()).IsUnique);
    }

    [Fact]
    public void AC11_Documents_AreImmutable_AndBelongToTheUploadingProjectWithoutNavigation() {
        var document = Entity<Document>();

        Assert.Equal("documents", document.GetTableName());
        Assert.Equal(
            ["blob_name:character varying(200)", "content_type:character varying(255)", "created_at:timestamp with time zone", "id:uuid",
                "name:character varying(200)", "project_id:uuid", "sha256:bytea", "size:bigint"],
            Columns(document));
        Assert.Empty(document.GetNavigations());
        Assert.DoesNotContain(typeof(Document).GetProperties(), property => property.PropertyType == typeof(Project));
        Assert.All(typeof(Document).GetProperties(), property => Assert.True(IsInitOnly(property.SetMethod), property.Name));

        var uploader = Assert.Single(document.GetForeignKeys());
        Assert.Equal(typeof(Project), uploader.PrincipalEntityType.ClrType);
        Assert.Equal("project_id", Assert.Single(uploader.Properties).GetColumnName());
        Assert.Equal(DeleteBehavior.Restrict, uploader.DeleteBehavior);

        var indexes = document.GetIndexes().ToDictionary(index => Assert.Single(index.Properties).GetColumnName(), index => index.IsUnique);
        Assert.True(indexes["blob_name"]);
        Assert.False(indexes["sha256"]);
        Assert.Contains(document.GetCheckConstraints(), check => check.Sql == "octet_length(sha256) = 32");
    }

    [Fact]
    public void AC11_ProjectDocuments_LinkProjectsAndDocuments_ManyToMany() {
        var link = Entity<ProjectDocument>();

        Assert.Equal("project_documents", link.GetTableName());
        Assert.Equal(["project_id", "document_id"], link.FindPrimaryKey()!.Properties.Select(property => property.GetColumnName()));
        Assert.Equal(
            [(typeof(Document), DeleteBehavior.Cascade), (typeof(Project), DeleteBehavior.Cascade)],
            link.GetForeignKeys().Select(key => (key.PrincipalEntityType.ClrType, key.DeleteBehavior)).OrderBy(key => key.ClrType.Name));
    }

    private static IModel Model(DbContext db) => db.GetService<IDesignTimeModel>().Model;

    private IEntityType Entity<T>() => Model(_tenant).FindEntityType(typeof(T)) ?? throw new InvalidOperationException(typeof(T).Name);

    private static IEnumerable<string> Columns(IEntityType entity) => entity.GetProperties()
        .Select(property => $"{property.GetColumnName()}:{property.GetColumnType()}{(property.IsNullable ? "?" : "")}")
        .Order();

    private static bool IsInitOnly(System.Reflection.MethodInfo? setter) =>
        setter?.ReturnParameter.GetRequiredCustomModifiers().Contains(typeof(IsExternalInit)) == true;
}
