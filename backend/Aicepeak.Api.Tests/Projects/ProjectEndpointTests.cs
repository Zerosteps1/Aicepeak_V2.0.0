using System.Net;
using System.Text.Json;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.EntityFrameworkCore;
using static Aicepeak.Api.Tests.Infrastructure.BearerRequests;

namespace Aicepeak.Api.Tests.Projects;

/// <summary>
/// AC-13 (create, read and change projects), AC-11 (in the tenant's own database), AC-5 (validation), AC-2 and AC-8
/// against a real PostgreSQL (Docker). Each test uses a fresh tenant.
/// </summary>
[Collection(PostgresCollection.Name)]
[Trait("Category", "Database")]
public sealed class ProjectEndpointTests(PostgresFixture postgres) {
    private const string Base = TenantApi.Base;

    [Fact]
    public async Task AC13_Create_Returns201WithLocation_AndTheProject() {
        await using var api = await TenantApi.CreateAsync(postgres);

        var response = await api.SendJsonAsync(HttpMethod.Post, Base, new {
            name = "Forecast 2026",
            startDate = "2026-01-01",
            endDate = "2026-12-31",
            description = "Planung",
        });

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var project = await TenantApi.ReadJsonAsync(response);
        Assert.Equal(["id", "name", "startDate", "endDate", "description", "documents"], project.EnumerateObject().Select(p => p.Name));
        var id = project.GetProperty("id").GetGuid();
        Assert.Equal(7, id.Version);
        Assert.Equal($"{Base}/{id}", response.Headers.Location?.OriginalString);
        Assert.Equal("Forecast 2026", project.GetProperty("name").GetString());
        Assert.Equal("2026-01-01", project.GetProperty("startDate").GetString());
        Assert.Equal("2026-12-31", project.GetProperty("endDate").GetString());
        Assert.Equal("Planung", project.GetProperty("description").GetString());
        Assert.Equal(0, project.GetProperty("documents").GetArrayLength());
    }

    [Fact]
    public async Task AC13_Create_WithoutOptionalFields_HasNullEndDate_AndEmptyDescription() {
        await using var api = await TenantApi.CreateAsync(postgres);
        var id = await api.CreateProjectAsync("Minimal");

        var project = await api.GetProjectAsync(id);

        Assert.Equal(JsonValueKind.Null, project.GetProperty("endDate").ValueKind);
        Assert.Equal("", project.GetProperty("description").GetString());
    }

