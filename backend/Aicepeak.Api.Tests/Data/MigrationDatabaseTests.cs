using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Aicepeak.Api.Tests.Data;

/// <summary>AC-6 against a real PostgreSQL (Docker): migrations apply and map <see cref="User"/>.</summary>
[Collection(PostgresCollection.Name)]
[Trait("Category", "Database")]
public sealed class MigrationDatabaseTests(PostgresFixture postgres)
{
    [Fact]
    public async Task Migrate_CreatesUsersTable_AndUserRoundTrips()
    {
        var ct = TestContext.Current.CancellationToken;
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(postgres.Settings(database: "migration_test"))
            .Build();
        await using var services = new ServiceCollection().AddDatabase(configuration).BuildServiceProvider();
        var options = services.GetRequiredService<DbContextOptions<AppDbContext>>();

        await using (var db = new AppDbContext(options))
        {
            await db.Database.MigrateAsync(ct);
            db.Users.Add(new User { EntraId = "00000000-0000-0000-0000-000000000001", Name = "Ada" });
            await db.SaveChangesAsync(ct);
        }

        await using (var db = new AppDbContext(options))
        {
            var user = await db.Users.SingleAsync(u => u.EntraId == "00000000-0000-0000-0000-000000000001", ct);
            Assert.Equal("Ada", user.Name);
        }
    }
}
