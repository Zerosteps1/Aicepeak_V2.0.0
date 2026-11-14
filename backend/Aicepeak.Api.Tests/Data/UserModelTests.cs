using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Metadata;

namespace Aicepeak.Api.Tests.Data;

/// <summary>AC-19 and AC-21: the EF model and its migrations, without a database.</summary>
public sealed class UserModelTests : IDisposable {
    private readonly AppDbContext _db = new(
        new DbContextOptionsBuilder<AppDbContext>().UseNpgsql("Host=localhost").Options);

    public void Dispose() => _db.Dispose();

    [Fact]
    public void AC19_User_HasCompositePrimaryKeyTidAndOid_AndRequiredName() {
        var user = Model.FindEntityType(typeof(User));

        Assert.NotNull(user);
        var key = user.FindPrimaryKey()!.Properties;
        Assert.Equal([nameof(User.Tid), nameof(User.Oid)], key.Select(property => property.Name));
        Assert.All(key, property => {
            Assert.Equal(typeof(Guid), property.ClrType);
            Assert.Equal(ValueGenerated.Never, property.ValueGenerated);
        });
        var name = user.FindProperty(nameof(User.Name));
        Assert.NotNull(name);
        Assert.False(name.IsNullable);
        Assert.Equal("Users", user.GetTableName());
    }

    [Fact]
    public void AC21_AllowedTenants_IsKeyedByTid_AndSeededWithTheDefaultTenant() {
        var tenant = Model.FindEntityType(typeof(AllowedTenant));

        Assert.NotNull(tenant);
        Assert.Equal("allowed_tenants", tenant.GetTableName());
        var key = Assert.Single(tenant.FindPrimaryKey()!.Properties);
        Assert.Equal("tid", key.GetColumnName());
        Assert.Equal(ValueGenerated.Never, key.ValueGenerated);
        var seed = Assert.Single(tenant.GetSeedData());
        Assert.Equal(new Guid("db760528-cb7c-455c-bd41-e50a38f6fd62"), seed[nameof(AllowedTenant.Tid)]);
    }

    [Fact]
    public void Migrations_ContainInitialCreate() {
        Assert.Contains(_db.Database.GetMigrations(), migration => migration.EndsWith("_InitialCreate", StringComparison.Ordinal));
    }

    [Fact]
    public void Model_HasNoChangesMissingFromMigrations() {
        Assert.False(_db.Database.HasPendingModelChanges());
    }

    private IModel Model => _db.GetService<IDesignTimeModel>().Model;
}