    [Fact]
    public async Task AC11_Projects_AreStoredInTheDatabaseOfTheTenant_AndInvisibleToOtherTenants() {
        await using var owner = await TenantApi.CreateAsync(postgres);
        await using var other = await TenantApi.CreateAsync(postgres);
        var id = await owner.CreateProjectAsync("Nur Mandant A");
        await other.CreateProjectAsync("Nur Mandant B");

        var get = await other.Client.GetAsync($"{Base}/{id}", TestContext.Current.CancellationToken);
        var patch = await other.SendJsonAsync(HttpMethod.Patch, $"{Base}/{id}", new { name = "Übernommen" });

        Assert.Equal(HttpStatusCode.NotFound, get.StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, patch.StatusCode);
        await using var db = owner.CreateDb();
        Assert.Equal(owner.Tid.ToString(), db.Database.GetDbConnection().Database);
        Assert.Equal(["Nur Mandant A"], await db.Projects.Select(project => project.Name).ToListAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC13_Get_ReturnsWhatCreateReturned() {
        await using var api = await TenantApi.CreateAsync(postgres);
        var created = await api.SendJsonAsync(HttpMethod.Post, Base, new { name = "P", startDate = "2026-03-01", description = "D" });

        var fetched = await api.Client.GetAsync(created.Headers.Location, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.OK, fetched.StatusCode);
        Assert.Equal(
            await created.Content.ReadAsStringAsync(TestContext.Current.CancellationToken),
            await fetched.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC13_Patch_ChangesOnlyTheGivenFields_AndNullClearsTheEndDate() {
        await using var api = await TenantApi.CreateAsync(postgres);
        var created = await api.SendJsonAsync(HttpMethod.Post, Base, new {
            name = "Alt",
            startDate = "2026-01-01",
            endDate = "2026-06-30",
            description = "Bleibt",
        });
        var id = (await TenantApi.ReadJsonAsync(created)).GetProperty("id").GetGuid();

        var renamed = await api.SendJsonAsync(HttpMethod.Patch, $"{Base}/{id}", new { id, name = "Neu", startDate = "2026-02-01" });
        var cleared = await api.SendRawAsync(HttpMethod.Patch, $"{Base}/{id}", """{"endDate":null}""");

        Assert.Equal(HttpStatusCode.OK, renamed.StatusCode);
        Assert.Equal(HttpStatusCode.OK, cleared.StatusCode);
        var project = await api.GetProjectAsync(id);
        Assert.Equal(await TenantApi.ReadJsonAsync(cleared), project, JsonElementComparer);
        Assert.Equal("Neu", project.GetProperty("name").GetString());
        Assert.Equal("2026-02-01", project.GetProperty("startDate").GetString());
        Assert.Equal(JsonValueKind.Null, project.GetProperty("endDate").ValueKind);
        Assert.Equal("Bleibt", project.GetProperty("description").GetString());
    }

    [Fact]
    public async Task AC13_Patch_EmptyBody_ChangesNothing() {
        await using var api = await TenantApi.CreateAsync(postgres);
        var id = await api.CreateProjectAsync("Unverändert");
        var before = await api.GetProjectAsync(id);

        var response = await api.SendRawAsync(HttpMethod.Patch, $"{Base}/{id}", "{}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(before, await api.GetProjectAsync(id), JsonElementComparer);
    }

    [Fact]
    public async Task AC05_Create_DuplicateName_Returns400() {
        await using var api = await TenantApi.CreateAsync(postgres);
        await api.CreateProjectAsync("Doppelt");

        var response = await api.SendJsonAsync(HttpMethod.Post, Base, new { name = " Doppelt ", startDate = "2026-01-01" });

        Assert.Equal(["is already used by another project"], (await TenantApi.ReadErrorsAsync(response))["name"]);
    }

    [Fact]
    public async Task AC05_Patch_NameOfAnotherProject_Returns400_OwnNameIsFine() {
        await using var api = await TenantApi.CreateAsync(postgres);
        await api.CreateProjectAsync("Erstes");
        var id = await api.CreateProjectAsync("Zweites");

        var taken = await api.SendJsonAsync(HttpMethod.Patch, $"{Base}/{id}", new { name = "Erstes" });
        var own = await api.SendJsonAsync(HttpMethod.Patch, $"{Base}/{id}", new { name = "Zweites" });

        Assert.Equal(["is already used by another project"], (await TenantApi.ReadErrorsAsync(taken))["name"]);
        Assert.Equal(HttpStatusCode.OK, own.StatusCode);
    }

    [Fact]
    public async Task AC05_Create_ListsEveryFailure_AndStoresNothing() {
        await using var api = await TenantApi.CreateAsync(postgres);

        var response = await api.SendRawAsync(HttpMethod.Post, Base, """
            {"id":"0193a5b2-0000-7000-8000-000000000001","name":"","startDate":"2026-05-01","endDate":"2026-04-30","documents":[],"color":"red"}
            """);

        Assert.Equal(["color", "documents", "endDate", "id", "name"], (await TenantApi.ReadErrorsAsync(response)).Keys.Order());
        await using var db = api.CreateDb();
        Assert.False(await db.Projects.AnyAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC05_Patch_InvalidFields_Return400_AndChangeNothing() {
        await using var api = await TenantApi.CreateAsync(postgres);
        var id = await api.CreateProjectAsync("Fest", startDate: "2026-03-01");
        var before = await api.GetProjectAsync(id);

        var response = await api.SendJsonAsync(HttpMethod.Patch, $"{Base}/{id}", new {
            id = Guid.NewGuid(),
            name = "Neu",
            endDate = "2026-02-28",
            unknown = 1,
        });

        var errors = await TenantApi.ReadErrorsAsync(response);
        Assert.Equal(["endDate", "id", "unknown"], errors.Keys.Order());
        Assert.Equal(["endDate must not be before startDate"], errors["endDate"]);
        Assert.Equal(before, await api.GetProjectAsync(id), JsonElementComparer);
    }

    [Theory]
    [InlineData("POST", "")]
    [InlineData("PATCH", "/{id}")]
    [InlineData("POST", "/{id}/upload-url")]
    public async Task AC05_BodyNotJson_Returns415_InvalidJsonOrNoObject_Returns400(string method, string route) {
        await using var api = await TenantApi.CreateAsync(postgres);
        var path = Base + route.Replace("{id}", (await api.CreateProjectAsync()).ToString());

        var text = await api.SendRawAsync(new HttpMethod(method), path, "name=x", "text/plain");
        var broken = await api.SendRawAsync(new HttpMethod(method), path, """{"name":""");
        var array = await api.SendRawAsync(new HttpMethod(method), path, "[]");

        Assert.Equal(HttpStatusCode.UnsupportedMediaType, text.StatusCode);
        Assert.Equal(["is not valid JSON"], (await TenantApi.ReadErrorsAsync(broken))["body"]);
        Assert.Equal(["must be a JSON object"], (await TenantApi.ReadErrorsAsync(array))["body"]);
    }

    [Theory]
    [InlineData("GET", "/{id}")]
    [InlineData("PATCH", "/{id}")]
    [InlineData("POST", "/{id}/upload-url")]
    [InlineData("DELETE", "/{id}/document/0193a5b2-0000-7000-8000-000000000002")]
    [InlineData("DELETE", "/{project}/document/{id}")]
    [InlineData("GET", "/{id}/document-validation/sse")]
    [InlineData("GET", "/{id}/document-extraction/sse")]
    public async Task AC08_AC02_IdsThatAreNoGuidOrUnknown_Return404_AfterAuthentication(string method, string route) {
        await using var api = await TenantApi.CreateAsync(postgres);
        var project = await api.CreateProjectAsync();

        foreach (var id in new[] { "not-a-guid", Guid.NewGuid().ToString() }) {
            var path = Base + route.Replace("{project}", project.ToString()).Replace("{id}", id);
            var response = await api.SendRawAsync(new HttpMethod(method), path, """{"sha256":"00","name":"a.pdf","size":1,"contentType":"application/pdf"}""");

            Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        }
    }

    [Fact]
    public async Task AC08_AppToken_Returns401_AndCreatesNoTenantDatabase() {
        await using var api = await TenantApi.CreateAsync(postgres);
        var client = api.Factory.CreateClient();

        var response = await client.SendAsync(HttpMethod.Get, $"{Base}/{Guid.NewGuid()}", TestTokens.App(api.Tid).Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Empty(api.Factory.AuthenticationFailures);
        await using var db = api.CreateDb();
        Assert.False(await db.Database.CanConnectAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC08_TenantNotAllowed_Returns401() {
        await using var api = await TenantApi.CreateAsync(postgres);
        var client = api.Factory.CreateClient();

        var response = await client.SendAsync(HttpMethod.Post, Base, TestTokens.User(Guid.NewGuid()).Build());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal(Rejections.TenantNotAllowed, api.Factory.SingleRejection());
    }

    private static readonly IEqualityComparer<JsonElement> JsonElementComparer =
        EqualityComparer<JsonElement>.Create((a, b) => JsonElement.DeepEquals(a, b), element => element.GetRawText().GetHashCode());
}
