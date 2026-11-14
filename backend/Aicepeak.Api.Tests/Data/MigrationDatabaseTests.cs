using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;

namespace Aicepeak.Api.Tests.Data;

/// <summary>AC-19 and AC-21 against a real PostgreSQL (Docker): migrations apply and map <see cref="User"/>.</summary>
[Collection(PostgresCollection.Name)]
[Trait("Category", "Database")]
public sealed class MigrationDatabaseTests(PostgresFixture postgres) {
    [Fact]
    public async Task AC19_Migrate_CreatesUsersTable_AndUserRoundTripsByTidAndOid() {
        var ct = TestContext.Current.CancellationToken;
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(postgres.Settings(database: "migration_test"))
            .Build();
        await using var services = new ServiceCollection().AddDatabase(configuration).BuildServiceProvider();
        var options = services.GetRequiredService<DbContextOptions<AppDbContext>>();
        var (tid, oid) = (Guid.NewGuid(), Guid.NewGuid());

        await using (var db = new AppDbContext(options)) {
            await db.Database.MigrateAsync(ct);
            db.Users.Add(new User { Tid = tid, Oid = oid, Name = "Ada" });
            await db.SaveChangesAsync(ct);
        }

        await using (var db = new AppDbContext(options)) {
            var user = await db.Users.SingleAsync(u => u.Tid == tid && u.Oid == oid, ct);
            Assert.Equal("Ada", user.Name);
        }
    }

    [Fact]
    public async Task AC19_Migrate_UsersKey_RejectsSameTidAndOid_AllowsSameOidInAnotherTenant() {
        var ct = TestContext.Current.CancellationToken;
        var options = await MigratedAsync("migration_test");
        var (tid, oid) = (Guid.NewGuid(), Guid.NewGuid());
        await using (var db = new AppDbContext(options)) {
            db.Users.Add(new User { Tid = tid, Oid = oid, Name = "Ada" });
            db.Users.Add(new User { Tid = Guid.NewGuid(), Oid = oid, Name = "Ada elsewhere" });
            await db.SaveChangesAsync(ct);
        }

        await using (var db = new AppDbContext(options)) {
            db.Users.Add(new User { Tid = tid, Oid = oid, Name = "Ada again" });

            var exception = await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync(ct));
            Assert.Equal(PostgresErrorCodes.UniqueViolation, Assert.IsType<PostgresException>(exception.InnerException).SqlState);
        }
    }

    [Fact]
    public async Task AC21_Migrate_CreatesAllowedTenants_SeededWithTheDefaultTenant() {
        var options = await MigratedAsync("migration_test");

        await using var db = new AppDbContext(options);

        var tenant = Assert.Single(await db.AllowedTenants.ToListAsync(TestContext.Current.CancellationToken));
        Assert.Equal(new Guid("db760528-cb7c-455c-bd41-e50a38f6fd62"), tenant.Tid);
    }

    [Fact]
    public async Task AC21_MigrateDown_ToInitialCreate_DropsAllowedTenants_AndRestoresTheOldUsersTable() {
        var ct = TestContext.Current.CancellationToken;
        var options = await MigratedAsync("migration_down_test");

        await using var db = new AppDbContext(options);
        await db.GetService<IMigrator>().MigrateAsync("20261111080133_InitialCreate", ct);

        Assert.Equal(["EntraId", "Name"], await ColumnsAsync(db, "Users"));
        Assert.Empty(await ColumnsAsync(db, "allowed_tenants"));
        await db.Database.MigrateAsync(ct);
        Assert.Equal(["Name", "Oid", "Tid"], await ColumnsAsync(db, "Users"));
    }

    private async Task<DbContextOptions<AppDbContext>> MigratedAsync(string database) {
        var options = new DbContextOptionsBuilder<AppDbContext>().UseNpgsql(postgres.ConnectionString(database)).Options;
        await using var db = new AppDbContext(options);
        await db.Database.MigrateAsync(TestContext.Current.CancellationToken);

        return options;
    }

    private static Task<List<string>> ColumnsAsync(AppDbContext db, string table) =>
        db.Database.SqlQuery<string>(
                $"SELECT column_name AS \"Value\" FROM information_schema.columns WHERE table_name = {table} ORDER BY column_name")
            .ToListAsync(TestContext.Current.CancellationToken);
}
