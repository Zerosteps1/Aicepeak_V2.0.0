using System.Collections.Concurrent;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Aicepeak.Api.Data;

/// <summary>
/// Creates a tenant's database on first use and applies the tenant migrations, once per tenant and process. Several
/// app instances may do this at the same time: the races PostgreSQL reports (database created or in use by another
/// session, catalog unique violation) are retried.
/// </summary>
public sealed class TenantDatabaseMigrator(TenantDbContextFactory databases, ILogger<TenantDatabaseMigrator> logger) {
    internal const int MaxRetries = 3;

    private static readonly TimeSpan RetryDelay = TimeSpan.FromMilliseconds(200);

    private static readonly HashSet<string> RetryableStates = [
        PostgresErrorCodes.DuplicateDatabase,
        PostgresErrorCodes.ObjectInUse,
        PostgresErrorCodes.UniqueViolation,
    ];

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

        await using var db = databases.Create(tid);
        await db.Database.MigrateAsync(cancellationToken);
    }

    private static bool IsRetryable(Exception exception) {
        for (var current = exception; current is not null; current = current.InnerException) {
            if (current is PostgresException postgres && RetryableStates.Contains(postgres.SqlState)) {
                return true;
            }
        }

        return false;
    }
}
