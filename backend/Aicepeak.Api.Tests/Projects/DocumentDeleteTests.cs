using System.Net;
using System.Text.Json;
using Aicepeak.Api.Storage;
using Aicepeak.Api.Storage.Azure;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Aicepeak.Api.Tests.Projects;

/// <summary>
/// <c>DELETE /project/{id}/document/{documentId}</c> against PostgreSQL and Azurite (Docker): AC-6 (the project's link
/// goes; row and blob only with the last link) and AC-6b (a failing blob deletion changes nothing).
/// </summary>
[Collection(StorageCollection.Name)]
[Trait("Category", "Database")]
public sealed class DocumentDeleteTests(PostgresFixture postgres, AzuriteFixture azurite) {
    private const string Base = TenantApi.Base;

    [Fact]
    public async Task AC06_LastReference_DeletesLinkRowAndBlob() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var projectId = await api.CreateProjectAsync();
        var kept = await api.AddDocumentAsync(projectId, TenantApi.File("a1"), "Bleibt.pdf");
        var removed = await api.AddDocumentAsync(projectId, TenantApi.File("a2"), "Weg.pdf");

        var response = await DeleteAsync(api, projectId, removed);

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        Assert.Equal([kept], Documents(await api.GetProjectAsync(projectId)));
        await using var db = api.CreateDb();
        Assert.False(await db.Documents.AnyAsync(document => document.Id == Guid.Parse(TenantApi.DocumentId(removed.Url)), TestContext.Current.CancellationToken));
        Assert.False(await Blob(api, projectId, removed).ExistsAsync(TestContext.Current.CancellationToken));
        Assert.True(await Blob(api, projectId, kept).ExistsAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC06_SharedDocument_OnlyLosesThisProjectsLink() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var uploader = await api.CreateProjectAsync();
        var other = await api.CreateProjectAsync();
        var shared = await api.AddDocumentAsync(uploader, TenantApi.File("b"), "Geteilt.pdf");
        Assert.Equal(HttpStatusCode.OK, (await api.PatchDocumentsAsync(other, shared)).StatusCode);

        var fromUploader = await DeleteAsync(api, uploader, shared);

        Assert.Equal(HttpStatusCode.NoContent, fromUploader.StatusCode);
        Assert.Empty(Documents(await api.GetProjectAsync(uploader)));
        Assert.Equal([shared], Documents(await api.GetProjectAsync(other)));
        Assert.True(await Blob(api, uploader, shared).ExistsAsync(TestContext.Current.CancellationToken));

        var fromOther = await DeleteAsync(api, other, shared);

        Assert.Equal(HttpStatusCode.NoContent, fromOther.StatusCode);
        Assert.False(await Blob(api, uploader, shared).ExistsAsync(TestContext.Current.CancellationToken));
        await using var db = api.CreateDb();
        Assert.False(await db.Documents.AnyAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC06_DocumentNotLinkedToTheProject_Returns404_AndNothingChanges() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite);
        var owner = await api.CreateProjectAsync();
        var other = await api.CreateProjectAsync();
        var document = await api.AddDocumentAsync(owner, TenantApi.File("c"), "Bilanz.pdf");

        var notLinked = await DeleteAsync(api, other, document);
        var unknownDocument = await api.Client.DeleteAsync($"{Base}/{owner}/document/{Guid.NewGuid()}", TestContext.Current.CancellationToken);
        var unknownProject = await api.Client.DeleteAsync(
            $"{Base}/{Guid.NewGuid()}/document/{TenantApi.DocumentId(document.Url)}", TestContext.Current.CancellationToken);

        Assert.All([notLinked, unknownDocument, unknownProject], response => Assert.Equal(HttpStatusCode.NotFound, response.StatusCode));
        Assert.Equal([document], Documents(await api.GetProjectAsync(owner)));
        Assert.True(await Blob(api, owner, document).ExistsAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task AC06b_BlobCannotBeDeleted_RollsBackLinkAndRow() {
        await using var api = await TenantApi.CreateAsync(postgres, azurite, services => services.AddSingleton<IBlobStorage>(
            provider => new FailingDeletes(ActivatorUtilities.CreateInstance<AzureBlobStorage>(provider))));
        var projectId = await api.CreateProjectAsync();
        var document = await api.AddDocumentAsync(projectId, TenantApi.File("d"), "Bilanz.pdf");

        var response = await DeleteAsync(api, projectId, document);

        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.Equal([document], Documents(await api.GetProjectAsync(projectId)));
        await using var db = api.CreateDb();
        Assert.Equal(1, await db.Documents.CountAsync(TestContext.Current.CancellationToken));
        Assert.True(await Blob(api, projectId, document).ExistsAsync(TestContext.Current.CancellationToken));
    }

    private static Task<HttpResponseMessage> DeleteAsync(TenantApi api, Guid projectId, DocumentRefBody document) =>
        api.Client.DeleteAsync($"{Base}/{projectId}/document/{TenantApi.DocumentId(document.Url)}", TestContext.Current.CancellationToken);

    private static Azure.Storage.Blobs.BlobClient Blob(TenantApi api, Guid uploader, DocumentRefBody document) =>
        api.Container.GetBlobClient($"{uploader}/{TenantApi.DocumentId(document.Url)}");

    private static List<DocumentRefBody> Documents(JsonElement project) =>
        project.GetProperty("documents").Deserialize<List<DocumentRefBody>>(JsonSerializerOptions.Web)!;

    /// <summary>The real storage, except that deleting a blob fails as when the storage is unreachable.</summary>
    private sealed class FailingDeletes(IBlobStorage inner) : IBlobStorage {
        public Task<bool> DeleteAsync(string space, string name, CancellationToken cancellationToken) =>
            throw new HttpRequestException("Storage unreachable.");

        public Task<Uri> CreateUploadUrlAsync(string space, string name, DateTimeOffset expiresOn, CancellationToken cancellationToken) =>
            inner.CreateUploadUrlAsync(space, name, expiresOn, cancellationToken);

        public Uri GetUrl(string space, string name) => inner.GetUrl(space, name);

        public bool TryParseUrl(Uri url, out string space, out string name) => inner.TryParseUrl(url, out space, out name);

        public Task<BlobInfo?> GetInfoAsync(string space, string name, CancellationToken cancellationToken) =>
            inner.GetInfoAsync(space, name, cancellationToken);

        public Task<Stream> OpenReadAsync(string space, string name, CancellationToken cancellationToken) =>
            inner.OpenReadAsync(space, name, cancellationToken);

        public IAsyncEnumerable<BlobListItem> ListAsync(string space, CancellationToken cancellationToken) => inner.ListAsync(space, cancellationToken);

        public Task<bool> SpaceExistsAsync(string space, CancellationToken cancellationToken) => inner.SpaceExistsAsync(space, cancellationToken);
    }
}
