using Aicepeak.Api.Configuration;
using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Data.TenantMigrations;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Aicepeak.Api.Tests.Data;

/// <summary>
/// AC-12 against a real PostgreSQL (Docker): <see cref="TenantDatabaseMigrator"/> creates one database per tenant, named
/// exactly like the tid, with the tenant tables and the trigger that keeps documents immutable; several instances may
/// migrate the same new tenant at once.
/// </summary>
[Collection(PostgresCollection.Name)]
[Trait("Category", "Database")]
public sealed class TenantMigrationDatabaseTests(PostgresFixture postgres) {
    [Fact]
    public async Task AC12_EnsureMigrated_CreatesTheDatabaseNamedExactlyLikeTheTid_WithTheTenantTables() {
        var tid = Guid.NewGuid();

        await Migrator().EnsureMigratedAsync(tid, TestContext.Current.CancellationToken);

        Assert.Equal([tid.ToString("D")], await QueryAsync("postgres", $"SELECT datname FROM pg_database WHERE datname = '{tid}'"));
        Assert.Equal(
            ["__EFMigrationsHistory", "documents", "project_documents", "projects"],
            await QueryAsync(tid.ToString(), "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"));
        Assert.Equal(["documents_immutable"], await QueryAsync(tid.ToString(), "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"));
    }

    [Fact]
    public async Task AC12_Documents_CanBeInsertedAndDeleted_ButNeverUpdated() {
        var ct = TestContext.Current.CancellationToken;
        var tid = Guid.NewGuid();
        await Migrator().EnsureMigratedAsync(tid, ct);
        await using var db = TenantDb(tid);
        var project = new Project { Id = Guid.CreateVersion7(), Name = "P", StartDate = new DateOnly(2026, 1, 1), Description = "" };
        var document = NewDocument(project.Id);
        db.AddRange(project, document, new ProjectDocument { ProjectId = project.Id, DocumentId = document.Id });
        await db.SaveChangesAsync(ct);

        var update = await Assert.ThrowsAsync<PostgresException>(() =>
            db.Database.ExecuteSqlAsync($"UPDATE documents SET name = 'renamed.pdf' WHERE id = {document.Id}", ct));
        Assert.Equal(PostgresErrorCodes.RaiseException, update.SqlState);
        Assert.Equal("documents are immutable", update.MessageText);

        // The uploading project cannot be deleted while it has documents; the link goes with the document.
        var deleteProject = await Assert.ThrowsAsync<PostgresException>(() =>
            db.Database.ExecuteSqlAsync($"DELETE FROM projects WHERE id = {project.Id}", ct));
        Assert.Equal(PostgresErrorCodes.ForeignKeyViolation, deleteProject.SqlState);
        Assert.Equal(1, await db.Database.ExecuteSqlAsync($"DELETE FROM documents WHERE id = {document.Id}", ct));
        Assert.False(await db.ProjectDocuments.AnyAsync(ct));
    }

    [Fact]
    public async Task AC12_Documents_Sha256MustHave32Bytes() {
        var ct = TestContext.Current.CancellationToken;
        var tid = Guid.NewGuid();
        await Migrator().EnsureMigratedAsync(tid, ct);
        await using var db = TenantDb(tid);
        var project = new Project { Id = Guid.CreateVersion7(), Name = "P", StartDate = new DateOnly(2026, 1, 1), Description = "" };
        db.AddRange(project, NewDocument(project.Id, sha256: new byte[31]));

        var exception = await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync(ct));

