using System.Net;
using System.Text.Json;
using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.Tokens;
using Npgsql;
using static Aicepeak.Api.Tests.Infrastructure.BearerRequests;

namespace Aicepeak.Api.Tests.Auth;

/// <summary>
/// AC-3, AC-4, AC-7, AC-9, AC-11, AC-16, AC-18 and AC-19 for <c>PUT /api/v1/login</c> and the protected API against a
/// real PostgreSQL (Docker). The Users table is emptied before each test, so "no record" means an empty table.
/// </summary>
[Collection(PostgresCollection.Name)]
[Trait("Category", "Database")]
public sealed class LoginDatabaseTests(PostgresFixture postgres) : IAsyncLifetime {
    private const string Database = "login_test";

    public async ValueTask InitializeAsync() {
        await using var db = CreateDb();
        await db.Database.MigrateAsync(TestContext.Current.CancellationToken);
        await db.Database.ExecuteSqlAsync($"TRUNCATE \"Users\"", TestContext.Current.CancellationToken);
    }

    public ValueTask DisposeAsync() => ValueTask.CompletedTask;

    [Fact]
    public async Task AC03_FirstLogin_CreatesExactlyOneUser_AndReturnsItAsJson() {
        await using var factory = CreateFactory();
        var oid = Guid.NewGuid();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Put, LoginPath, TestTokens.User(oid: oid).Build());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("application/json", response.Content.Headers.ContentType?.MediaType);
        using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Equal(["tid", "oid", "name"], json.RootElement.EnumerateObject().Select(property => property.Name));
        Assert.Equal(TestTokens.AllowedTenant.ToString(), json.RootElement.GetProperty("tid").GetString());
        Assert.Equal(oid.ToString(), json.RootElement.GetProperty("oid").GetString());
        Assert.Equal("Ada Lovelace", json.RootElement.GetProperty("name").GetString());
        var user = Assert.Single(await UsersAsync());
        Assert.Equal((TestTokens.AllowedTenant, oid, "Ada Lovelace"), (user.Tid, user.Oid, user.Name));
    }

    [Theory]
    [InlineData("name", "Ada Lovelace")]
    [InlineData("preferred_username", "ada@example.test")]
    [InlineData("none", "")]
    public async Task AC03_FirstLogin_StoresNameFromNameClaim_ElsePreferredUsername(string source, string expected) {
        await using var factory = CreateFactory();
        var token = source switch {
            "name" => TestTokens.User(),
            "preferred_username" => TestTokens.User().Without("name"),
            _ => TestTokens.User().Without("name").Without("preferred_username"),
        };

        var response = await factory.CreateClient().SendAsync(HttpMethod.Put, LoginPath, token.Build());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(expected, Assert.Single(await UsersAsync()).Name);
    }

    [Fact]
    public async Task AC04_SecondLogin_CreatesNoSecondUser_AndReturnsTheStoredRecord() {
        await using var factory = CreateFactory();
        var client = factory.CreateClient();
        var oid = Guid.NewGuid();

        var first = await client.SendAsync(HttpMethod.Put, LoginPath, TestTokens.User(oid: oid).Build());
        var second = await client.SendAsync(HttpMethod.Put, LoginPath, TestTokens.User(oid: oid).With("name", "Renamed").Build());

        Assert.Equal(HttpStatusCode.OK, first.StatusCode);
        Assert.Equal(HttpStatusCode.OK, second.StatusCode);
        Assert.Equal(
            await first.Content.ReadAsStringAsync(TestContext.Current.CancellationToken),
            await second.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Equal("Ada Lovelace", Assert.Single(await UsersAsync()).Name);
    }

    [Fact]
    public async Task AC04_ConcurrentLogins_CreateExactlyOneUser() {
        await using var factory = CreateFactory();
        var client = factory.CreateClient();
        var token = TestTokens.User().Build();

        var responses = await Task.WhenAll(Enumerable.Range(0, 20)
            .Select(_ => client.SendAsync(HttpMethod.Put, LoginPath, token)));

        Assert.All(responses, response => Assert.Equal(HttpStatusCode.OK, response.StatusCode));
        Assert.Single(await UsersAsync());
    }

    [Fact]
    public async Task AC04_LoginRacingAnotherLogin_ReturnsTheRecordStoredFirst_WithoutSecondUser() {
        // Another sign-in of the same user inserts the record between this request's lookup and its insert.
        var racer = new ConcurrentInsertInterceptor(postgres.ConnectionString(Database), "Stored first");
        await using var factory = CreateFactory(services =>
            services.ConfigureDbContext<AppDbContext>(options => options.AddInterceptors(racer)));

        var response = await factory.CreateClient().SendAsync(HttpMethod.Put, LoginPath, TestTokens.User().Build());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.True(racer.Inserted);
        using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        Assert.Equal("Stored first", json.RootElement.GetProperty("name").GetString());
        Assert.Equal("Stored first", Assert.Single(await UsersAsync()).Name);
    }

    [Fact]
    public async Task AC19_SameOidInAnotherAllowedTenant_CreatesASecondUser() {
        var otherTenant = new Guid("5c3f1a2b-7d4e-4f60-8a9b-0c1d2e3f4a5b");
        await using (var db = CreateDb()) {
            await db.Database.ExecuteSqlAsync(
                $"INSERT INTO allowed_tenants (tid) VALUES ({otherTenant}) ON CONFLICT DO NOTHING",
                TestContext.Current.CancellationToken);
        }

        await using var factory = CreateFactory();
        var client = factory.CreateClient();
        var oid = Guid.NewGuid();

        var first = await client.SendAsync(HttpMethod.Put, LoginPath, TestTokens.User(oid: oid).Build());
        var second = await client.SendAsync(HttpMethod.Put, LoginPath, TestTokens.User(otherTenant, oid).Build());

        Assert.Equal(HttpStatusCode.OK, first.StatusCode);
        Assert.Equal(HttpStatusCode.OK, second.StatusCode);
        var users = await UsersAsync();
        Assert.Equal(2, users.Count);
        Assert.All(users, user => Assert.Equal(oid, user.Oid));
        Assert.Equal(new[] { TestTokens.AllowedTenant, otherTenant }.Order(), users.Select(user => user.Tid).Order());
    }

    [Fact]
    public async Task AC09_TenantNotInAllowlist_Returns401_AndCreatesNoUser() {
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Put, LoginPath, TestTokens.User(Guid.NewGuid()).Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal(Rejections.TenantNotAllowed, factory.SingleRejection());
        Assert.Empty(await UsersAsync());
    }

    [Theory]
    [InlineData("User.Read")]
    [InlineData("access_as_user_admin")]
    [InlineData("xaccess_as_user")]
    [InlineData("Access_As_User")]
    [InlineData("access_as_user,User.Read")]
    [InlineData("")]
    public async Task AC11_UserTokenWithoutRequiredScope_Returns401_AndCreatesNoUser(string scope) {
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Put, LoginPath, TestTokens.User().With("scp", scope).Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal(Rejections.MissingScope, factory.SingleRejection());
        Assert.Empty(await UsersAsync());
    }

    [Fact]
    public async Task AC11_UserTokenWithSeveralScopes_IncludingTheRequiredOne_CreatesUser() {
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(
            HttpMethod.Put, LoginPath, TestTokens.User().With("scp", "User.Read access_as_user openid").Build());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Single(await UsersAsync());
    }

    [Theory]
    [InlineData("no-roles")]
    [InlineData("other-role")]
    [InlineData("no-idtyp")]
    [InlineData("idtyp-user")]
    public async Task AC11_AppTokenWithoutRequiredRoleOrIdtypApp_Returns401_AndCreatesNoUser(string kind) {
        var token = kind switch {
            "no-roles" => TestTokens.App().Without("roles"),
            "other-role" => TestTokens.App().With("roles", new[] { "Api.Other" }),
            "no-idtyp" => TestTokens.App().Without("idtyp"),
            "idtyp-user" => TestTokens.App().With("idtyp", "user"),
            _ => throw new ArgumentOutOfRangeException(nameof(kind)),
        };
        await using var factory = CreateFactory();
        var client = factory.CreateClient();

        var onProtected = await client.SendAsync(HttpMethod.Get, ProtectedPath, token.Build());
        var onLogin = await client.SendAsync(HttpMethod.Put, LoginPath, token.Build());

        Assert.Equal(HttpStatusCode.Unauthorized, onProtected.StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, onLogin.StatusCode);
        Assert.All(factory.AuthenticationFailures, failure => Assert.Equal(Rejections.NotAnAppToken, failure.Message));
        Assert.Equal(2, factory.AuthenticationFailures.Count);
        Assert.Empty(await UsersAsync());
    }

    [Fact]
    public async Task AC11_ValidAppToken_IsAcceptedByTheProtectedApi() {
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Get, ProtectedPath, TestTokens.App().Build());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Empty(factory.AuthenticationFailures);
    }

    [Fact]
    public async Task AC11_ValidAppToken_OnLogin_Returns401_AndCreatesNoUser() {
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Put, LoginPath, TestTokens.App().Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        // Authenticated, but app tokens never get a user record.
        Assert.Empty(factory.AuthenticationFailures);
        Assert.Empty(await UsersAsync());
    }

    [Theory]
    [InlineData("no-tid", nameof(SecurityTokenInvalidIssuerException))]
    [InlineData("tid-not-a-guid", Rejections.NoTidOrOid)]
    [InlineData("no-oid", Rejections.NoTidOrOid)]
    [InlineData("oid-not-a-guid", Rejections.NoTidOrOid)]
    public async Task AC16_TokenWithoutValidTidOrOid_Returns401_AndCreatesNoUser(string kind, string rejection) {
        var token = kind switch {
            "no-tid" => TestTokens.User().Without("tid"),
            "tid-not-a-guid" => TestTokens.User().With("tid", "contoso").With("iss", "https://login.microsoftonline.com/contoso/v2.0"),
            "no-oid" => TestTokens.User().Without("oid"),
            "oid-not-a-guid" => TestTokens.User().With("oid", "not-a-guid"),
            _ => throw new ArgumentOutOfRangeException(nameof(kind)),
        };
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Put, LoginPath, token.Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal(rejection, factory.SingleRejection());
        Assert.Empty(await UsersAsync());
    }

    [Theory]
    [InlineData("expired-4-minutes-ago")]
    [InlineData("valid-in-4-minutes")]
    public async Task AC18_LifetimeInsideFiveMinuteSkew_IsAccepted(string kind) {
        var token = kind == "expired-4-minutes-ago"
            ? TestTokens.User().NotBefore(TimeSpan.FromHours(-1)).ExpiresIn(TimeSpan.FromMinutes(-4))
            : TestTokens.User().NotBefore(TimeSpan.FromMinutes(4));
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Put, LoginPath, token.Build());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Single(await UsersAsync());
    }

    [Theory]
    [InlineData("signed-with-other-key")]
    [InlineData("unsigned")]
    [InlineData("signed-with-rs384")]
    [InlineData("garbage")]
    [InlineData("expired")]
    public async Task AC07_InvalidOrExpiredToken_Returns401_AndCreatesNoUser(string kind) {
        var token = kind switch {
            "signed-with-other-key" => TestTokens.User().SignedWith(TestTokens.CreateKey(TestTokens.KeyId)).Build(),
            "unsigned" => TestTokens.User().SignedWith(null).Build(),
            "signed-with-rs384" => TestTokens.User().SignedWith(TestTokens.SigningKey, SecurityAlgorithms.RsaSha384).Build(),
            "garbage" => "not-a-jwt",
            "expired" => TestTokens.User().NotBefore(TimeSpan.FromHours(-2)).ExpiresIn(TimeSpan.FromHours(-1)).Build(),
            _ => throw new ArgumentOutOfRangeException(nameof(kind)),
        };
        await using var factory = CreateFactory();

        var response = await factory.CreateClient().SendAsync(HttpMethod.Put, LoginPath, token);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Single(factory.AuthenticationFailures);
        Assert.Empty(await UsersAsync());
    }

    private ApiFactory CreateFactory(Action<IServiceCollection>? configureServices = null) =>
        new(TestSettings.Production, TestSettings.WithEntra(postgres.Settings(database: Database)), configureServices: configureServices);

    private AppDbContext CreateDb() =>
        new(new DbContextOptionsBuilder<AppDbContext>().UseNpgsql(postgres.ConnectionString(Database)).Options);

    private async Task<List<User>> UsersAsync() {
        await using var db = CreateDb();
        return await db.Users.AsNoTracking().ToListAsync(TestContext.Current.CancellationToken);
    }

    /// <summary>Inserts each user the API is about to insert through another connection first, once.</summary>
    private sealed class ConcurrentInsertInterceptor(string connectionString, string name) : SaveChangesInterceptor {
        public bool Inserted { get; private set; }

        public override async ValueTask<InterceptionResult<int>> SavingChangesAsync(
            DbContextEventData eventData, InterceptionResult<int> result, CancellationToken cancellationToken = default) {
            var added = eventData.Context!.ChangeTracker.Entries<User>().Where(entry => entry.State == EntityState.Added).ToList();
            if (Inserted || added.Count == 0) {
                return result;
            }

            await using var connection = new NpgsqlConnection(connectionString);
            await connection.OpenAsync(cancellationToken);
            foreach (var user in added.Select(entry => entry.Entity)) {
                await using var command = new NpgsqlCommand("INSERT INTO \"Users\" (\"Tid\", \"Oid\", \"Name\") VALUES ($1, $2, $3)", connection) {
                    Parameters = { new() { Value = user.Tid }, new() { Value = user.Oid }, new() { Value = name } },
                };
                await command.ExecuteNonQueryAsync(cancellationToken);
            }

            Inserted = true;
            return result;
        }
    }
}
