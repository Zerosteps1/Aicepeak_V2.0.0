using System.Collections.Concurrent;
using System.Data;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Aicepeak.Api.Data;

/// <summary>
/// Creates a tenant's database on first use and applies the tenant migrations, once per tenant and process. Several
/// app instances may do this at the same time: the races PostgreSQL reports (database created or in use by another
/// session, catalog unique violation) are retried, and the migrations themselves run under an advisory lock. Any other
/// failure, such as a unique violation on tenant data, is thrown at once.
/// </summary>
public sealed class TenantDatabaseMigrator(TenantDbContextFactory databases, ILogger<TenantDatabaseMigrator> logger) {
    internal const int MaxRetries = 3;

    /// <summary>The advisory lock key of migrating a tenant database (advisory locks are per database).</summary>
    private const long MigrationLock = 0x5465_6E61_6E74_4D67; // "TenantMg"

    private static readonly TimeSpan RetryDelay = TimeSpan.FromMilliseconds(200);

    private readonly ConcurrentDictionary<Guid, SemaphoreSlim> _gates = new();
    private readonly ConcurrentDictionary<Guid, bool> _migrated = new();

    public async Task EnsureMigratedAsync(Guid tid, CancellationToken cancellationToken) {
        if (_migrated.ContainsKey(tid)) {
            return;
        }

        var gate = _gates.GetOrAdd(tid, _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken);
        try {
            if (_migrated.ContainsKey(tid)) {
                return;
            }

            for (var retry = 0; ; retry++) {
                try {
                    await CreateAndMigrateAsync(tid, cancellationToken);
                    break;
                } catch (Exception exception) when (retry < MaxRetries && IsRetryable(exception)) {
                    logger.LogInformation("Migrating the database of tenant {Tid} raced with another session; retrying.", tid);
                    await Task.Delay(RetryDelay * (retry + 1), cancellationToken);
                }
            }

            _migrated[tid] = true;
        } finally {
            gate.Release();
        }
    }

    private async Task CreateAndMigrateAsync(Guid tid, CancellationToken cancellationToken) {
        var name = TenantDbContextFactory.DatabaseName(tid);
        await using (var connection = new NpgsqlConnection(databases.MainConnectionString())) {
            await connection.OpenAsync(cancellationToken);
            await using var exists = new NpgsqlCommand("SELECT 1 FROM pg_database WHERE datname = $1", connection) {
                Parameters = { new() { Value = name } },
            };
            if (await exists.ExecuteScalarAsync(cancellationToken) is null) {
                // The name is a formatted GUID (hex digits and hyphens), so quoting it is enough.
                await using var create = new NpgsqlCommand($"CREATE DATABASE \"{name}\"", connection);
                await create.ExecuteNonQueryAsync(cancellationToken);
                logger.LogInformation("Created the database of tenant {Tid}.", tid);
            }
        }

        // EF Core locks the history table only for each migration's transaction, but reads the applied migrations once:
        // two instances could both apply a later migration. A session advisory lock serializes the whole run instead.
        await using var db = databases.Create(tid);
        await db.Database.OpenConnectionAsync(cancellationToken);
        await db.Database.ExecuteSqlAsync($"SELECT pg_advisory_lock({MigrationLock})", cancellationToken);
        try {
            await db.Database.MigrateAsync(cancellationToken);
        } finally {
            // The pooled connection outlives the context, and with it the lock; a broken connection has lost it already.
            if (db.Database.GetDbConnection().State == ConnectionState.Open) {
                await db.Database.ExecuteSqlAsync($"SELECT pg_advisory_unlock({MigrationLock})", CancellationToken.None);
            }
        }
    }

    internal static bool IsRetryable(Exception exception) {
        for (var current = exception; current is not null; current = current.InnerException) {
            if (current is PostgresException postgres && IsRace(postgres)) {
                return true;
            }
        }

        return false;
    }

    /// <summary>
    /// A race with another session: the database already created or in use, or a unique violation in the system catalog
    /// (two sessions creating the same object). A unique violation on a tenant table is a fact about its data, no race.
    /// </summary>
    private static bool IsRace(PostgresException postgres) => postgres.SqlState switch {
        PostgresErrorCodes.DuplicateDatabase or PostgresErrorCodes.ObjectInUse => true,
        PostgresErrorCodes.UniqueViolation => postgres.SchemaName == "pg_catalog",
        _ => false,
    };
}