        Assert.Equal(PostgresErrorCodes.CheckViolation, Assert.IsType<PostgresException>(exception.InnerException).SqlState);
    }

    [Fact]
    public async Task AC12_MigrateDown_DropsTablesAndTrigger_AndUpRestoresThem() {
        var ct = TestContext.Current.CancellationToken;
        var tid = Guid.NewGuid();
        await Migrator().EnsureMigratedAsync(tid, ct);
        await using var db = TenantDb(tid);

        await db.GetService<IMigrator>().MigrateAsync(Migration.InitialDatabase, ct);
        Assert.Equal(["__EFMigrationsHistory"], await QueryAsync(tid.ToString(), "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"));
        Assert.Empty(await QueryAsync(tid.ToString(), "SELECT proname FROM pg_proc WHERE proname = 'documents_reject_update'"));

        await db.Database.MigrateAsync(ct);
        Assert.Equal(["documents_immutable"], await QueryAsync(tid.ToString(), "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"));
    }

    [Fact]
    public async Task AC12_ProjectNamesCaseInsensitive_MigratesDownAndUp_KeepingTheProjects() {
        var ct = TestContext.Current.CancellationToken;
        var tid = Guid.NewGuid();
        await Migrator().EnsureMigratedAsync(tid, ct);
        await using var db = TenantDb(tid);
        db.Projects.Add(new Project { Id = Guid.CreateVersion7(), Name = "Übernahme", StartDate = new DateOnly(2026, 1, 1), Description = "" });
        await db.SaveChangesAsync(ct);
        const string NameIndexes = "SELECT indexname || ':' || indexdef FROM pg_indexes WHERE tablename = 'projects' AND indexname LIKE 'IX_%'";
        const string NormalizedColumn = "SELECT column_name FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'name_normalized'";

        // Down to the migration before: the unique index is on name again, case-sensitive.
        await db.GetService<IMigrator>().MigrateAsync(db.Database.GetMigrations().Single(migration => migration.EndsWith("_CreateProjectsAndDocuments", StringComparison.Ordinal)), ct);
        Assert.Equal(
            ["IX_projects_name:CREATE UNIQUE INDEX \"IX_projects_name\" ON public.projects USING btree (name)"],
            await QueryAsync(tid.ToString(), NameIndexes));
        Assert.Empty(await QueryAsync(tid.ToString(), NormalizedColumn));
        Assert.Equal(["Übernahme"], await QueryAsync(tid.ToString(), "SELECT name FROM projects"));

        // Up again: PostgreSQL fills the column for the existing project, and the index rejects another case.
        await db.Database.MigrateAsync(ct);
        Assert.Equal(
            ["IX_projects_name_normalized:CREATE UNIQUE INDEX \"IX_projects_name_normalized\" ON public.projects USING btree (name_normalized)"],
            await QueryAsync(tid.ToString(), NameIndexes));
        Assert.Equal(["übernahme"], await QueryAsync(tid.ToString(), "SELECT name_normalized FROM projects"));
        var duplicate = await Assert.ThrowsAsync<PostgresException>(() => db.Database.ExecuteSqlAsync(
            $"INSERT INTO projects (id, name, start_date, description) VALUES ({Guid.CreateVersion7()}, 'ÜBERNAHME', DATE '2026-01-01', '')", ct));
        Assert.Equal(PostgresErrorCodes.UniqueViolation, duplicate.SqlState);
        Assert.Equal("IX_projects_name_normalized", duplicate.ConstraintName);
    }

    [Fact]
    public async Task AC12_ProjectNamesCaseInsensitive_OverNamesDifferingOnlyInCase_FailsAtOnce_WithTheProjectIds() {
        var ct = TestContext.Current.CancellationToken;
        var tid = Guid.NewGuid();
        await Migrator().EnsureMigratedAsync(tid, ct);
        await using var db = TenantDb(tid);
        var before = db.Database.GetMigrations().Single(migration => migration.EndsWith("_CreateProjectsAndDocuments", StringComparison.Ordinal));
        await db.GetService<IMigrator>().MigrateAsync(before, ct);
        // Allowed before the migration: names differing only in case, also beyond ASCII.
        var (alpha, alphaLower, takeover, takeoverUpper, other) =
            (Guid.CreateVersion7(), Guid.CreateVersion7(), Guid.CreateVersion7(), Guid.CreateVersion7(), Guid.CreateVersion7());
        foreach (var (id, name) in new[] { (alpha, "Alpha"), (alphaLower, "alpha"), (takeover, "Übernahme"), (takeoverUpper, "ÜBERNAHME"), (other, "Beta") }) {
            await db.Database.ExecuteSqlAsync(
                $"INSERT INTO projects (id, name, start_date, description) VALUES ({id}, {name}, DATE '2026-01-01', '')", ct);
        }

        using var logs = new CapturingLoggerProvider();
        using var loggers = new LoggerFactory([logs]);
        var migrator = Migrator(loggers.CreateLogger<TenantDatabaseMigrator>());

        var failure = await Assert.ThrowsAsync<PostgresException>(() => migrator.EnsureMigratedAsync(tid, ct));

        // A clear error, not taken for a race: no retry. The migration rolled back, the names are unchanged.
        Assert.Equal(PostgresErrorCodes.RaiseException, failure.SqlState);
        var groups = new[] { Group(alpha, alphaLower), Group(takeover, takeoverUpper) }.Order(StringComparer.Ordinal);
        Assert.Equal(ProjectNamesCaseInsensitive.DuplicateNamesMessage + string.Join("; ", groups), failure.MessageText);
        Assert.DoesNotContain(logs.Entries, entry => entry.Message.Contains("raced", StringComparison.Ordinal));
        Assert.Equal(before, (await db.Database.GetAppliedMigrationsAsync(ct)).Last());
        Assert.Equal(
            ["Alpha", "Beta", "alpha", "ÜBERNAHME", "Übernahme"],
            (await QueryAsync(tid.ToString(), "SELECT name FROM projects")).Order(StringComparer.Ordinal));

        // Once the tenant renamed them, the same instance migrates on the next request.
        await db.Database.ExecuteSqlAsync($"UPDATE projects SET name = name || ' 2' WHERE id IN ({alphaLower}, {takeoverUpper})", ct);
        await migrator.EnsureMigratedAsync(tid, ct);
        Assert.Empty(await db.Database.GetPendingMigrationsAsync(ct));
    }

    [Fact]
    public async Task AC12_SeveralInstancesMigratingTheSameNewTenant_AllSucceed() {
        var tid = Guid.NewGuid();
        var instances = Enumerable.Range(0, 6).Select(_ => Migrator()).ToList();

        await Task.WhenAll(instances.SelectMany(instance => new[] {
            instance.EnsureMigratedAsync(tid, TestContext.Current.CancellationToken),
            instance.EnsureMigratedAsync(tid, TestContext.Current.CancellationToken),
        }));

        Assert.Single(await QueryAsync("postgres", $"SELECT datname FROM pg_database WHERE datname = '{tid}'"));
        await using var db = TenantDb(tid);
        Assert.Equal(
            db.Database.GetMigrations(),
            await QueryAsync(tid.ToString(), "SELECT \"MigrationId\" FROM \"__EFMigrationsHistory\" ORDER BY 1"));
        // Each instance migrated under the advisory lock and released it, although its pooled connection stays open.
        Assert.Empty(await QueryAsync(
            "postgres", $"SELECT pid::text FROM pg_locks WHERE locktype = 'advisory' AND database = (SELECT oid FROM pg_database WHERE datname = '{tid}')"));
    }

    [Fact]
    public async Task AC12_TenantsGetSeparateDatabases() {
        var ct = TestContext.Current.CancellationToken;
        var (first, second) = (Guid.NewGuid(), Guid.NewGuid());
        var migrator = Migrator();
        await migrator.EnsureMigratedAsync(first, ct);
        await migrator.EnsureMigratedAsync(second, ct);

        await using (var db = TenantDb(first)) {
            db.Projects.Add(new Project { Id = Guid.CreateVersion7(), Name = "Only in first", StartDate = new DateOnly(2026, 1, 1), Description = "" });
            await db.SaveChangesAsync(ct);
        }

        await using (var db = TenantDb(second)) {
            Assert.False(await db.Projects.AnyAsync(ct));
        }
    }

    private TenantDatabaseMigrator Migrator(ILogger<TenantDatabaseMigrator>? logger = null) {
        var options = Options.Create(new DatabaseOptions {
            ConnectionString = postgres.ConnectionStringWithoutCredentials,
            Username = postgres.Username,
            Password = postgres.Password,
        });
        return new TenantDatabaseMigrator(new TenantDbContextFactory(options), logger ?? NullLogger<TenantDatabaseMigrator>.Instance);
    }

    /// <summary>The project IDs sharing one name ignoring case, as the migration's error lists them.</summary>
    private static string Group(params Guid[] ids) => $"({string.Join(", ", ids.Select(id => id.ToString()).Order(StringComparer.Ordinal))})";

    private TenantDbContext TenantDb(Guid tid) =>
        new(new DbContextOptionsBuilder<TenantDbContext>().UseNpgsql(postgres.ConnectionString(tid.ToString())).Options);

    private async Task<List<string>> QueryAsync(string database, string sql) {
        await using var connection = new NpgsqlConnection(postgres.ConnectionString(database));
        await connection.OpenAsync(TestContext.Current.CancellationToken);
        await using var command = new NpgsqlCommand(sql, connection);
        await using var reader = await command.ExecuteReaderAsync(TestContext.Current.CancellationToken);
        var values = new List<string>();
        while (await reader.ReadAsync(TestContext.Current.CancellationToken)) {
            values.Add(reader.GetString(0));
        }

        return values;
    }

    private static Document NewDocument(Guid projectId, byte[]? sha256 = null) {
        var id = Guid.CreateVersion7();
        return new Document {
            Id = id,
            ProjectId = projectId,
            BlobName = $"{projectId}/{id}",
            Name = "Bilanz.pdf",
            Size = 10,
            ContentType = "application/pdf",
            Sha256 = sha256 ?? new byte[32],
            CreatedAt = DateTimeOffset.UtcNow,
        };
    }
}
