using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Metadata;

namespace Aicepeak.Api.Tests.Data;

/// <summary>AC-6: the EF model and its migrations, without a database.</summary>
public sealed class UserModelTests : IDisposable
{
    private readonly AppDbContext _db = new(
        new DbContextOptionsBuilder<AppDbContext>().UseNpgsql("Host=localhost").Options);

    public void Dispose() => _db.Dispose();

    [Fact]
    public void User_HasStringPrimaryKeyEntraId_AndRequiredName()
    {
        var user = _db.GetService<IDesignTimeModel>().Model.FindEntityType(typeof(User));

        Assert.NotNull(user);
        var key = Assert.Single(user.FindPrimaryKey()!.Properties);
        Assert.Equal(nameof(User.EntraId), key.Name);
        Assert.Equal(typeof(string), key.ClrType);
        Assert.Equal(ValueGenerated.Never, key.ValueGenerated);
        var name = user.FindProperty(nameof(User.Name));
        Assert.NotNull(name);
        Assert.False(name.IsNullable);
        Assert.Equal("Users", user.GetTableName());
    }

    [Fact]
    public void Migrations_ContainInitialCreate()
    {
        Assert.Contains(_db.Database.GetMigrations(), migration => migration.EndsWith("_InitialCreate", StringComparison.Ordinal));
    }

    [Fact]
    public void Model_HasNoChangesMissingFromMigrations()
    {
        Assert.False(_db.Database.HasPendingModelChanges());
    }
}
