using Aicepeak.Api.Data;
using Npgsql;

namespace Aicepeak.Api.Tests.Data;

/// <summary>
/// AC-12 without a database: <see cref="TenantDatabaseMigrator"/> retries only the races PostgreSQL reports when several
/// instances migrate the same tenant, never a failure that would come back, such as a unique violation on tenant data.
/// </summary>
public sealed class TenantDatabaseMigratorTests {
    [Theory]
    [InlineData(PostgresErrorCodes.DuplicateDatabase, null, true)]
    [InlineData(PostgresErrorCodes.ObjectInUse, null, true)]
    // Two sessions creating the same database or table collide in a system catalog index.
    [InlineData(PostgresErrorCodes.UniqueViolation, "pg_catalog", true)]
    // E.g. a unique index that cannot be built over existing tenant data.
    [InlineData(PostgresErrorCodes.UniqueViolation, "public", false)]
    [InlineData(PostgresErrorCodes.UniqueViolation, null, false)]
    [InlineData(PostgresErrorCodes.RaiseException, null, false)]
    [InlineData(PostgresErrorCodes.UndefinedTable, "public", false)]
    public void AC12_OnlyRacesAreRetried_AlsoWhenWrapped(string sqlState, string? schema, bool retried) {
        var postgres = new PostgresException("failed", "ERROR", "ERROR", sqlState, schemaName: schema);

        Assert.Equal(retried, TenantDatabaseMigrator.IsRetryable(postgres));
        Assert.Equal(retried, TenantDatabaseMigrator.IsRetryable(new InvalidOperationException("An EF Core failure.", postgres)));
    }

    [Fact]
    public void AC12_OtherExceptions_AreNotRetried() => Assert.False(TenantDatabaseMigrator.IsRetryable(new TimeoutException()));
}
